"""Batch harness: run many prompts, rank the failures, watch only the worst.

The point of this tool is to make motion quality *measurable at a glance*.
Instead of eyeballing clips one at a time, you run a corpus, get a ranked list
of what is broken and why, and then watch only the failures.

Usage:
    python tools/batch_harness.py                       # built-in corpus, no render
    python tools/batch_harness.py --render-worst 5      # also render the 5 worst
    python tools/batch_harness.py --prompts prompts.txt # one prompt per line
    python tools/batch_harness.py --json out/batch.json --md out/BATCH.md

Exit code is non-zero if any prompt failed to plan, so it can gate CI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.service import batch, produce  # noqa: E402

# A varied corpus: every 1P action, every paired action, and some multi-beat
# scenes. Deliberately includes the known-hard cases (getup, knockdown).
CORPUS: List[str] = [
    "idle", "walk forward", "run", "walk back", "jump", "punch", "kick",
    "block", "wave", "squat", "knockdown", "get up", "celebrate",
    "punch and block", "kick and dodge", "exchange", "knockdown and get up",
    "walk forward, then punch, then celebrate",
    "two stickmen fight for 3 seconds",
    "run in, jump, land, then wave",
    "idle then slowly walk backwards",
    "a stickman punches twice then blocks",
    "squat, jump, and celebrate",
]

# Severity weights: a correctness defect is worth far more than timing debt,
# so the ranking surfaces broken motion above merely-mechanical motion.
WEIGHT = {
    "ground_penetration": 100,
    "numeric_instability": 100,
    "decode_failure": 100,
    "targeted_interaction_absent": 60,
    "jerk_spike": 20,
    "foot_slide": 15,
    "dead_hold": 8,
    "missing_anticipation": 3,
    "linear_easing": 1,
}


def score(row: Dict[str, Any]) -> int:
    """Rank key: correctness defects dominate timing debt."""
    if not row.get("ok") and row.get("error"):
        return 1000  # failed to even plan/compile -- worst possible
    return sum(WEIGHT.get(c, 5) for c in row.get("hard", [])) + \
        sum(WEIGHT.get(c, 1) for c in row.get("timing", []))


def _load_prompts(path: str) -> List[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _fmt_codes(codes: List[str]) -> str:
    return ", ".join(codes) if codes else "--"


def write_markdown(rows: List[Dict[str, Any]], path: Path, rendered: Dict[str, str]) -> None:
    lines = ["# Batch harness: ranked failures", ""]
    n_ok = sum(1 for r in rows if r["ok"])
    lines.append(f"- prompts: **{len(rows)}**  |  clean: **{n_ok}**  |  "
                 f"blocked: **{len(rows) - n_ok}**")
    lines.append("")
    lines.append("Ranked worst-first. Correctness defects outweigh timing debt, so the "
                 "top of this list is what to fix next.")
    lines.append("")
    lines.append("| # | score | prompt | hard defects | timing debt | clip |")
    lines.append("|---|-------|--------|--------------|-------------|------|")
    for i, r in enumerate(rows, 1):
        clip = rendered.get(r["prompt"], "")
        clip_cell = f"[watch]({Path(clip).name})" if clip else ""
        lines.append(f"| {i} | {r['score']} | {r['prompt']} | "
                     f"{_fmt_codes(r.get('hard', []))} | {_fmt_codes(r.get('timing', []))} | {clip_cell} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch motion-quality harness")
    ap.add_argument("--prompts", type=str, default=None,
                    help="File of prompts, one per line (# comments allowed).")
    ap.add_argument("--render-worst", type=int, default=0,
                    help="Also render the N worst clips (slow).")
    ap.add_argument("--render-all", action="store_true", help="Render every clip.")
    ap.add_argument("--sd", action="store_true", help="Render SD arena (fast).")
    ap.add_argument("--strict-timing", action="store_true",
                    help="Treat timing debt as blocking when ranking.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-dir", type=str, default="out/batch")
    ap.add_argument("--json", type=str, default="out/batch/report.json")
    ap.add_argument("--md", type=str, default="out/batch/FAILURES.md")
    args = ap.parse_args()

    prompts = _load_prompts(args.prompts) if args.prompts else CORPUS
    print(f"[*] Running {len(prompts)} prompts through plan -> compile -> diagnose...")
    rows = batch(prompts, seed=args.seed, strict_timing=args.strict_timing)
    for r in rows:
        r["score"] = score(r)
    rows.sort(key=lambda r: r["score"], reverse=True)

    n_ok = sum(1 for r in rows if r["ok"])
    print(f"[+] Clean: {n_ok}/{len(rows)}   Blocked: {len(rows) - n_ok}/{len(rows)}")
    print()
    print(f"{'score':>6}  {'prompt':<44}  hard / timing")
    print("-" * 92)
    for r in rows:
        print(f"{r['score']:>6}  {r['prompt'][:44]:<44}  "
              f"{_fmt_codes(r.get('hard', []))} / {_fmt_codes(r.get('timing', []))}")

    # Optional rendering of the worst offenders.
    rendered: Dict[str, str] = {}
    to_render = rows if args.render_all else rows[:max(0, args.render_worst)]
    if to_render:
        out_dir = Path(args.out_dir)
        print(f"\n[*] Rendering {len(to_render)} clip(s) to {out_dir}...")
        for i, r in enumerate(to_render, 1):
            name = f"rank{i:02d}"
            res = produce(r["prompt"], out_dir, sd=args.sd, seed=args.seed,
                          strict_timing=args.strict_timing, name=name)
            if res.get("video"):
                rendered[r["prompt"]] = res["video"]
                print(f"    [{i}/{len(to_render)}] {r['prompt'][:44]:<44} -> {res['video']}")
            else:
                print(f"    [{i}/{len(to_render)}] {r['prompt'][:44]:<44} -> BLOCKED "
                      f"({_fmt_codes([h['code'] for h in (res.get('report') or {}).get('hard', [])])})")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(
        {"count": len(rows), "clean": n_ok, "rows": rows, "rendered": rendered},
        indent=2), encoding="utf-8")
    write_markdown(rows, Path(args.md), rendered)
    print(f"\n[+] Report: {args.json}\n[+] Summary: {args.md}")

    plan_failures = sum(1 for r in rows if r.get("error"))
    return 1 if plan_failures else 0


if __name__ == "__main__":
    sys.exit(main())
