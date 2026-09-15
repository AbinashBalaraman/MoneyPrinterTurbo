"""Publish outcomes reported by ``shorts_content_engine``.

The dashboard cannot publish: that work belongs to the directing engine, which
is headless by design. So it reports each platform outcome here and the
dashboard renders it from a single backend.

The one rule this module exists to enforce: **a simulated upload is never a
publication.** The original defect was a dry run being recorded as a real post,
which made an empty pipeline look like it had shipped. ``is_mock`` is therefore
a first-class field, ``status='published'`` requires a platform ``post_id``, and
a simulated result may not carry a URL.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

#: ``requested`` — a retry was queued; nothing attempted yet.
#: ``published`` — a real platform accepted the upload.
#: ``dry_run``   — simulated; nothing was posted.
#: ``failed``    — attempted and rejected.
PublicationStatus = Literal["requested", "published", "dry_run", "failed"]


class PublicationCreate(BaseModel):
    """One platform outcome, as reported by the directing engine."""

    platform: str
    status: PublicationStatus = "published"
    post_id: Optional[str] = None
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    is_mock: bool = False
    metadata: Optional[dict] = None
    published_at: Optional[str] = None

    @model_validator(mode="after")
    def _validate_honesty(self) -> "PublicationCreate":
        self.platform = self.platform.strip().lower()
        if not self.platform:
            raise ValueError("platform is required")

        if self.is_mock:
            # Mirrors the CHECK constraint on the publication table. Catching it
            # here turns a 500 from SQLite into a 422 that names the problem.
            if self.status != "dry_run":
                raise ValueError("a simulated upload (is_mock) must have status 'dry_run'")
            if self.video_url or self.post_id:
                raise ValueError("a simulated upload (is_mock) cannot carry a url or post_id")

        if self.status == "published" and not self.post_id:
            # A 200 with no platform id is a failure, not a publication.
            raise ValueError("status 'published' requires the platform's post_id")

        if self.status == "failed" and not self.error_message:
            raise ValueError("status 'failed' requires an error_message")

        return self


class Publication(BaseModel):
    """A stored publish outcome."""

    id: str
    video_id: str
    project_id: Optional[str] = None
    platform: str
    status: PublicationStatus
    post_id: Optional[str] = None
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    is_mock: bool = False
    metadata: dict = Field(default_factory=dict)
    published_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def is_live(self) -> bool:
        """True only when a real platform acknowledged the upload."""
        return self.status == "published" and not self.is_mock


class PublicationSummary(BaseModel):
    """Counts the publish panel renders.

    Computed server-side so the definition of "live" lives in exactly one place
    rather than being re-derived — and possibly mis-derived — in the UI.
    """

    total: int = 0
    live: int = 0
    dry_run: int = 0
    failed: int = 0
    requested: int = 0
    #: True when something succeeded but none of it was real, i.e. nothing posted.
    is_dry_run: bool = False
    #: True when no platform has ever been attempted for this video.
    is_unpublished: bool = True

    @classmethod
    def from_rows(cls, rows: list[dict]) -> "PublicationSummary":
        """Aggregate stored rows.

        A row counts as ``live`` only when the status says published *and* it is
        not a simulation. Deriving the counts here rather than in the UI keeps
        that rule in one place, so the panel cannot drift from it.
        """
        live = sum(1 for r in rows if r.get("status") == "published" and not r.get("is_mock"))
        dry = sum(1 for r in rows if r.get("status") == "dry_run")
        failed = sum(1 for r in rows if r.get("status") == "failed")
        requested = sum(1 for r in rows if r.get("status") == "requested")
        return cls(
            total=len(rows),
            live=live,
            dry_run=dry,
            failed=failed,
            requested=requested,
            is_dry_run=(live + dry) > 0 and live == 0,
            is_unpublished=live == 0 and dry == 0 and requested == 0,
        )


class PublicationListResponse(BaseModel):
    video_id: str
    publications: list[Publication] = Field(default_factory=list)
    summary: PublicationSummary = Field(default_factory=PublicationSummary)


class RetryRequest(BaseModel):
    """Ask for one or more platforms to be re-attempted."""

    platforms: Optional[list[str]] = None
    #: Why the retry was requested, surfaced in the UI.
    reason: Optional[str] = None
