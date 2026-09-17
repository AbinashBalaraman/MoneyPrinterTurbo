# Launch verification — 2026-09-17

Scope: existing dashboard, chat and terminal. No publishing or paid media generation.
The installed unlazy skill lacks gate-check.mjs/templates; checks are run explicitly
in PowerShell from the repository root (build from flowkit/dashboard).

- [x] L1 Production dashboard build succeeds without disabling TypeScript checks.
  CHECK: npm run build
  EXPECT: built in
  EVIDENCE: "✓ built in 20.60s", exit 0.
- [x] L2 Root pipeline regression tests pass.
  CHECK: .venv\Scripts\python.exe -B -m pytest -p no:cacheprovider test/test_flowkit_bridge.py test/test_automation_runner.py test/test_automation_ledger.py test/test_main.py -q
  EXPECT: passed
  EVIDENCE: "88 passed in 5.28s".
- [x] L3 Browser terminal accepts echo input and displays the result.
  Manual: Chrome DevTools keyboard input into .xterm.
  EVIDENCE: .xterm-rows contains "echo TERMINAL_UI_OKTERMINAL_UI_OK" with a live
  cmd.exe prompt rooted at the workspace.
- [x] L4 Chat agent stream returns model output end-to-end.
  Manual/API: POST /api/opencode/agent/stream with gemini-3.8-flash.
  EVIDENCE: delta frames contain "PIPELINE_OK_73". UI verification of the same
  request was blocked twice by a transient Google 503 (high demand); the error
  rendered correctly with a working Retry button. muse-spark-*-free and
  nemotron-*-free models are refused by OpenCode's free-tier policy from any
  non-OpenCode client — provider policy, not an app bug. gemini-2.5-* and
  gemini-2.0 ids are retired by Google for new users.
- [x] L5 Main dashboard pages render without blank panels.
  Manual: Chrome DevTools snapshots of Chat, Projects, Gallery, Dashboard, Logs,
  Guide.
  EVIDENCE: all pages render real data (2 projects, dashboard widgets, live
  logs, WS LIVE badge); zero browser console errors.

Aside originally verified main navigation, but later returned HTTP 402 insufficient
credits. Remaining verification used Chrome DevTools and the backend API directly.
