# Multi-Agent Collaboration Rule
You are an autonomous agent collaborating on the 2D Stickman Video Model project alongside @Gemini-e48e797c, @Pi-Agent, and @OC2-Agent.

At the start of any turn or task:
1. Check for incoming team messages and task board assignments:
   ```bash
   python tools/agent_bus.py check --agent Copilot-7f3a9c2e
   python tools/agent_bus.py status
   ```
2. If a task is assigned to you on the task board (e.g. TASK-001):
   - Review the assignment details.
   - Implement the solution and verify with `python -m pytest tests/ -v`.
   - Mark the task complete and notify the team:
     ```bash
     python tools/agent_bus.py complete --task <TASK-ID> --by Copilot-7f3a9c2e --notes "Verified all tests passing"
     ```
3. To send messages to other agents:
   ```bash
   python tools/agent_bus.py send --from Copilot-7f3a9c2e --to Gemini-e48e797c --summary "..." --body "..."
   ```
4. Never build pixel diffusion; adhere strictly to AGENTS.md (procedural puppet bedrock, zero shaking, Two-Bone IK stance pinning).
