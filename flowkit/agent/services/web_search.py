"""TinyFish Search — web search for the agent.

Endpoint: ``GET https://api.search.tinyfish.ai``
Auth:     ``X-API-Key`` header (``TINYFISH_API_KEY``)

Search is free at any balance, including $0, so it is safe to call liberally.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent.config import TINYFISH_API_KEY, TINYFISH_SEARCH_URL

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 8
TIMEOUT_SECONDS = 20.0


def configured() -> bool:
    return bool(TINYFISH_API_KEY)


def normalise(payload: dict[str, Any], max_results: int) -> dict[str, Any]:
    """Reduce the upstream payload to the fields the chat actually shows."""
    raw = payload.get("results") or []
    results = []
    for item in raw[:max_results]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "position": item.get("position"),
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("snippet") or "",
                "site_name": item.get("site_name") or "",
            }
        )
    return {
        "query": payload.get("query", ""),
        "total_results": payload.get("total_results", len(results)),
        "results": results,
    }


async def search(
    query: str,
    *,
    purpose: str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    domain_type: str = "web",
    recency_minutes: int | None = None,
    location: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Run a web search. Returns ``{"query", "total_results", "results"}`` or ``{"error": …}``."""
    query = (query or "").strip()
    if not query:
        return {"error": "Empty search query."}

    if not TINYFISH_API_KEY:
        return {
            "error": (
                "TINYFISH_API_KEY is not set. Add it to AutoShorts/.env "
                "(get a key at https://agent.tinyfish.ai/api-keys) and restart the agent."
            )
        }

    params: dict[str, Any] = {"query": query}
    if domain_type and domain_type != "web":
        params["domain_type"] = domain_type
    if recency_minutes is not None:
        params["recency_minutes"] = int(recency_minutes)
    if location:
        params["location"] = location
    if language:
        params["language"] = language
    if purpose:
        # Max 2000 chars upstream — trim rather than let the API reject it.
        params["purpose"] = purpose[:2000]

    try:
        # NOTE: unlike the localhost calls in this codebase, this one deliberately
        # honours proxy env vars — outbound HTTPS here needs the corporate proxy.
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                TINYFISH_SEARCH_URL,
                params=params,
                headers={"X-API-Key": TINYFISH_API_KEY, "Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        logger.warning("TinyFish search failed: %s", exc)
        return {"error": f"Search request failed: {exc}"}

    if resp.status_code >= 400:
        detail = resp.text[:300]
        logger.warning("TinyFish search HTTP %s: %s", resp.status_code, detail)
        return {"error": f"Search API returned HTTP {resp.status_code}: {detail}"}

    try:
        payload = resp.json()
    except ValueError:
        return {"error": "Search API returned a non-JSON response."}

    return normalise(payload, max_results)
