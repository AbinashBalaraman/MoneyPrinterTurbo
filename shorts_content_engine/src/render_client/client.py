"""Asynchronous HTTP client for the local FlowKit API service (http://127.0.0.1:8100/api)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional, Union

import httpx

from src.render_client.models import (
    BatchStatus,
    FlowKitCharacterCreate,
    FlowKitNarrateVideoRequest,
    FlowKitProjectCreate,
    FlowKitRequestCreate,
    FlowKitSceneCreate,
    FlowKitSceneUpdate,
    FlowKitVideoCreate,
    NarrateVideoResponse,
)

logger = logging.getLogger(__name__)


class FlowKitClient:
    """High-performance asynchronous client for communicating with FlowKit."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8100/api",
        timeout: float = 60.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._external_client = client is not None
        self.client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def __aenter__(self) -> "FlowKitClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Closes the underlying HTTP client session if owned."""
        if not self._external_client and not self.client.is_closed:
            await self.client.aclose()

    def _serialize(self, data: Any) -> dict[str, Any]:
        """Helper to serialize Pydantic model or dict to JSON-compatible dict."""
        if hasattr(data, "model_dump"):
            return data.model_dump(exclude_none=True)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        raise TypeError(f"Cannot serialize object of type {type(data)}")

    # --- System & Connection Endpoints ---

    async def get_status(self) -> dict[str, Any]:
        """Fetches FlowKit extension connection status (GET /api/flow/status)."""
        resp = await self.client.get("/flow/status")
        resp.raise_for_status()
        return resp.json()

    async def verify_connection(self) -> bool:
        """Verifies if the FlowKit Chrome Extension is connected and ready."""
        try:
            status = await self.get_status()
            return bool(status.get("connected", False))
        except Exception as exc:
            logger.warning("FlowKit connection verification failed: %s", exc)
            return False

    async def get_materials(self) -> list[dict[str, Any]]:
        """Retrieves registered aesthetic materials from FlowKit (GET /api/materials)."""
        resp = await self.client.get("/materials")
        resp.raise_for_status()
        return resp.json()

    async def get_models(self) -> dict[str, Any]:
        """Retrieves registered image/video models from FlowKit (GET /api/models)."""
        resp = await self.client.get("/models")
        resp.raise_for_status()
        return resp.json()

    # --- Project Endpoints ---

    async def create_project(
        self,
        project: Union[FlowKitProjectCreate, dict[str, Any]],
    ) -> dict[str, Any]:
        """Creates a project container with character entities (POST /api/projects)."""
        payload = self._serialize(project)
        resp = await self.client.post("/projects", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_project(self, project_id: str) -> dict[str, Any]:
        """Retrieves project details by ID (GET /api/projects/{id})."""
        resp = await self.client.get(f"/projects/{project_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_output_dir(self, project_id: str) -> dict[str, Any]:
        """Retrieves local output directory path for a project (GET /api/projects/{id}/output-dir)."""
        resp = await self.client.get(f"/projects/{project_id}/output-dir")
        resp.raise_for_status()
        return resp.json()

    # --- Character / Entity Endpoints ---

    async def register_character(
        self,
        character: Union[FlowKitCharacterCreate, dict[str, Any]],
    ) -> dict[str, Any]:
        """Registers a reference character or location entity (POST /api/characters)."""
        payload = self._serialize(character)
        resp = await self.client.post("/characters", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def link_character(self, project_id: str, character_id: str) -> bool:
        """Links an existing character to a project (POST /api/projects/{id}/characters/{cid})."""
        resp = await self.client.post(f"/projects/{project_id}/characters/{character_id}")
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get("ok", True))

    async def get_characters(self, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Lists characters, optionally filtered by project (GET /api/characters)."""
        params = {"project_id": project_id} if project_id else None
        resp = await self.client.get("/characters", params=params)
        resp.raise_for_status()
        return resp.json()

    async def update_character(self, character_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Patches a character entity, e.g. {"media_id": ...} (PATCH /api/characters/{id})."""
        resp = await self.client.patch(f"/characters/{character_id}", json=updates)
        resp.raise_for_status()
        return resp.json()

    async def upload_image(
        self, file_path: str, project_id: str, file_name: Optional[str] = None
    ) -> dict[str, Any]:
        """Uploads a server-local image into Google Flow (POST /api/flow/upload-image).

        Returns {"media_id": ..., "raw": ...}. The FlowKit server reads the file
        itself, so file_path must be absolute on the server machine.
        """
        import os

        payload = {
            "file_path": file_path,
            "project_id": project_id,
            "file_name": file_name or os.path.basename(file_path),
        }
        resp = await self.client.post("/flow/upload-image", json=payload)
        resp.raise_for_status()
        return resp.json()

    # --- Video Endpoints ---

    async def create_video(
        self,
        video: Union[FlowKitVideoCreate, dict[str, Any]],
    ) -> dict[str, Any]:
        """Creates a video container under a project (POST /api/videos)."""
        payload = self._serialize(video)
        resp = await self.client.post("/videos", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_video(self, video_id: str) -> dict[str, Any]:
        """Retrieves video container details (GET /api/videos/{id})."""
        resp = await self.client.get(f"/videos/{video_id}")
        resp.raise_for_status()
        return resp.json()

    # --- Scene Endpoints (Two-Step Creation) ---

    async def create_scene(
        self,
        scene: Union[FlowKitSceneCreate, dict[str, Any]],
        narrator_text: Optional[str] = None,
    ) -> dict[str, Any]:
        """Creates a scene and ensures narrator_text is updated via two-step POST + PATCH.
        
        CRITICAL: FlowKit's SceneCreate schema omits narrator_text. If narrator_text
        is supplied directly or via the parameter, this method performs:
        1. POST /api/scenes (creating the scene)
        2. PATCH /api/scenes/{id} with {"narrator_text": ...} (preserving voiceover)
        """
        payload = self._serialize(scene)
        
        # Extract narrator_text if supplied in dictionary
        extracted_text = narrator_text or payload.pop("narrator_text", None)

        # Step 1: POST /api/scenes
        resp = await self.client.post("/scenes", json=payload)
        resp.raise_for_status()
        scene_data = resp.json()
        scene_id = scene_data.get("id")

        # Step 2: PATCH /api/scenes/{id} if narrator_text is present
        if extracted_text and scene_id:
            patch_payload = {"narrator_text": extracted_text}
            patch_resp = await self.client.patch(f"/scenes/{scene_id}", json=patch_payload)
            patch_resp.raise_for_status()
            scene_data = patch_resp.json()

        return scene_data

    async def update_scene(
        self,
        scene_id: str,
        update: Union[FlowKitSceneUpdate, dict[str, Any]],
    ) -> dict[str, Any]:
        """Updates scene properties (PATCH /api/scenes/{id})."""
        payload = self._serialize(update)
        resp = await self.client.patch(f"/scenes/{scene_id}", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_scenes(self, video_id: str) -> list[dict[str, Any]]:
        """Retrieves all scenes for a video container (GET /api/scenes?video_id={id})."""
        resp = await self.client.get("/scenes", params={"video_id": video_id})
        resp.raise_for_status()
        return resp.json()

    # --- Job Request & Batch Polling Endpoints ---

    async def submit_request(
        self,
        request: Union[FlowKitRequestCreate, dict[str, Any]],
    ) -> dict[str, Any]:
        """Submits a single generation job (POST /api/requests)."""
        payload = self._serialize(request)
        resp = await self.client.post("/requests", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def submit_batch_requests(
        self,
        requests: list[Union[FlowKitRequestCreate, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Submits a batch of generation requests idempotently (POST /api/requests/batch)."""
        payload = {"requests": [self._serialize(r) for r in requests]}
        resp = await self.client.post("/requests/batch", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_batch_status(
        self,
        video_id: Optional[str] = None,
        project_id: Optional[str] = None,
        req_type: Optional[str] = None,
        orientation: Optional[str] = "VERTICAL",
    ) -> BatchStatus:
        """Queries batch progress metrics (GET /api/requests/batch-status)."""
        params: dict[str, Any] = {}
        if video_id:
            params["video_id"] = video_id
        if project_id:
            params["project_id"] = project_id
        if req_type:
            params["type"] = req_type
        if orientation:
            params["orientation"] = orientation

        resp = await self.client.get("/requests/batch-status", params=params)
        resp.raise_for_status()
        return BatchStatus.model_validate(resp.json())

    async def poll_batch_resilient(
        self,
        expected_count: int,
        video_id: Optional[str] = None,
        project_id: Optional[str] = None,
        req_type: Optional[str] = None,
        orientation: Optional[str] = "VERTICAL",
        timeout: float = 600.0,
        poll_interval: float = 2.0,
        raise_on_failure: bool = True,
    ) -> BatchStatus:
        """Polls batch status guarding against the empty query trap (total=0, done=True).
        
        FlowKit's backend calculates `done = (pending == 0 and processing == 0)`.
        If the query is made before requests are committed or indexed, total is 0,
        causing done to be True prematurely!
        
        This method strictly asserts `status.total >= expected_count` before evaluating `done`.
        """
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            status = await self.get_batch_status(
                video_id=video_id,
                project_id=project_id,
                req_type=req_type,
                orientation=orientation,
            )

            # Polling Guard: If DB has not indexed all expected items yet, wait
            if status.total < expected_count:
                logger.debug(
                    "Batch %s: total %d < expected %d, waiting for indexing...",
                    req_type,
                    status.total,
                    expected_count,
                )
                await asyncio.sleep(poll_interval)
                continue

            # Check if all processing has finished
            if status.done:
                if status.all_succeeded:
                    logger.info("Batch %s completed successfully (%d/%d)", req_type, status.completed, status.total)
                    return status

                if status.failed > 0:
                    err_msg = (
                        f"Batch {req_type} completed with {status.failed} failure(s) out of {status.total} requests."
                    )
                    logger.error(err_msg)
                    if raise_on_failure:
                        raise RuntimeError(err_msg)
                    return status

            await asyncio.sleep(poll_interval)

        raise TimeoutError(
            f"Batch {req_type} timed out after {timeout}s (completed {status.completed}/{expected_count})"
        )

    # --- Narration & Post-Processing ---

    async def narrate_video(
        self,
        video_id: str,
        request: Union[FlowKitNarrateVideoRequest, dict[str, Any]],
    ) -> NarrateVideoResponse:
        """Triggers OmniVoice TTS synthesis and audio mixing (POST /api/videos/{id}/narrate)."""
        payload = self._serialize(request)
        resp = await self.client.post(f"/videos/{video_id}/narrate", json=payload)
        resp.raise_for_status()
        return NarrateVideoResponse.model_validate(resp.json())
