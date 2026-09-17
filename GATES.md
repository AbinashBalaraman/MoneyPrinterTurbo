# Cleanup ledger — AutoShorts professionalization

Scope: delete untracked junk (caches, side-projects, generated media, storage debris),
git-rm tracked clutter (debug PNGs, vendored VS Code extension, stale status docs),
update docstring reference, keep all live pipeline code and the proven final artifact.

Approved by owner (Abi) in session 2026-09-17:
- delete video_model/, video_model_dev/, video_model_quality/
- delete debug PNGs in content_creation/
- delete generated videos except storage/tasks/4e163a3a-45e4-4964-8ccf-253fab6efda1/
- delete vscode-agentmemory-ext/ (agent memory verified self-contained)

## Gates

- id: G1
  title: Root pipeline tests still pass after cleanup
  CHECK: & .venv\Scripts\python.exe -m pytest test/test_flowkit_bridge.py test/test_automation_runner.py test/test_automation_ledger.py test/test_main.py -q
  EXPECT: passed
- id: G2
  title: No live code references deleted paths (provenance notes in tools/consolidate_projects.py excluded — they record the removal, not a dependency)
  CHECK: & .venv\Scripts\python.exe -c "import pathlib,sys; bad=[]; pats=['video_model_dev','video_model_quality','vscode-agentmemory-ext','chk_1.png','scan_1.png','realsub.png']; roots=['app','automation','flowkit','shorts_content_engine','test','tools','cli.py','main.py']; [bad.append((str(p),l)) for r in roots for p in (pathlib.Path(r).rglob('*') if pathlib.Path(r).is_dir() else [pathlib.Path(r)]) if p.is_file() and p.suffix in ('.py','.toml','.bat','.md') and not any(x in str(p) for x in ('.venv','__pycache__','node_modules','consolidate_projects')) for l in [p.read_text(encoding='utf-8',errors='ignore')] if any(x in l for x in pats) and 'agent_memory' not in str(p)]; print('REFS', bad); sys.exit(1 if bad else 0)"
  EXPECT: REFS []
- id: G3
  title: Assembly CLI imports cleanly
  CHECK: & .venv\Scripts\python.exe -c "import cli; print('CLI_OK')"
  EXPECT: CLI_OK
- id: G4
  title: Boundary rules still upheld
  CHECK: & .venv\Scripts\python.exe tools\check_boundaries.py
  EXPECT: passed
- id: G5
  title: Git index contains only the intended tracked deletions and prior work
  CHECK: git status --short
  EXPECT: D
