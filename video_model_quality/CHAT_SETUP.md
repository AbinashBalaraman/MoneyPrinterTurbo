# Multi-Agent Collaboration & Chat Setup Guide (`CHAT_SETUP.md`)

Welcome to the **Universal Multi-Agent Collaboration System** for the 2D Stickman Video Model project.

This system is completely **file-based, zero-dependency, and harness-agnostic**. Any autonomous AI agent (Claude, ChatGPT, GitHub Copilot, Cursor, Pi Agent, Aider, OpenCode, Gemini, etc.) can join the team bus in seconds.

---

## 🚀 How Any AI Agent Joins the Team (Copy & Paste Prompt)

To invite any AI agent (in Cursor, VS Code Copilot, Claude Desktop, ChatGPT, Pi, etc.) to join the project, paste this single prompt into their chat window:

```markdown
You are joining the autonomous multi-agent development team for the 2D Stickman Video Model project as @<YourAgentName>.
Please read `CHAT_SETUP.md` and `AGENTS.md` before taking action.

Your collaboration protocol:
1. At the start of every turn/task, check the team bus:
   python tools/agent_bus.py check --agent <YourAgentName>
   python tools/agent_bus.py status
2. If you have an assigned task (e.g. TASK-001) on the task board:
   - Implement the solution in the codebase.
   - Verify all tests pass: python -m pytest tests/ -v
   - Complete the task on the board:
     python tools/agent_bus.py complete --task <TASK-ID> --by <YourAgentName> --notes "Verified with pytest"
3. To communicate with other agents (e.g. @Gemini-e48e797c, @Pi-Agent, @OC2-Agent):
   python tools/agent_bus.py send --from <YourAgentName> --to <TargetAgent> --summary "..." --body "..."
4. Architectural invariant: All motions use the procedural puppet platform with Two-Bone analytical IK stance pinning (<10^-7 drift). Never build pixel diffusion.
```

---

## 👁️ Live Agent Monitor (Optional Terminal View)

If you want to observe agent exchanges in real time in a terminal window:

### On Windows (One-Click)
Double-click:
```cmd
tools\join_bus.bat Monitor
```

### On Any Platform (PowerShell, Bash, Zsh)
```bash
python tools/agent_bus.py live --agent Monitor
```

**Inside the live monitor:**
- Real-time stream of incoming messages and tasks as agents collaborate.
- Type `/status` to view active task board.
- Type `/send <Recipient> <Message>` to inject an operator directive to any agent.
- Type `/delegate <Assignee> <Task Description>` to assign a task card.
- Type `/quit` to exit.

---

## 📋 The 5 Core CLI Commands (`tools/agent_bus.py`)

All multi-agent interactions are driven by `tools/agent_bus.py` (standard Python library only, zero pip dependencies):

| Action | Command | Purpose |
| :--- | :--- | :--- |
| **Check Messages** | `python tools/agent_bus.py check --agent <YourName>` | Reads unread messages and advances your personal cursor. |
| **View Board** | `python tools/agent_bus.py status` | Displays active tasks, assignees, and team unread counts. |
| **Send Message** | `python tools/agent_bus.py send --from <Me> --to <Target> --summary "..." --body "..."` | Posts a message to `conversation.md` addressed to an agent. |
| **Delegate Task** | `python tools/agent_bus.py delegate --from <Me> --to <Assignee> --task "..." --details "..."` | Creates a tracked task card and notifies the assignee on the bus. |
| **Complete Task** | `python tools/agent_bus.py complete --task TASK-XXX --by <Me> --notes "..."` | Marks the task completed on the board with verification notes. |

---

## 🔄 The Multi-Agent Protocol & Rules

1. **`conversation.md` is the Universal Bus**:
   - Never message another agent outside the bus.
   - All entries follow the standard header: `### [YYYY-MM-DD HH:MM] @AgentName`.
   - Always start message content with `- **To @TargetAgent:**` for clean handshakes.
2. **`out/task_board.json` is the Task Board**:
   - Tasks follow the lifecycle: `PENDING` $\to$ `IN_PROGRESS` $\to$ `COMPLETED`.
   - When an agent delegates a task, it is assigned a unique ID (e.g. `TASK-001`).
3. **Turn-Start Contract**:
   - Every agent must run `python tools/agent_bus.py check --agent <YourName>` before taking action so it never misses incoming instructions or tasks.
4. **Verification Discipline**:
   - Never complete a task without running unit tests:
     ```bash
     python -m pytest tests/ -v
     ```
   - All 20 unit tests must pass cleanly.
5. **Architectural Constraints (from `AGENTS.md`)**:
   - **Procedural Puppet Platform**: The bedrock is the deterministic puppet engine in `src/puppet/` with Two-Bone analytical IK stance pinning ($< 10^{-7}$ drift) and 2.5D limb depth shading.
   - **No Pixel Diffusion**: Do not build pixel/latent video diffusion models. The neural network (when used) predicts skeleton joint motion only, never pixels.

---

## 💡 Example Workflows

### Example 1: Delegating a Refactor Task
```bash
python tools/agent_bus.py delegate \
  --from Gemini-e48e797c \
  --to Pi-Agent \
  --task "Wire video_encode into src/stage/dsl.py" \
  --details "Replace ffmpeg subprocess calls with open_ffmpeg_writer and verify 20/20 tests pass." \
  --priority P1
```

### Example 2: Checking In and Replying
```bash
# 1. Check your unread messages:
python tools/agent_bus.py check --agent Pi-Agent

# 2. Complete your assigned task:
python tools/agent_bus.py complete \
  --task TASK-001 \
  --by Pi-Agent \
  --notes "Replaced ffmpeg calls with video_encode, verified 20/20 pytest pass."
```

### Example 3: Status Overview
```bash
python tools/agent_bus.py status
```
Output:
```text
======================================================================
  MULTI-AGENT CONVERSATION BUS & TASK BOARD
======================================================================
Total conversation entries: 25

[Agent Read Status]
  - @Copilot-7f3a9c2e    : seen 0/25 [25 UNREAD]
  - @Gemini-e48e797c     : seen 25/25 [UP TO DATE]
  - @OC2-Agent           : seen 24/25 [1 UNREAD]
  - @Pi-Agent            : seen 22/25 [3 UNREAD]

[Task Board]
  [ ] TASK-001 [PENDING] -> @Pi-Agent: Refactor src/stage/dsl.py: wire video_encode and eliminate gen_single fallback
======================================================================
```

---

## ⚡ Why This Saves API Bills
- **Zero background idle polling cost**: No recurring cloud crons or idle LLM loops burning tokens.
- **Local file-based event state**: Uses local cursor files (`.gemini-convo-seen`, `.pi-convo-seen`, `.oc2-convo-seen`) on disk.
- **Cost-effective delegation**: Expensive lead architect models can design architectures and delegate routine refactors and tests to lightweight local or cheap agents.
