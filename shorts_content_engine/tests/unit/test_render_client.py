"""Unit tests for FlowKit integration subsystem (Milestone 2).

Covers:
1. FlowKit Pydantic V2 Models & Schema Constraints
2. Domain Adapter & S2P Prompt Decoupling
3. Asynchronous FlowKitClient & Two-Step Scene Initialization
4. Resilient Batch Poller (total=0 guard & failure detection)
5. Fault-Tolerant Audio Mixer & Scene Concatenation
6. FlowKit Orchestrator (Mock/Simulation Pipeline)
7. Standalone Payload Validation Suite
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from scripts.validate_flowkit_payloads import validate_manifest_payloads
from src.director.character import CharacterRegistry, build_default_characters
from src.director.director import StoryDirector
from src.render_client.adapter import FlowKitPayloadAdapter, slugify_name
from src.render_client.client import FlowKitClient
from src.render_client.models import (
    BatchStatus,
    CharacterInput,
    FlowKitCharacterCreate,
    FlowKitNarrateVideoRequest,
    FlowKitProjectCreate,
    FlowKitRequestCreate,
    FlowKitSceneCreate,
    FlowKitSceneUpdate,
    FlowKitVideoCreate,
    ProjectCreate,
    SceneCreate,
    SceneUpdate,
)
from src.render_client.orchestrator import (
    FlowKitOrchestrator,
    check_stream_has_audio,
    concatenate_scenes,
    mix_narration_resilient,
)
from src.models import (
    CharacterProfile,
    EntityType,
    EpisodeManifest,
    SceneBeat,
    SeriesState,
)


@pytest.fixture
def sample_manifest() -> EpisodeManifest:
    """Fixture producing a canonical EpisodeManifest for testing."""
    characters = build_default_characters()
    series_state = SeriesState(
        series_id="cyber_noir",
        title="The Obsidian Directive",
        genre="Sci-Fi Cyberpunk Noir",
        premise="Detective Vance hunts a rogue temporal physicist.",
        characters={c.character_id: c for c in characters},
    )
    director = StoryDirector()
    return director.direct_episode(
        series_state=series_state,
        episode_num=1,
        target_duration=45.0,
    )


# ==============================================================================
# 1. Pydantic Models & Schema Validation Tests
# ==============================================================================

class TestFlowKitModels:
    """Tests for FlowKit Pydantic schemas mirroring API specifications."""

    def test_project_create_valid(self):
        """Verifies valid project creation payload and style mapping."""
        p = FlowKitProjectCreate(
            name="Cyber Noir Ep 1",
            material="realistic",
            characters=[
                CharacterInput(name="Rex Vance", entity_type="character", description="Detective"),
                CharacterInput(name="Safehouse", entity_type="location", description="Bunker"),
            ],
        )
        assert p.name == "Cyber Noir Ep 1"
        assert p.material == "realistic"
        assert len(p.characters) == 2
        assert p.characters[1].entity_type == "location"

        # Test legacy style mapping
        p_legacy = ProjectCreate(name="Pixar Ep", style="3D")
        assert p_legacy.material == "3d_pixar"

    def test_project_create_invalid_material(self):
        """Verifies that invalid material slugs are rejected by regex pattern."""
        with pytest.raises(ValidationError):
            FlowKitProjectCreate(name="Test", material="Invalid Material With Spaces!")

    def test_character_create_valid(self):
        """Verifies character and location entity creation schemas."""
        char = FlowKitCharacterCreate(
            name="Detective Vance",
            entity_type="character",
            description="Weathered trench coat",
            voice_description="Gravelly baritone",
        )
        assert char.entity_type == "character"

        loc = FlowKitCharacterCreate(
            name="Neon Alley",
            entity_type="location",
            image_prompt="Wide establishing landscape shot",
        )
        assert loc.entity_type == "location"
        assert loc.voice_description is None

    def test_character_create_invalid_entity_type(self):
        """Verifies rejection of unsupported entity types."""
        with pytest.raises(ValidationError):
            FlowKitCharacterCreate(name="Invalid", entity_type="spaceship")

    def test_video_create_valid(self):
        """Verifies video container payload creation."""
        vid = FlowKitVideoCreate(
            project_id="proj_123",
            title="Episode 1",
            orientation="VERTICAL",
        )
        assert vid.project_id == "proj_123"
        assert vid.orientation == "VERTICAL"

    def test_scene_create_omits_narrator_text(self):
        """Verifies that SceneCreate omits narrator_text while SceneUpdate supports it."""
        scene = SceneCreate(
            video_id="vid_123",
            prompt="Medium shot of Vance in the rain",
            video_prompt="0-3s: Vance looks left; 3-6s: walks forward",
            character_names=["char_rex_vance"],
        )
        assert "narrator_text" not in scene.model_dump()

        update = SceneUpdate(narrator_text="The rain never stopped in Sector 4.")
        assert update.narrator_text == "The rain never stopped in Sector 4."

    def test_request_create_dependency_validation(self):
        """Verifies custom model validators on RequestCreate dependencies."""
        # Valid scene request
        req = FlowKitRequestCreate(
            type="GENERATE_IMAGE",
            scene_id="s1",
            project_id="p1",
            video_id="v1",
        )
        assert req.type == "GENERATE_IMAGE"

        # Missing scene_id for GENERATE_IMAGE
        with pytest.raises(ValidationError) as exc_info:
            FlowKitRequestCreate(type="GENERATE_IMAGE", project_id="p1", video_id="v1")
        assert "scene_id is required" in str(exc_info.value)

        # Missing character_id for GENERATE_CHARACTER_IMAGE
        with pytest.raises(ValidationError) as exc_info:
            FlowKitRequestCreate(type="GENERATE_CHARACTER_IMAGE", project_id="p1")
        assert "character_id is required" in str(exc_info.value)

    def test_narrate_video_request_validation(self):
        """Verifies boundary constraints on speed and sfx_volume."""
        req = FlowKitNarrateVideoRequest(
            project_id="p1",
            speed=1.5,
            sfx_volume=0.4,
            instruct="male, low pitch, intense",
        )
        assert req.speed == 1.5
        assert req.sfx_volume == 0.4

        # Speed out of bounds
        with pytest.raises(ValidationError):
            FlowKitNarrateVideoRequest(project_id="p1", speed=4.0)

        # SFX volume out of bounds
        with pytest.raises(ValidationError):
            FlowKitNarrateVideoRequest(project_id="p1", sfx_volume=-0.1)

    def test_batch_status_model(self):
        """Verifies BatchStatus schema fields and status computation."""
        bs = BatchStatus(
            total=5,
            pending=0,
            processing=0,
            completed=5,
            failed=0,
            done=True,
            all_succeeded=True,
        )
        assert bs.done is True
        assert bs.all_succeeded is True


# ==============================================================================
# 2. FlowKit Adapter Tests
# ==============================================================================

class TestFlowKitAdapter:
    """Tests adapting domain models into FlowKit payloads."""

    def test_slugify_name(self):
        """Verifies name slugification utility."""
        assert slugify_name("Detective Rex Vance") == "detective_rex_vance"
        assert slugify_name("Dr. Aris Thorne!") == "dr_aris_thorne"
        assert slugify_name("Subterranean-Bank Vault") == "subterranean_bank_vault"

    def test_to_project_payload(self, sample_manifest: EpisodeManifest):
        """Verifies conversion of EpisodeManifest to FlowKitProjectCreate."""
        payload = FlowKitPayloadAdapter.to_project_payload(
            manifest=sample_manifest,
            material="realistic",
        )
        assert "cyber_noir" in payload.name
        assert payload.material == "realistic"
        assert payload.characters is not None
        assert len(payload.characters) == len(sample_manifest.character_profiles)

    def test_to_character_payloads(self, sample_manifest: EpisodeManifest):
        """Verifies conversion of CharacterProfiles with EntityType segregation."""
        payloads = FlowKitPayloadAdapter.to_character_payloads(sample_manifest.character_profiles)
        assert len(payloads) == len(sample_manifest.character_profiles)

        # Check character entity
        rex = next(p for p in payloads if "Rex" in p.name)
        assert rex.entity_type == "character"
        assert rex.voice_description is not None

        # Check location entity
        vault = next((p for p in payloads if p.entity_type == "location"), None)
        if vault:
            assert vault.entity_type == "location"
            assert vault.voice_description is None
            assert "landscape" in vault.image_prompt.lower()

    def test_to_video_payload(self, sample_manifest: EpisodeManifest):
        """Verifies video container conversion."""
        v_pay = FlowKitPayloadAdapter.to_video_payload(
            manifest=sample_manifest,
            project_id="proj_xyz",
            orientation="VERTICAL",
        )
        assert v_pay.project_id == "proj_xyz"
        assert v_pay.orientation == "VERTICAL"
        assert f"Ep {sample_manifest.episode_num}" in v_pay.title

    def test_to_scene_payloads_two_step(self, sample_manifest: EpisodeManifest):
        """Verifies two-step scene conversion separating FlowKitSceneCreate and narrator_text."""
        pairs = FlowKitPayloadAdapter.to_scene_payloads(sample_manifest, video_id="vid_123")
        assert len(pairs) == len(sample_manifest.scenes)

        for idx, (scene_create, narrator_text) in enumerate(pairs):
            assert scene_create.video_id == "vid_123"
            assert scene_create.display_order == idx
            assert scene_create.prompt == sample_manifest.scenes[idx].action_prompt
            assert narrator_text == sample_manifest.scenes[idx].narration.strip()

    def test_to_batch_requests(self):
        """Verifies batch generation request generation."""
        scene_ids = ["s1", "s2", "s3"]
        reqs = FlowKitPayloadAdapter.to_batch_requests(
            scene_ids=scene_ids,
            project_id="p1",
            video_id="v1",
            req_type="GENERATE_IMAGE",
        )
        assert len(reqs) == 3
        for r in reqs:
            assert r.type == "GENERATE_IMAGE"
            assert r.project_id == "p1"
            assert r.video_id == "v1"


# ==============================================================================
# 3. Asynchronous FlowKit Client Tests
# ==============================================================================

class TestFlowKitClient:
    """Tests FlowKitClient API interactions and resilient behaviors."""

    @pytest.mark.asyncio
    async def test_client_verify_connection(self):
        """Verifies connection verification behavior with mocked HTTP responses."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"connected": True, "transport": "batch"})
        )
        async with httpx.AsyncClient(transport=mock_transport, base_url="http://test") as http_c:
            client = FlowKitClient(client=http_c)
            assert await client.verify_connection() is True

        mock_fail_transport = httpx.MockTransport(
            lambda request: httpx.Response(500, json={"error": "disconnected"})
        )
        async with httpx.AsyncClient(transport=mock_fail_transport, base_url="http://test") as http_c:
            client = FlowKitClient(client=http_c)
            assert await client.verify_connection() is False

    @pytest.mark.asyncio
    async def test_client_two_step_scene_creation(self):
        """Verifies that create_scene calls POST /scenes then PATCH /scenes/{id} for narrator_text."""
        posted_bodies: list[dict[str, Any]] = []
        patched_bodies: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json
            data = json.loads(request.content.decode("utf-8"))
            if request.method == "POST" and request.url.path == "/scenes":
                posted_bodies.append(data)
                return httpx.Response(201, json={"id": "scene_mock_001", **data})
            if request.method == "PATCH" and request.url.path == "/scenes/scene_mock_001":
                patched_bodies.append(data)
                return httpx.Response(200, json={"id": "scene_mock_001", "narrator_text": data.get("narrator_text")})
            return httpx.Response(404)

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport, base_url="http://test") as http_c:
            client = FlowKitClient(client=http_c)
            scene_create = FlowKitSceneCreate(
                video_id="vid_1",
                prompt="Detective enters room",
                video_prompt="0-3s: walks in",
            )
            created = await client.create_scene(scene_create, narrator_text="He knew it was a trap.")

            assert created["id"] == "scene_mock_001"
            assert len(posted_bodies) == 1
            assert "narrator_text" not in posted_bodies[0]
            assert len(patched_bodies) == 1
            assert patched_bodies[0]["narrator_text"] == "He knew it was a trap."

    @pytest.mark.asyncio
    async def test_client_resilient_batch_polling_guard(self):
        """Verifies that poll_batch_resilient DOES NOT exit when total == 0, done == True."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Trap: total=0 but done=True!
                return httpx.Response(
                    200,
                    json={
                        "total": 0,
                        "pending": 0,
                        "processing": 0,
                        "completed": 0,
                        "failed": 0,
                        "done": True,
                        "all_succeeded": False,
                    },
                )
            # Call 2: DB has indexed all 3 requests and completed them
            return httpx.Response(
                200,
                json={
                    "total": 3,
                    "pending": 0,
                    "processing": 0,
                    "completed": 3,
                    "failed": 0,
                    "done": True,
                    "all_succeeded": True,
                },
            )

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport, base_url="http://test") as http_c:
            client = FlowKitClient(client=http_c)
            status = await client.poll_batch_resilient(
                expected_count=3,
                video_id="vid_test",
                req_type="GENERATE_IMAGE",
                poll_interval=0.01,
            )
            assert status.total == 3
            assert status.all_succeeded is True
            assert call_count >= 2  # Proves it didn't exit on call 1!

    @pytest.mark.asyncio
    async def test_client_batch_polling_failure_detection(self):
        """Verifies that poll_batch_resilient detects failures and raises RuntimeError."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "total": 3,
                    "pending": 0,
                    "processing": 0,
                    "completed": 2,
                    "failed": 1,
                    "done": True,
                    "all_succeeded": False,
                },
            )

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport, base_url="http://test") as http_c:
            client = FlowKitClient(client=http_c)
            with pytest.raises(RuntimeError) as exc_info:
                await client.poll_batch_resilient(
                    expected_count=3,
                    video_id="vid_test",
                    req_type="GENERATE_VIDEO",
                    poll_interval=0.01,
                )
            assert "completed with 1 failure(s)" in str(exc_info.value)


# ==============================================================================
# 4. Audio Mixer & Video Concatenation Tests
# ==============================================================================

class TestResilientAudioMixerAndConcat:
    """Tests dual-path audio ducking and video concatenation with real FFmpeg execution."""

    def test_dual_path_audio_mixer_with_silent_video(self):
        """Verifies that mix_narration_resilient succeeds on silent video (without audio stream).
        
        This tests the fix for the fatal code 4294967274 FFmpeg filtergraph crash.
        """
        with tempfile.TemporaryDirectory() as td:
            silent_mp4 = os.path.join(td, "silent.mp4")
            audio_wav = os.path.join(td, "narration.wav")
            mixed_mp4 = os.path.join(td, "mixed.mp4")

            # 1. Create a synthetic silent video (no audio track)
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=360x640:d=1", "-c:v", "libx264", silent_mp4],
                capture_output=True,
                check=True,
            )
            assert check_stream_has_audio(silent_mp4) is False

            # 2. Create synthetic audio
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=800:duration=1", audio_wav],
                capture_output=True,
                check=True,
            )

            # 3. Mix narration
            ok = mix_narration_resilient(
                video_path=silent_mp4,
                audio_path=audio_wav,
                output_path=mixed_mp4,
                sfx_vol=0.4,
            )
            assert ok is True
            assert os.path.exists(mixed_mp4)
            assert os.path.getsize(mixed_mp4) > 1000
            assert check_stream_has_audio(mixed_mp4) is True

    def test_dual_path_audio_mixer_with_audio_track(self):
        """Verifies dual-stream audio ducking when video already possesses an ambient audio track."""
        with tempfile.TemporaryDirectory() as td:
            video_with_audio = os.path.join(td, "video_audio.mp4")
            audio_wav = os.path.join(td, "narration.wav")
            mixed_mp4 = os.path.join(td, "mixed.mp4")

            # 1. Create video with audio stream
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=360x640:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=200:duration=1",
                    "-c:v", "libx264", "-c:a", "aac", video_with_audio,
                ],
                capture_output=True,
                check=True,
            )
            assert check_stream_has_audio(video_with_audio) is True

            # 2. Create narration audio
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=1", audio_wav],
                capture_output=True,
                check=True,
            )

            # 3. Mix narration
            ok = mix_narration_resilient(
                video_path=video_with_audio,
                audio_path=audio_wav,
                output_path=mixed_mp4,
                sfx_vol=0.3,
            )
            assert ok is True
            assert os.path.exists(mixed_mp4)
            assert check_stream_has_audio(mixed_mp4) is True

    def test_video_concatenation(self):
        """Verifies concatenation of multiple scene clips into an assembled video."""
        with tempfile.TemporaryDirectory() as td:
            clip1 = os.path.join(td, "clip1.mp4")
            clip2 = os.path.join(td, "clip2.mp4")
            assembled = os.path.join(td, "assembled.mp4")

            for p in (clip1, clip2):
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", "color=c=red:s=360x640:d=1",
                        "-f", "lavfi", "-i", "sine=frequency=300:duration=1",
                        "-c:v", "libx264", "-c:a", "aac", p,
                    ],
                    capture_output=True,
                    check=True,
                )

            ok = concatenate_scenes([clip1, clip2], assembled)
            assert ok is True
            assert os.path.exists(assembled)
            assert os.path.getsize(assembled) > 1000


# ==============================================================================
# 5. FlowKit Orchestrator Pipeline Tests
# ==============================================================================

class TestFlowKitOrchestrator:
    """Tests end-to-end orchestration in both mock/simulation and failure modes."""

    @pytest.mark.asyncio
    async def test_orchestrator_mock_execution(self, sample_manifest: EpisodeManifest):
        """Verifies full pipeline execution in mock/simulation mode."""
        with tempfile.TemporaryDirectory() as td:
            orchestrator = FlowKitOrchestrator(output_dir=td, mock=True)
            result = await orchestrator.run_pipeline(
                manifest=sample_manifest,
                material="realistic",
                orientation="VERTICAL",
            )

            assert result.status == "SUCCESS"
            assert result.is_mock is True
            assert len(result.scene_ids) == len(sample_manifest.scenes)
            # 1 connection, 2 registration, 2 character refs, 3 scenes, 4 stills, 5 clips, 6 narration
            assert len(result.phases_completed) == 7
            assert any("Character Reference Images" in p for p in result.phases_completed)
            assert result.assembled_video_path is not None
            assert os.path.exists(result.assembled_video_path)

    @pytest.mark.asyncio
    async def test_orchestrator_connection_failure(self, sample_manifest: EpisodeManifest):
        """Verifies graceful pipeline failure when FlowKit extension is disconnected."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"connected": False})
        )
        async with httpx.AsyncClient(transport=mock_transport, base_url="http://test") as http_c:
            client = FlowKitClient(client=http_c)
            orchestrator = FlowKitOrchestrator(client=client, mock=False)
            result = await orchestrator.run_pipeline(manifest=sample_manifest)

            assert result.status == "FAILED"
            assert any("Extension is disconnected" in e for e in result.errors)


# ==============================================================================
# 6. Standalone Payload Validation Script Tests
# ==============================================================================

class TestPayloadValidationScript:
    """Tests the automated payload validation suite."""

    def test_validate_manifest_payloads(self, sample_manifest: EpisodeManifest):
        """Verifies that all generated payloads pass the validation suite."""
        success, report = validate_manifest_payloads(
            manifest=sample_manifest,
            material="realistic",
            live_url=None,
            verbose=False,
        )
        assert success is True
        assert report["valid"] is True
        assert report["payloads_checked"] >= 20
        assert len(report["errors"]) == 0


# ==============================================================================
# 8. Character Reference Images (scene stills depend on them)
# ==============================================================================

class _FakeFlowKitClient:
    """Minimal stand-in for FlowKitClient covering the phases up to scene init.

    Used with ``skip_video_render=True`` so the pipeline stops before any ffmpeg
    or audio work — enough to observe what gets queued and in what order.
    """

    def __init__(self, characters):
        self.verify_connection = AsyncMock(return_value=True)
        self.create_project = AsyncMock(return_value={"id": "proj-001"})
        self.get_characters = AsyncMock(return_value=characters)
        self.submit_batch_requests = AsyncMock(
            side_effect=lambda reqs: [{"id": f"req-{i}"} for i in range(len(reqs))]
        )
        self.poll_batch_resilient = AsyncMock(return_value=None)
        self.create_video = AsyncMock(return_value={"id": "vid-001"})
        self.create_scene = AsyncMock(
            side_effect=lambda scene, narrator_text: {"id": f"scene-{scene.display_order}"}
        )


class TestCharacterReferenceImages:
    """Scene stills are conditioned on each named entity's reference image.

    FlowKit refuses a GENERATE_IMAGE whose scene names a character with no
    media_id ("Waiting for reference images: …"), so the orchestrator has to
    generate them before any scene still is submitted.
    """

    @pytest.mark.asyncio
    async def test_queues_reference_image_for_entity_missing_media(
        self, sample_manifest: EpisodeManifest, tmp_path
    ):
        client = _FakeFlowKitClient([
            {"id": "c1", "name": "Arthur", "slug": "arthur", "media_id": None},
            {"id": "c2", "name": "Rusty", "slug": "rusty", "media_id": "media-2"},
        ])
        orchestrator = FlowKitOrchestrator(client=client, output_dir=str(tmp_path))

        result = await orchestrator.run_pipeline(sample_manifest, skip_video_render=True)

        assert result.status == "SUCCESS"
        client.get_characters.assert_awaited_once_with(project_id="proj-001")

        submitted = client.submit_batch_requests.call_args[0][0]
        assert [r.character_id for r in submitted] == ["c1"], "Rusty already has a reference image"
        assert all(r.type == "GENERATE_CHARACTER_IMAGE" for r in submitted)
        assert any("Character Reference Images Generated" in p for p in result.phases_completed)

    @pytest.mark.asyncio
    async def test_polls_without_orientation_filter(
        self, sample_manifest: EpisodeManifest, tmp_path
    ):
        """Character requests carry no orientation — filtering by it matches nothing."""
        client = _FakeFlowKitClient([{"id": "c1", "name": "Arthur", "media_id": None}])
        orchestrator = FlowKitOrchestrator(client=client, output_dir=str(tmp_path))

        await orchestrator.run_pipeline(sample_manifest, skip_video_render=True)

        poll_kwargs = client.poll_batch_resilient.call_args[1]
        assert poll_kwargs["req_type"] == "GENERATE_CHARACTER_IMAGE"
        assert poll_kwargs["orientation"] is None
        assert poll_kwargs["project_id"] == "proj-001"
        assert poll_kwargs["expected_count"] == 1

    @pytest.mark.asyncio
    async def test_skips_when_all_references_already_exist(
        self, sample_manifest: EpisodeManifest, tmp_path
    ):
        client = _FakeFlowKitClient([
            {"id": "c1", "name": "Arthur", "media_id": "media-1"},
            {"id": "c2", "name": "Rusty", "media_id": "media-2"},
        ])
        orchestrator = FlowKitOrchestrator(client=client, output_dir=str(tmp_path))

        result = await orchestrator.run_pipeline(sample_manifest, skip_video_render=True)

        assert result.status == "SUCCESS"
        client.submit_batch_requests.assert_not_called()
        client.poll_batch_resilient.assert_not_called()
        assert any("Character References Already Present" in p for p in result.phases_completed)

    @pytest.mark.asyncio
    async def test_pipeline_fails_cleanly_when_reference_generation_fails(
        self, sample_manifest: EpisodeManifest, tmp_path
    ):
        client = _FakeFlowKitClient([{"id": "c1", "name": "Arthur", "media_id": None}])
        client.poll_batch_resilient = AsyncMock(
            side_effect=RuntimeError("Batch GENERATE_CHARACTER_IMAGE completed with 1 failure(s)")
        )
        orchestrator = FlowKitOrchestrator(client=client, output_dir=str(tmp_path))

        result = await orchestrator.run_pipeline(sample_manifest, skip_video_render=True)

        assert result.status == "FAILED"
        assert any("character references" in e for e in result.errors)
        # Scene stills must not be queued behind a failed reference image.
        client.create_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_project_with_no_entities(
        self, sample_manifest: EpisodeManifest, tmp_path
    ):
        """Environmental manifests have no characters — nothing should be queued."""
        client = _FakeFlowKitClient([])
        orchestrator = FlowKitOrchestrator(client=client, output_dir=str(tmp_path))

        result = await orchestrator.run_pipeline(sample_manifest, skip_video_render=True)

        assert result.status == "SUCCESS"
        client.submit_batch_requests.assert_not_called()
        assert any("Character References Already Present" in p for p in result.phases_completed)
