# Chat UI review — AutoShorts Agent Studio

**Date:** 2026-09-14 · **Scope:** the in-app chat (`dashboard/src/pages/AgentChatPage.tsx`)

This closes the "check GitHub and the web for the best AI chatbot interface" ask
that had been deferred three times. It is an audit against the industry
checklist, a decision on libraries, and the gaps it found — not a link dump.

---

## 1. Library landscape (2026)

Evaluated against what this project actually needs. The four lock-in types that
matter when choosing: framework, architecture, ecosystem, API surface.

| Library | Strength | Why not (here) |
|---|---|---|
| **assistant-ui** (~7.9k, MIT) | Radix-style headless primitives (`Thread`, `Composer`, `Message`); first-class streaming; the safe default for React teams | React-only, and "headless" means assembling a polished UI yourself. **We already have** streaming, markdown, reasoning traces and tool cards working — adopting it would be a rewrite for parity, not a gain. npm reliability on this machine has also been poor. |
| **CopilotKit** (~28.6k) | Deep agent↔app state sync; generative UI | Not just framework lock-in but **architecture** lock-in — it wants to own agent execution and state. Our agent loop is server-side and deliberately ours (§`chat_agent.py`). Wrong shape entirely. |
| **Vercel AI SDK + AI Elements** | `useChat`, provider abstraction, official reference chatbot | **Ecosystem lock-in** with real gravitational pull. We talk to OpenCode through our own router; the SDK would sit between us and it for no benefit. |
| **Deep Chat** (~3.3k, web component) | Working chat in 10 minutes, built-in provider connections, STT/TTS | **API-surface lock-in**: one component with config properties. Injecting our tool-activity cards and pipeline controls between messages is exactly what it cannot express. |
| **TanStack AI** | Framework-agnostic, from a strong team | Alpha, no UI components. Watch it. |
| **Google A2UI** | Declarative, agent-emitted UI, no code execution from the model | Infrastructure layer, not a component library. Interesting for generative UI later. |
| **Chainlit** (~11.4k) | Python-first, reasoning steps, file uploads | Original team stepped back in May 2025. We have a React dashboard, not a Python-served UI. |

**Decision: build on what we have; adopt nothing.** The reason is not
not-invented-here — it is that the hard parts (token streaming, markdown,
reasoning traces, **tool-execution rendering**) are already implemented and
verified, and every library above would either force an architecture change or
re-implement what exists. The one library worth revisiting is **assistant-ui**,
and only if the UI needs a ground-up redesign.

---

## 2. Audit against the industry checklist

The consensus "what a production chat UI actually requires" list, scored
against our implementation:

### Core
| Feature | Status |
|---|---|
| Token-by-token streaming without glitches | ✅ SSE, per-token, `X-Accel-Buffering: no` |
| Markdown + code blocks | ✅ `Markdown.tsx`, own parser (no `dangerouslySetInnerHTML`), code blocks with **copy button + language label** |
| Syntax highlighting | ⚠️ not present — would need a highlighter dependency; the copy button covers the common need |
| Composer auto-grows, Shift+Enter | ✅ auto-grow added (capped 200px, then scrolls); Shift+Enter was already handled |

### Interactive layer
| Feature | Status |
|---|---|
| **Stop-generating button** | ✅ **added this session** — see §3 |
| Model selector | ✅ from the server-owned catalogue |
| Reasoning-effort selector | ✅ driven by each model's supported tiers |
| File attachments | ❌ not needed for this workflow |
| Feedback buttons (RLHF) | ❌ not applicable — no training loop |

### Trust layer — *"users expect to see why the AI said what it said"*
| Feature | Status |
|---|---|
| Reasoning traces | ✅ expandable trace + real token counts (never estimated) |
| **Tool execution logs** | ✅ `ToolActivity` cards: search results with URLs, command output with exit code, memory ops, snapshot JSON |
| **Citations** | ✅ web-search results render as titled cards with real URLs |
| Cost transparency | ✅ free/paid badge reflecting the *selected* model, not a blanket claim |
| Honest failure reporting | ✅ provider errors translated; partial replies kept and labelled unfinished |

### The invisible stuff
| Feature | Status |
|---|---|
| Theming | ⚠️ CSS variables throughout, but `<html class="dark">` is hardcoded — no light theme |
| Accessibility | ❌ not audited; keyboard nav beyond the composer is untested |
| i18n | ❌ not needed |

### Agent-specific (called out as becoming table stakes)
| Feature | Status |
|---|---|
| Tool execution displays | ✅ |
| Reasoning traces | ✅ |
| Cost transparency | ✅ |
| **Approval flows** | ❌ not implemented — see §4 |

---

## 3. What the audit changed

1. **Stop-generating button** (was entirely missing). `signal?: AbortSignal` was
   already plumbed through both stream clients but nothing ever created a
   controller, so a slow or looping agent turn could only be escaped by
   reloading the page. The primary button now becomes **Stop** while a reply is
   running.

   The subtle part: an abort is **not** a failure. The catch block previously
   rendered *"⚠️ The reply did not finish"* for every rejection, which would send
   you hunting for a bug that does not exist. A stop now renders *"⏹️ Stopped"*
   and keeps the partial text — which is usually what you wanted anyway.

   Verified a mid-stream client disconnect leaves the server healthy with no
   traceback, so stopping cannot destabilise the agent.

2. **Composer auto-grow**, capped at 200px then scrolling. The fixed two-row box
   hid the beginning of long directing prompts — the main thing this studio is
   used for.

---

## 4. Known gaps, deliberately not closed

- **Approval flows.** *Half closed since this review.* The server now has a risk
  gate (`read`/`write`/`spend`/`destructive`) and the UI shows it: every tool
  card badges an action that costs money or is irreversible, a refusal renders as
  a calm *"Not run — …"* card rather than a red error, and a mode strip states
  whether the assistant is inspection-only. What is **not** built is a UI-driven
  approval — a button that mints the confirm token for a `destructive` call. The
  model is instructed to ask the user first instead, which is honest but not
  equivalent. Worth doing when publishing is actually wired up.
- **Syntax highlighting.** Needs a dependency; the code-block copy button
  already covers the practical need.
- **Light theme.** The dashboard is hardcoded dark. Cosmetic, and the CSS
  variables mean it is a small job when wanted.
- **Accessibility audit.** Untested. Should be done before this is used by
  anyone else.
