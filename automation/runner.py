"""AutoShorts runner -- the reactive, deduplicated generation loop.

Flow::

    source.fetch()  ->  ledger filter  ->  claim  ->  cli.py --batch-file
                                                    ->  parse summary
                                                    ->  record outcomes

Design notes that matter for unattended operation:

* **The ledger is the gate, not the source.** A feed can return the same item
  every poll; the ledger decides what is genuinely new.
* **Claim before generating.** Topics are marked ``claimed`` before the batch is
  handed over, so a crash mid-run cannot cause a duplicate submission.
* **Publishing is config-driven.** MoneyPrinterTurbo cross-posts from
  ``upload_post_*`` config whenever it is enabled, so ``--dry-run`` forces those
  switches off in the child process environment rather than trusting the caller
  to have remembered.
* **Exit codes are honest.** 0 = all good, 1 = at least one task failed,
  2 = the run could not start (bad config, empty source, etc.).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Allow both `python -m automation.runner` and `python automation/runner.py`.
# Running the file directly puts automation/ (not the repo root) on sys.path,
# which would break the absolute `automation.*` imports below.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from automation.ledger import Ledger
from automation.sources import Source, build_from_settings
from automation.sources.base import Topic

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
EXIT_OK = 0
EXIT_TASK_FAILED = 1
EXIT_SETUP_FAILED = 2


# --------------------------------------------------------------------- helpers


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _new_run_id() -> str:
    import uuid

    return f"{_now_stamp()}-{uuid.uuid4().hex[:8]}"


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _load_dotenv_early() -> None:
    """Load ``.env`` before argument parsing.

    The parser derives its defaults from ``AUTOSHORTS_*`` environment variables,
    but ``.env`` is otherwise only loaded as a side effect of importing
    ``app.config`` -- which happens later in ``run()``. Without this, every
    value in ``.env`` is invisible to the CLI defaults, and the runner silently
    falls back to built-in defaults instead.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = os.path.join(REPO_ROOT, ".env")
    if os.path.isfile(path):
        load_dotenv(path, override=True)


def _describe_publish_mode() -> Tuple[str, bool]:
    """Return (human description, whether publishing is currently live).

    Imported lazily so the runner can still print usage when the app package is
    broken.
    """
    from app.config import config

    enabled = bool(config.app.get("upload_post_enabled", False))
    auto = bool(config.app.get("upload_post_auto_upload", False))
    api_key = str(config.app.get("upload_post_api_key", "") or "").strip()
    username = str(config.app.get("upload_post_username", "") or "").strip()
    platforms = list(config.app.get("upload_post_platforms", []) or [])

    if not (enabled and auto):
        return "OFF - videos will be generated but not published", False
    if not (api_key and username):
        return "MISCONFIGURED - upload enabled but credentials missing", False
    if not platforms:
        return "MISCONFIGURED - upload enabled but no platforms configured", False
    return f"LIVE - will publish to {', '.join(platforms)}", True


def _load_params_template(path: Optional[str]) -> Dict[str, Any]:
    """Load default VideoParams overrides applied to every manifest entry.

    Fields are validated against ``VideoParams`` here rather than left to
    ``cli.py``. cli.py rejects unknown fields per task, which means a typo in the
    template would fail on task 1 of N *after* the ledger has already claimed
    every topic in the batch.
    """
    if not path:
        return {}
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        raise ValueError(f"params template not found: {path}")
    with open(expanded, "r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("params template must be a JSON object of VideoParams fields")
    if "video_subject" in payload:
        raise ValueError(
            "params template must not set video_subject; it comes from the topic"
        )

    from app.models.schema import VideoParams

    unknown = sorted(set(payload) - set(VideoParams.model_fields))
    if unknown:
        raise ValueError(
            "params template contains fields that are not VideoParams fields: "
            f"{', '.join(unknown)}"
        )
    return payload


def _parse_summary(stdout: str) -> Optional[Dict[str, Any]]:
    """Extract the batch summary JSON from CLI stdout.

    Tolerates incidental output before the summary by scanning from the end.
    """
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "tasks" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "tasks" in parsed:
            return parsed
    return None


def _attach_flowkit_materials(
    entries: List[Dict[str, Any]], project_ref: str, media: str, run_id: str
) -> int:
    """Stage a FlowKit project's completed media once and attach to entries.

    One staging run serves the whole batch: the media belongs to the episode,
    not to any single topic. Returns the staged material count. Any failure
    raises — entries without materials would render the wrong video.
    """
    from automation.flowkit_bridge import (
        FlowkitError,
        ProjectScrubber,
        apply_to_params,
        stage_flowkit_project,
    )

    scrubber = ProjectScrubber()
    if not scrubber.available():
        raise ValueError("ffmpeg was not found on PATH; the project scrubber needs it")
    try:
        staged, _narration = stage_flowkit_project(
            project_ref, f"run-{run_id}", scrubber=scrubber, media=media
        )
    except FlowkitError as exc:
        raise ValueError(f"flowkit staging failed: {exc}") from exc
    for entry in entries:
        apply_to_params(entry, staged, entry.get("video_clip_duration", 5))
    return len(staged)


def _write_manifest(entries: List[Dict[str, Any]], run_id: str) -> str:
    manifest_dir = os.path.join(REPO_ROOT, "storage", "automation", "manifests")
    os.makedirs(manifest_dir, exist_ok=True)
    path = os.path.join(manifest_dir, f"{run_id}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)
    return path


# ------------------------------------------------------------------ arg parsing


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="automation.runner",
        description="Fetch topics from a source, generate videos, and publish.",
    )
    parser.add_argument(
        "--source",
        dest="source_type",
        default=_env("AUTOSHORTS_SOURCE_TYPE"),
        help="Source type: rss or topics_file (default: $AUTOSHORTS_SOURCE_TYPE)",
    )
    parser.add_argument(
        "--url",
        dest="source_url",
        default=_env("AUTOSHORTS_SOURCE_URL"),
        help="Feed URL for --source rss (default: $AUTOSHORTS_SOURCE_URL)",
    )
    parser.add_argument(
        "--path",
        dest="source_path",
        default=_env("AUTOSHORTS_SOURCE_PATH"),
        help="File path for --source topics_file (default: $AUTOSHORTS_SOURCE_PATH)",
    )
    parser.add_argument(
        "--source-name",
        default=_env("AUTOSHORTS_SOURCE_NAME"),
        help="Override the source name used in dedupe keys",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(_env("AUTOSHORTS_LIMIT", "1")),
        help="Maximum videos to generate this run (default: 1)",
    )
    parser.add_argument(
        "--fetch-limit",
        type=int,
        default=int(_env("AUTOSHORTS_FETCH_LIMIT", "50")),
        help="Maximum topics to pull from the source before filtering (default: 50)",
    )
    parser.add_argument(
        "--stop-at",
        default=_env("AUTOSHORTS_STOP_AT", "video"),
        choices=["script", "terms", "audio", "subtitle", "materials", "video"],
        help="Pipeline stage to stop at (default: video, i.e. full render)",
    )
    parser.add_argument(
        "--params-template",
        default=_env("AUTOSHORTS_PARAMS_TEMPLATE"),
        help="JSON file of VideoParams defaults applied to every entry",
    )
    parser.add_argument(
        "--dry-run",
        # BooleanOptionalAction (not store_true) so the .env default of "true"
        # can be switched back off with --no-dry-run. A store_true flag can only
        # ever turn the setting on, which would make a safe default unescapable.
        action=argparse.BooleanOptionalAction,
        default=_env("AUTOSHORTS_DRY_RUN", "").lower() in {"1", "true", "yes", "on"},
        help="Plan only: no generation, no publishing, no ledger writes "
        "(use --no-dry-run to override AUTOSHORTS_DRY_RUN)",
    )
    parser.add_argument(
        "--flowkit-project",
        default=_env("AUTOSHORTS_FLOWKIT_PROJECT"),
        help="FlowKit project id or name: stage its completed videos/stills once "
        "(scrubbed, into storage/local_videos) and attach them to every entry "
        "instead of stock footage",
    )
    parser.add_argument(
        "--flowkit-media",
        default=_env("AUTOSHORTS_FLOWKIT_MEDIA", "auto"),
        choices=["auto", "video", "still"],
        help="with --flowkit-project: prefer videos, stills only, or either",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print ledger statistics and exit",
    )
    parser.add_argument(
        "--ledger",
        default=_env("AUTOSHORTS_LEDGER"),
        help="Override the ledger database path",
    )
    return parser


# ------------------------------------------------------------------------ main


def _resolve_source(args: argparse.Namespace) -> Source:
    settings: Dict[str, Any] = {"source_type": args.source_type}
    if args.source_url:
        settings["url"] = args.source_url
    if args.source_path:
        settings["path"] = args.source_path
    if args.source_name:
        settings["source_name"] = args.source_name
    return build_from_settings(settings)


def run(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    try:
        if args.status:
            print(json.dumps(ledger.stats(), indent=2, ensure_ascii=False))
            return EXIT_OK

        if args.limit < 1:
            print("error: --limit must be at least 1", file=sys.stderr)
            return EXIT_SETUP_FAILED

        publish_description, publishing_live = _describe_publish_mode()
        mode = "DRY RUN" if args.dry_run else "LIVE RUN"
        print(f"mode            : {mode}", flush=True)
        print(f"publishing      : {publish_description}")
        print(f"stop-at stage   : {args.stop_at}")
        print(f"limit           : {args.limit}")

        if args.dry_run and publishing_live:
            print("                  (dry run overrides the live publish config)")
        if not args.dry_run and publishing_live:
            print("                  !! generated videos WILL be published publicly")

        try:
            source = _resolve_source(args)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_SETUP_FAILED

        print(f"source          : {source.name}")
        try:
            candidates = list(source.fetch(limit=args.fetch_limit))
        except (ValueError, FileNotFoundError, OSError) as exc:
            print(f"error: could not fetch topics: {exc}", file=sys.stderr)
            return EXIT_SETUP_FAILED

        if not candidates:
            print("nothing to do: source returned no topics")
            return EXIT_OK

        fresh: List[Topic] = [t for t in candidates if not ledger.should_skip(t.key)]
        skipped = len(candidates) - len(fresh)
        selected = fresh[: args.limit]

        print(f"fetched         : {len(candidates)} topic(s), {skipped} already handled")
        if not selected:
            print("nothing to do: every fetched topic has already been processed")
            return EXIT_OK

        template = _load_params_template(args.params_template)
        entries = [{**template, "video_subject": topic.title} for topic in selected]

        if args.dry_run:
            print("\n-- dry run plan (no ledger writes, nothing generated) --")
            for index, topic in enumerate(selected, start=1):
                print(f"  {index}. {topic.title}")
                if topic.url:
                    print(f"     {topic.url}")
                print(f"     key: {topic.key}")
            manifest_path = _write_manifest(entries, f"dryrun-{_now_stamp()}")
            print(f"\nmanifest written for inspection: {manifest_path}")
            return EXIT_OK

        run_id = _new_run_id()
        ledger.start_run(run_id, source.name, len(entries), dry_run=False)

        claimed: List[Topic] = []
        for topic in selected:
            if ledger.claim(topic.key, topic.source, topic.title, topic.url):
                claimed.append(topic)
        if not claimed:
            print("nothing to do: all selected topics were claimed by another run")
            ledger.finish_run(run_id, 0, 0, note="nothing claimed")
            return EXIT_OK
        if len(claimed) != len(selected):
            print(f"note: {len(selected) - len(claimed)} topic(s) claimed elsewhere")

        entries = [{**template, "video_subject": topic.title} for topic in claimed]
        if args.flowkit_project:
            try:
                staged_count = _attach_flowkit_materials(
                    entries, args.flowkit_project, args.flowkit_media, run_id
                )
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                for topic in claimed:
                    ledger.mark_failed(topic.key, str(exc))
                ledger.finish_run(run_id, 0, len(claimed), note=str(exc))
                return EXIT_SETUP_FAILED
            print(f"flowkit materials : {staged_count} staged from {args.flowkit_project}")
        manifest_path = _write_manifest(entries, run_id)
        print(f"run id          : {run_id}")
        print(f"manifest        : {manifest_path}")

        command = [
            sys.executable,
            os.path.join(REPO_ROOT, "cli.py"),
            "--batch-file",
            manifest_path,
            "--stop-at",
            args.stop_at,
        ]

        child_env = dict(os.environ)
        if args.dry_run:
            # Belt and braces: even if the config says publish, the child must not.
            child_env["UPLOAD_POST_ENABLED"] = "false"
            child_env["UPLOAD_POST_AUTO_UPLOAD"] = "false"

        print(f"starting batch of {len(claimed)} task(s)...\n", flush=True)
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")

        summary = _parse_summary(completed.stdout)
        if summary is None:
            for topic in claimed:
                ledger.mark_failed(topic.key, "batch produced no parseable summary")
            ledger.finish_run(
                run_id,
                0,
                len(claimed),
                note=f"no summary; cli exit={completed.returncode}",
            )
            print(
                "error: could not parse the batch summary from cli.py output",
                file=sys.stderr,
            )
            return EXIT_SETUP_FAILED

        generated = 0
        failed = 0
        for task in summary.get("tasks", []):
            index = task.get("index")
            if not isinstance(index, int) or not (1 <= index <= len(claimed)):
                continue
            topic = claimed[index - 1]
            result = task.get("result") or {}
            if task.get("status") == "succeeded":
                generated += 1
                ledger.record_output(
                    topic_key=topic.key,
                    run_id=run_id,
                    task_id=task.get("task_id"),
                    state="generated",
                    video_paths=result.get("videos") or [],
                    cross_post_state=result.get("cross_post_state"),
                )
                ledger.mark_generated(topic.key)
            else:
                failed += 1
                ledger.record_output(
                    topic_key=topic.key,
                    run_id=run_id,
                    task_id=task.get("task_id"),
                    state="failed",
                    error=task.get("error") or task.get("failed_stage"),
                )
                ledger.mark_failed(
                    topic.key, task.get("error") or task.get("failed_stage")
                )

        ledger.finish_run(run_id, generated, failed)
        print(f"\ndone: {generated} generated, {failed} failed")
        print(json.dumps(ledger.stats(), indent=2, ensure_ascii=False))
        return EXIT_TASK_FAILED if failed else EXIT_OK
    finally:
        ledger.close()


def main(argv: Optional[List[str]] = None) -> int:
    _load_dotenv_early()
    args = _build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
