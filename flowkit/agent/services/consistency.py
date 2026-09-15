"""Standing report on reference conditioning: what was actually conditioned.

The warn-and-continue decision
------------------------------
Abi chose **warn** (2026-09-14) over hard-fail: a scene naming characters that
no linked entity matches still generates. That is the right call for renamed or
removed entities, but it has a sharp edge — the still comes out plausible, the
scene reports ``COMPLETED``, and the character is simply not the same one as
last episode. ``operations.py`` logs an ``ERROR`` at generation time, which only
helps if someone is watching the log stream at that moment.

Why this report does not simply check the project links
------------------------------------------------------
The obvious implementation — "flag scenes whose declared names are not linked" —
answers a *different* question than the one that matters, and lies in the case
that matters most:

    An image generated while the characters were unlinked is un-conditioned
    **forever**. Linking the characters afterwards does not retroactively
    condition it. A link-based check would go green and the inconsistency would
    stay.

So the truth is recorded at generation time, in ``scene.conditioned_with``
(see ``sdk/services/result_handler.py``), and this report reads it back. That
gives three genuinely different states:

===========================  ==========================================
``conditioned_with``         meaning
===========================  ==========================================
``["arthur","rusty"]``       conditioned on exactly these — fine
``[]``                       generated with NO conditioning — proven bad
``NULL``                     unknown; the image predates the column
===========================  ==========================================

``NULL`` is reported as ``unverified`` rather than guessed at either way.
Deliberately no backfill: inventing a value would destroy the only honest signal
we have.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.utils.entity_match import declared_names, resolve_matched

logger = logging.getLogger(__name__)


def _recorded(scene: dict) -> list[str] | None:
    """Parse ``scene.conditioned_with``.

    ``None`` means unknown (NULL column or unparseable); ``[]`` means the image
    is known to be un-conditioned. The distinction is the whole point.
    """
    raw = scene.get("conditioned_with")
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(n) for n in raw]
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, list):
        return [str(n) for n in parsed]
    return None


def _image_done(scene: dict) -> bool:
    return scene.get("vertical_image_status") == "COMPLETED"


async def unconditioned_scenes(project_id: str | None = None) -> dict[str, Any]:
    """Report reference-conditioning problems for a project.

    Returns three distinct lists, because they need different responses:

    * ``unlinked``     — declared names nothing links to. The *next* generation
      will be un-conditioned. Fix by linking, before regenerating.
    * ``unconditioned``— proven: the image completed and recorded no
      conditioning. Must be regenerated after linking.
    * ``unverified``   — the image completed before conditioning was recorded,
      so it cannot be checked either way. Regenerate to make it checkable.
    """
    from agent.db import crud

    pid = (project_id or "").strip()
    project = await crud.get_project(pid) if pid else None

    if project is None:
        projects = await crud.list_projects()
        if not projects:
            return _empty(None, "No projects exist yet.")
        project = projects[0]

    linked = await crud.get_project_characters(project["id"])
    videos = await crud.list_videos(project_id=project["id"])

    checked = 0
    unlinked: list[dict[str, Any]] = []
    unconditioned: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []

    for video in videos:
        for scene in await crud.list_scenes(video_id=video["id"]):
            declared = declared_names(scene)
            if not declared:
                # Names nobody: no reference image was ever needed.
                continue
            checked += 1

            matched, unmatched = resolve_matched(declared, linked)
            entry = {
                "scene_id": scene.get("id"),
                "display_order": scene.get("display_order"),
                "video_title": video.get("title"),
                "image_status": scene.get("vertical_image_status"),
            }

            if unmatched:
                unlinked.append({**entry, "unlinked_names": sorted(unmatched)})

            recorded = _recorded(scene)
            if not _image_done(scene):
                # Nothing generated yet, so there is nothing to be wrong about.
                continue

            if recorded is None:
                unverified.append(entry)
            elif not recorded:
                unconditioned.append({**entry, "declared_names": sorted(declared)})

    return {
        "project": {"id": project["id"], "name": project.get("name")},
        "scenes_checked": checked,
        "unlinked": unlinked,
        "unconditioned": unconditioned,
        "unverified": unverified,
        # `unverified` is a gap in *evidence*, not a known problem: those images
        # simply predate the conditioning record. Counting it here would make
        # every project created before this column look broken — a report that
        # cries wolf gets ignored, which is worse than no report. It is surfaced
        # separately and quietly instead.
        "clean": not (unlinked or unconditioned),
        "note": (
            "unlinked = the next generation will be un-conditioned (link the "
            "entity first). unconditioned = the existing image is proven "
            "un-conditioned and must be regenerated after linking. unverified = "
            "the image predates conditioning records, so it can be neither "
            "confirmed nor denied; regenerate to make it checkable. Note that "
            "linking an entity does not retroactively fix an existing image."
        ),
    }


def _empty(project: Any, note: str) -> dict[str, Any]:
    return {
        "project": project,
        "scenes_checked": 0,
        "unlinked": [],
        "unconditioned": [],
        "unverified": [],
        "clean": True,
        "note": note,
    }
