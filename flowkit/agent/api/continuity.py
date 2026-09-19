"""FlowKit Continuity Ledger API Bridge.
Connects FlowKit Dashboard to shorts_content_engine's SQLite WAL continuity database.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/continuity", tags=["continuity"])

# One definition, shared with the operations that *write* the ledger. A second
# opinion here is what split the data across two files — see
# agent/services/ledger.py.
from agent.services.ledger import LEDGER_PATH

DB_PATH = LEDGER_PATH


def _get_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        # Fallback search
        candidate = Path("C:/Users/SATHYA TRADERS/Documents/Abi/Projects/shorts_content_engine/continuity_ledger.db")
        if candidate.exists():
            conn = sqlite3.connect(str(candidate))
            conn.row_factory = sqlite3.Row
            return conn
        raise HTTPException(status_code=404, detail=f"Continuity database not found at {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/ledger")
async def get_ledger_state() -> Dict[str, Any]:
    """Returns complete episodic continuity state: series, characters, and recorded episodes."""
    conn = _get_db()
    try:
        # 1. Series
        s_cursor = conn.execute("SELECT * FROM series ORDER BY rowid DESC LIMIT 10;")
        series_list = []
        for r in s_cursor.fetchall():
            d = dict(r)
            try:
                d["unresolved_threads"] = json.loads(d.get("unresolved_threads") or "[]")
            except Exception:
                d["unresolved_threads"] = []
            series_list.append(d)

        # 2. Characters
        c_cursor = conn.execute("SELECT * FROM characters ORDER BY id ASC;")
        char_list = []
        for r in c_cursor.fetchall():
            d = dict(r)
            try:
                d["relationships"] = json.loads(d.get("relationships") or "{}")
            except Exception:
                d["relationships"] = {}
            try:
                d["tags"] = json.loads(d.get("tags") or "[]")
            except Exception:
                d["tags"] = []
            char_list.append(d)

        # 3. Episodes
        e_cursor = conn.execute(
            "SELECT id, series_id, episode_num, season_num, title, premise, target_duration, "
            "cliffhanger, next_episode_hook, micro_loop, loop_phrase, status, created_at, manifest_json "
            "FROM episodes ORDER BY episode_num ASC;"
        )
        ep_list = []
        for r in e_cursor.fetchall():
            d = dict(r)
            if d.get("manifest_json"):
                try:
                    d["manifest"] = json.loads(d["manifest_json"])
                except Exception:
                    d["manifest"] = None
                del d["manifest_json"]
            ep_list.append(d)

        return {
            "connected": True,
            "db_path": str(DB_PATH),
            "series": series_list,
            "characters": char_list,
            "episodes": ep_list,
            "total_episodes": len(ep_list),
            "latest_episode": ep_list[-1] if ep_list else None,
        }
    finally:
        conn.close()


@router.get("/episodes")
async def get_episodes() -> List[Dict[str, Any]]:
    """Returns list of all canon episodes with cliffhangers and pacing metadata."""
    res = await get_ledger_state()
    return res.get("episodes", [])
