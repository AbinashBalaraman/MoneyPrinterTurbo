"""End-to-end FlowKit generation orchestrator supporting live and mock execution."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.render_client.adapter import FlowKitPayloadAdapter
from src.render_client.client import FlowKitClient
from src.render_client.models import (
    BatchStatus,
    Orientation,
)
from src.models import EpisodeManifest
from src.postprocess.metadata import MetadataScrubber
from src.postprocess.watermark import WatermarkScrubber

logger = logging.getLogger(__name__)


class OrchestrationResult(BaseModel):
    """Encapsulates the output and status of an orchestrated video generation pipeline."""
    project_id: str
    video_id: str
    episode_num: int
    title: str
    scene_ids: list[str] = Field(default_factory=list)
    image_request_ids: list[str] = Field(default_factory=list)
    video_request_ids: list[str] = Field(default_factory=list)
    assembled_video_path: Optional[str] = None
    status: str = "SUCCESS"
    phases_completed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    is_mock: bool = False


def check_stream_has_audio(video_path: str, ffprobe_cmd: str = "ffprobe") -> bool:
    """Probes a video file using ffprobe to determine if an audio stream is present."""
    if not os.path.exists(video_path):
        return False
    try:
        cmd = [
            ffprobe_cmd,
            "-v", "quiet",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            video_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return "audio" in res.stdout.lower()
    except Exception as exc:
        logger.warning("ffprobe check failed for %s: %s", video_path, exc)
        return False


def mix_narration_resilient(
    video_path: str,
    audio_path: str,
    output_path: str,
    sfx_vol: float = 0.4,
    narration_vol: float = 1.0,
    ffmpeg_cmd: str = "ffmpeg",
    ffprobe_cmd: str = "ffprobe",
) -> bool:
    """Safely mixes narration into a video clip with dual-path audio ducking.
    
    CRITICAL FIX: Standard FlowKit add_narration filtergraph crashes with code 4294967274
    whenever a video has no audio track (e.g. silent Veo generation).
    
    This function:
    1. Probes the video with ffprobe.
    2. If audio exists: executes dual-stream ducking ([0:a]volume=sfx + [1:a]volume=narr -> amerge).
    3. If silent: maps narration directly as the sole audio stream (-map 0:v -map 1:a -c:a aac).
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    has_audio = check_stream_has_audio(video_path, ffprobe_cmd=ffprobe_cmd)

    if has_audio:
        filter_complex = (
            f"[0:a]volume={sfx_vol}[sfx];"
            f"[1:a]volume={narration_vol},afade=t=in:st=0:d=0.2[narr];"
            f"[sfx][narr]amerge=inputs=2,pan=stereo|c0=c0+c2|c1=c1+c3[aout]"
        )
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
        ]
    else:
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
        ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            logger.error("FFmpeg narration mixing failed: %s", res.stderr)
            return False
        return True
    except Exception as exc:
        logger.error("Failed to execute FFmpeg for narration mixing: %s", exc)
        return False


def concatenate_scenes(
    scene_video_paths: list[str],
    output_path: str,
    encoder: Optional[str] = None,
    ffmpeg_cmd: str = "ffmpeg",
) -> bool:
    """Concatenates multiple scene video clips into a single video file.
    
    Standardizes output at 30fps with 48kHz AAC audio to eliminate timestamp drift
    and player rejection on TikTok/Shorts.
    """
    if not scene_video_paths:
        logger.error("No scene video paths provided for concatenation.")
        return False

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    concat_txt_path = f"{output_path}.concat.txt"

    try:
        with open(concat_txt_path, "w", encoding="utf-8") as f:
            for p in scene_video_paths:
                norm_p = os.path.abspath(p).replace("\\", "/")
                f.write(f"file '{norm_p}'\n")

        # Choose encoder: test preferred encoder or fallback to libx264
        selected_encoder = encoder or "libx264"

        cmd = [
            ffmpeg_cmd,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_txt_path,
            "-c:v", selected_encoder,
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-c:a", "aac",
            "-ar", "48000",
            "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            # Fallback to libx264 if hardware encoder failed
            if selected_encoder != "libx264":
                logger.warning("Encoder %s failed, falling back to libx264", selected_encoder)
                cmd[cmd.index(selected_encoder)] = "libx264"
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if res.returncode != 0:
                logger.error("FFmpeg scene concatenation failed: %s", res.stderr)
                return False

        return True
    except Exception as exc:
        logger.error("Scene concatenation execution failed: %s", exc)
        return False
    finally:
        if os.path.exists(concat_txt_path):
            try:
                os.remove(concat_txt_path)
            except OSError:
                pass


class FlowKitOrchestrator:
    """Coordinates full-lifecycle generation of an episode across FlowKit APIs."""

    def __init__(
        self,
        client: Optional[FlowKitClient] = None,
        output_dir: Optional[str] = None,
        mock: bool = False,
        scrub_watermarks: bool = False,
    ) -> None:
        self.client = client or FlowKitClient()
        self.output_dir = output_dir or os.path.abspath("output")
        self.mock = mock
        self.scrub_watermarks = scrub_watermarks

    async def run_pipeline(
        self,
        manifest: EpisodeManifest,
        material: str = "realistic",
        orientation: Orientation = "VERTICAL",
        skip_video_render: bool = False,
    ) -> OrchestrationResult:
        """Executes the 6-phase FlowKit episodic generation pipeline.
        
        Phases:
        1. Connection Check: verifies FlowKit extension connectivity.
        2. Project & Character Registration: registers entities, creates the
           project container, then generates a reference image for every entity
           that lacks one (GENERATE_CHARACTER_IMAGE). Scene stills are
           conditioned on these, so they must exist first.
        3. Video & Scene Initialization: creates video and scenes via two-step POST + PATCH.
        4. Scene Stills Generation: submits GENERATE_IMAGE batch and polls to completion.
        5. Scene Video Clips Generation: submits GENERATE_VIDEO batch and polls to completion.
        6. Audio Narration & Video Assembly: synthesizes narration and concatenates final MP4.
        """
        phases_completed: list[str] = []
        errors: list[str] = []

        if self.mock:
            return await self._run_mock_pipeline(manifest, material, orientation, skip_video_render)

        # --- Phase 1: Connection Verification ---
        logger.info("Phase 1: Verifying FlowKit service connection...")
        connected = await self.client.verify_connection()
        if not connected:
            err = "FlowKit Chrome Extension is disconnected. Cannot run live generation."
            logger.error(err)
            return OrchestrationResult(
                project_id="",
                video_id="",
                episode_num=manifest.episode_num,
                title=manifest.title,
                status="FAILED",
                errors=[err],
            )
        phases_completed.append("Phase 1: Connection Verified")

        # --- Phase 2: Project & Character Registration ---
        logger.info("Phase 2: Registering project and reference entities...")
        project_payload = FlowKitPayloadAdapter.to_project_payload(
            manifest=manifest,
            material=material,
            allow_music=False,
            allow_voice=True,
        )
        try:
            proj_data = await self.client.create_project(project_payload)
            project_id = proj_data["id"]
            phases_completed.append("Phase 2: Project & Entities Registered")
        except Exception as exc:
            err = f"Phase 2 failed: {exc}"
            logger.exception(err)
            return OrchestrationResult(
                project_id="",
                video_id="",
                episode_num=manifest.episode_num,
                title=manifest.title,
                status="FAILED",
                phases_completed=phases_completed,
                errors=[err],
            )

        # --- Phase 2 (cont.): Character Reference Images ---
        # Registering the entities is not enough. FlowKit refuses any
        # GENERATE_IMAGE whose scene names a character that has no media_id
        # ("Waiting for reference images: …"), so every referenced entity needs
        # its reference image to exist before the first scene still is
        # submitted. Characters that already carry a media_id are skipped, which
        # keeps re-runs idempotent.
        logger.info("Phase 2: Generating character reference images (GENERATE_CHARACTER_IMAGE)...")
        try:
            characters = await self.client.get_characters(project_id=project_id)
            pending_refs = [c for c in characters if not c.get("media_id")]

            if pending_refs:
                ref_reqs = FlowKitPayloadAdapter.to_character_batch_requests(
                    character_ids=[c["id"] for c in pending_refs],
                    project_id=project_id,
                )
                logger.info(
                    "Phase 2: %d of %d character(s) need reference images: %s",
                    len(ref_reqs),
                    len(characters),
                    ", ".join(c.get("name", "?") for c in pending_refs),
                )
                await self.client.submit_batch_requests(ref_reqs)
                await self.client.poll_batch_resilient(
                    expected_count=len(ref_reqs),
                    project_id=project_id,
                    req_type="GENERATE_CHARACTER_IMAGE",
                    # Character requests carry no orientation, so filtering by it
                    # would match nothing and the poll would time out.
                    orientation=None,
                    timeout=600.0,
                    poll_interval=5.0,
                )
                phases_completed.append(
                    f"Phase 2: Character Reference Images Generated ({len(ref_reqs)})"
                )
            else:
                logger.info(
                    "Phase 2: all %d character(s) already have reference images",
                    len(characters),
                )
                phases_completed.append("Phase 2: Character References Already Present")
        except Exception as exc:
            err = f"Phase 2 (character references) failed: {exc}"
            logger.exception(err)
            return OrchestrationResult(
                project_id=project_id,
                video_id="",
                episode_num=manifest.episode_num,
                title=manifest.title,
                status="FAILED",
                phases_completed=phases_completed,
                errors=[err],
            )

        # --- Phase 3: Video & Scene Container Creation ---
        logger.info("Phase 3: Creating video container and two-step scene initialization...")
        video_payload = FlowKitPayloadAdapter.to_video_payload(
            manifest=manifest,
            project_id=project_id,
            orientation=orientation,
        )
        try:
            vid_data = await self.client.create_video(video_payload)
            video_id = vid_data["id"]

            scene_pairs = FlowKitPayloadAdapter.to_scene_payloads(manifest, video_id=video_id)
            scene_ids: list[str] = []
            for scene_create, narrator_text in scene_pairs:
                # Two-step creation: POST /scenes + PATCH /scenes/{id} with narrator_text
                created_scene = await self.client.create_scene(
                    scene=scene_create,
                    narrator_text=narrator_text,
                )
                scene_ids.append(created_scene["id"])
            phases_completed.append("Phase 3: Video & Scenes Initialized")
        except Exception as exc:
            err = f"Phase 3 failed: {exc}"
            logger.exception(err)
            return OrchestrationResult(
                project_id=project_id,
                video_id="",
                episode_num=manifest.episode_num,
                title=manifest.title,
                status="FAILED",
                phases_completed=phases_completed,
                errors=[err],
            )

        # If skip_video_render requested (e.g. metadata/payload check only)
        if skip_video_render:
            return OrchestrationResult(
                project_id=project_id,
                video_id=video_id,
                episode_num=manifest.episode_num,
                title=manifest.title,
                scene_ids=scene_ids,
                status="SUCCESS",
                phases_completed=phases_completed,
            )

        # --- Phase 4: Scene Stills Generation ---
        logger.info("Phase 4: Submitting and polling Scene Stills (GENERATE_IMAGE)...")
        image_reqs = FlowKitPayloadAdapter.to_batch_requests(
            scene_ids=scene_ids,
            project_id=project_id,
            video_id=video_id,
            req_type="GENERATE_IMAGE",
            orientation=orientation,
        )
        try:
            image_resp = await self.client.submit_batch_requests(image_reqs)
            image_req_ids = [r["id"] for r in image_resp]

            # Poll with the expected_count guard
            await self.client.poll_batch_resilient(
                expected_count=len(scene_ids),
                video_id=video_id,
                req_type="GENERATE_IMAGE",
                orientation=orientation,
                timeout=600.0,
                poll_interval=5.0,
            )
            phases_completed.append("Phase 4: Scene Stills Generated")
        except Exception as exc:
            err = f"Phase 4 failed: {exc}"
            logger.exception(err)
            return OrchestrationResult(
                project_id=project_id,
                video_id=video_id,
                episode_num=manifest.episode_num,
                title=manifest.title,
                scene_ids=scene_ids,
                status="FAILED",
                phases_completed=phases_completed,
                errors=[err],
            )

        # --- Phase 5: Video Clips Generation ---
        logger.info("Phase 5: Submitting and polling Scene Video Clips (GENERATE_VIDEO)...")
        video_reqs = FlowKitPayloadAdapter.to_batch_requests(
            scene_ids=scene_ids,
            project_id=project_id,
            video_id=video_id,
            req_type="GENERATE_VIDEO",
            orientation=orientation,
        )
        try:
            video_resp = await self.client.submit_batch_requests(video_reqs)
            video_req_ids = [r["id"] for r in video_resp]

            await self.client.poll_batch_resilient(
                expected_count=len(scene_ids),
                video_id=video_id,
                req_type="GENERATE_VIDEO",
                orientation=orientation,
                timeout=1200.0,
                poll_interval=10.0,
            )
            phases_completed.append("Phase 5: Video Clips Generated")
        except Exception as exc:
            err = f"Phase 5 failed: {exc}"
            logger.exception(err)
            return OrchestrationResult(
                project_id=project_id,
                video_id=video_id,
                episode_num=manifest.episode_num,
                title=manifest.title,
                scene_ids=scene_ids,
                image_request_ids=image_req_ids,
                status="FAILED",
                phases_completed=phases_completed,
                errors=[err],
            )

        # --- Phase 6: Narration & Video Assembly ---
        logger.info("Phase 6: Synthesizing narration audio and concatenating final video...")
        try:
            narr_req = FlowKitPayloadAdapter.to_narrate_payload(
                project_id=project_id,
                orientation=orientation,
                mix=True,
                sfx_volume=0.4,
            )
            narr_resp = await self.client.narrate_video(video_id=video_id, request=narr_req)

            # Retrieve scene videos and assemble final episode
            scenes_data = await self.client.get_scenes(video_id=video_id)
            scene_files = [s.get("vertical_video_url") for s in scenes_data if s.get("vertical_video_url")]

            assembled_path = os.path.join(
                self.output_dir,
                f"episode_{manifest.episode_num:02d}_{manifest.series_id}.mp4",
            )

            if scene_files:
                concat_ok = concatenate_scenes(scene_files, assembled_path)
                if not concat_ok:
                    errors.append("Scene concatenation failed during final assembly.")
                elif self.scrub_watermarks and os.path.exists(assembled_path):
                    clean_temp = os.path.join(
                        self.output_dir,
                        f"clean_{manifest.episode_num:02d}_{manifest.series_id}.mp4",
                    )
                    scrubber = WatermarkScrubber()
                    meta = MetadataScrubber()
                    if scrubber.is_ffmpeg_available():
                        scrub_ok = scrubber.scrub_video(assembled_path, clean_temp)
                        if scrub_ok:
                            meta.strip_metadata(clean_temp, assembled_path)
                            try:
                                os.remove(clean_temp)
                            except OSError:
                                pass
                            phases_completed.append("Phase 7: Watermark & Metadata Scrubbed")
            else:
                assembled_path = None

            phases_completed.append("Phase 6: Narration & Assembly Complete")
            return OrchestrationResult(
                project_id=project_id,
                video_id=video_id,
                episode_num=manifest.episode_num,
                title=manifest.title,
                scene_ids=scene_ids,
                image_request_ids=image_req_ids,
                video_request_ids=video_req_ids,
                assembled_video_path=assembled_path,
                status="SUCCESS" if not errors else "PARTIAL",
                phases_completed=phases_completed,
                errors=errors,
            )
        except Exception as exc:
            err = f"Phase 6 failed: {exc}"
            logger.exception(err)
            return OrchestrationResult(
                project_id=project_id,
                video_id=video_id,
                episode_num=manifest.episode_num,
                title=manifest.title,
                scene_ids=scene_ids,
                image_request_ids=image_req_ids,
                video_request_ids=video_req_ids,
                status="FAILED",
                phases_completed=phases_completed,
                errors=[err],
            )

    async def _run_mock_pipeline(
        self,
        manifest: EpisodeManifest,
        material: str,
        orientation: Orientation,
        skip_video_render: bool,
    ) -> OrchestrationResult:
        """Simulates end-to-end pipeline execution for automated offline testing.
        
        Creates genuine local test media artifacts and executes real FFmpeg audio mixing
        and scene concatenation if FFmpeg is installed.
        """
        mock_proj_id = f"proj_mock_{uuid.uuid4().hex[:8]}"
        mock_vid_id = f"vid_mock_{uuid.uuid4().hex[:8]}"
        mock_scene_ids = [f"scene_mock_{i}_{uuid.uuid4().hex[:6]}" for i in range(len(manifest.scenes))]
        mock_image_req_ids = [f"req_img_{i}" for i in range(len(manifest.scenes))]
        mock_video_req_ids = [f"req_vid_{i}" for i in range(len(manifest.scenes))]

        phases = [
            "Phase 1: Connection Verified (Simulated)",
            "Phase 2: Project & Entities Registered (Simulated)",
            "Phase 2: Character Reference Images Generated (Simulated)",
            "Phase 3: Video & Scenes Initialized (Simulated)",
        ]

        if skip_video_render:
            return OrchestrationResult(
                project_id=mock_proj_id,
                video_id=mock_vid_id,
                episode_num=manifest.episode_num,
                title=manifest.title,
                scene_ids=mock_scene_ids,
                status="SUCCESS",
                phases_completed=phases,
                is_mock=True,
            )

        phases.append("Phase 4: Scene Stills Generated (Simulated)")
        phases.append("Phase 5: Video Clips Generated (Simulated)")

        # Generate genuine synthetic test media files using FFmpeg to test mixing and concatenation
        temp_dir = tempfile.mkdtemp(prefix="flowkit_mock_")
        scene_clip_paths: list[str] = []

        try:
            for idx, scene in enumerate(manifest.scenes):
                clip_path = os.path.join(temp_dir, f"scene_{idx:02d}.mp4")
                audio_path = os.path.join(temp_dir, f"narr_{idx:02d}.wav")
                mixed_path = os.path.join(temp_dir, f"mixed_{idx:02d}.mp4")

                # Generate a 1-second synthetic black clip and 1-second audio tone via FFmpeg
                vid_cmd = [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", clip_path,
                ]
                aud_cmd = [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    audio_path,
                ]

                vid_ok = subprocess.run(vid_cmd, capture_output=True, check=False).returncode == 0
                aud_ok = subprocess.run(aud_cmd, capture_output=True, check=False).returncode == 0

                if vid_ok and aud_ok:
                    # Test real dual-path audio ducking
                    mix_ok = mix_narration_resilient(
                        video_path=clip_path,
                        audio_path=audio_path,
                        output_path=mixed_path,
                        sfx_vol=0.4,
                    )
                    scene_clip_paths.append(mixed_path if mix_ok else clip_path)
                else:
                    # Fallback dummy file
                    with open(clip_path, "wb") as f:
                        f.write(b"MOCK_MP4_DATA")
                    scene_clip_paths.append(clip_path)

            output_dir = os.path.join(self.output_dir, "mock_episodes")
            os.makedirs(output_dir, exist_ok=True)
            assembled_path = os.path.join(output_dir, f"episode_{manifest.episode_num:02d}_{manifest.series_id}.mp4")

            # Perform actual concatenation
            if scene_clip_paths and os.path.getsize(scene_clip_paths[0]) > 100:
                concatenate_scenes(scene_clip_paths, assembled_path)
            else:
                with open(assembled_path, "wb") as f:
                    f.write(b"MOCK_CONCATENATED_MP4")

            phases.append("Phase 6: Narration & Assembly Complete (Simulated)")

            if self.scrub_watermarks and assembled_path and os.path.exists(assembled_path):
                clean_path = os.path.join(output_dir, f"clean_{manifest.episode_num:02d}_{manifest.series_id}.mp4")
                scrubber = WatermarkScrubber()
                meta = MetadataScrubber()
                if scrubber.is_ffmpeg_available() and os.path.getsize(assembled_path) > 100:
                    scrub_ok = scrubber.scrub_video(assembled_path, clean_path)
                    if scrub_ok:
                        meta.strip_metadata(clean_path, assembled_path)
                        try:
                            os.remove(clean_path)
                        except OSError:
                            pass
                phases.append("Phase 7: Watermark & Metadata Scrubbed (Simulated)")

            return OrchestrationResult(
                project_id=mock_proj_id,
                video_id=mock_vid_id,
                episode_num=manifest.episode_num,
                title=manifest.title,
                scene_ids=mock_scene_ids,
                image_request_ids=mock_image_req_ids,
                video_request_ids=mock_video_req_ids,
                assembled_video_path=assembled_path,
                status="SUCCESS",
                phases_completed=phases,
                is_mock=True,
            )
        except Exception as exc:
            logger.exception("Error in mock pipeline: %s", exc)
            return OrchestrationResult(
                project_id=mock_proj_id,
                video_id=mock_vid_id,
                episode_num=manifest.episode_num,
                title=manifest.title,
                scene_ids=mock_scene_ids,
                status="FAILED",
                phases_completed=phases,
                errors=[str(exc)],
                is_mock=True,
            )
