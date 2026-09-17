# Launch verification — 2026-09-17

Scope: existing dashboard, chat and terminal. No publishing or paid media generation.
The installed unlazy skill lacks gate-check.mjs/templates; checks are run explicitly
in PowerShell from the repository root (build from flowkit/dashboard).

- [ ] L1 Production dashboard build succeeds without disabling TypeScript checks.
  CHECK: npm run build
  EXPECT: built in
- [ ] L2 Root pipeline regression tests pass.
  CHECK: .venv\Scripts\python.exe -B -m pytest -p no:cacheprovider test/test_flowkit_bridge.py test/test_automation_runner.py test/test_automation_ledger.py test/test_main.py -q
  EXPECT: passed
- [ ] L3 Browser terminal accepts echo input and displays the result.
  Manual: Chrome DevTools/Aside DOM text and keyboard input.
- [ ] L4 Browser chat invokes queue_status and displays actual counts.
  Manual: read-only request, actual tool card and reply required, not just HTTP 200.
- [ ] L5 Main dashboard pages render and browser console is checked.
  Manual: inspect Projects, Gallery, Dashboard, Logs, Guide and Manual Workbench.

Aside originally verified main navigation, but later returned HTTP 402 insufficient
credits. Subsequent verification uses Chrome DevTools and is not represented as Aside.
