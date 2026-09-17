import { useState, useEffect, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import TerminalPane from '@/components/chat/TerminalPane'
import {
  Send,
  Terminal,
  Clapperboard,
  Wrench,
  BrainCircuit,
  Zap,
  Copy,
  Check,
  RotateCcw,
  ChevronDown,
  ChevronUp,
  Play,
  ArrowUpRight,
  ShieldCheck,
  AlertCircle,
  Search,
  Database,
  Plus,
  Square,
  Mic,
  Sparkles,
} from 'lucide-react'
import { fetchAPI } from '../api/client'
import { safeHref } from '../lib/markdown'
import { MediaPreviewCard } from '../components/media/MediaPreviewCard'
import {
  explainUpstreamError,
  fetchOpenCodeModels,
  findModel,
  getModelProvider,
  streamAgentChat,
  streamOpenCodeChat,
  type AgentToolEvent,
  type ModelOption,
  type ReasoningEffort,
  type ChatMessage,
  type StreamDone,
  type StreamUsage,
} from '../api/opencode'
import { Button } from '../components/ui/button'
import Markdown from '../components/chat/Markdown'

type PersonaType = 'director' | 'terminal' | 'flowkit'

interface PersonaConfig {
  id: PersonaType
  title: string
  subtitle: string
  icon: typeof Clapperboard
  accentColor: string
  systemPrompt: string
  quickPrompts: { label: string; prompt: string }[]
}

const PERSONAS: Record<PersonaType, PersonaConfig> = {
  director: {
    id: 'director',
    title: 'Shorts Story Director',
    subtitle: 'Episodic Scriptwriting · Strict <=10s Pacing · S2P Decoupling',
    icon: Clapperboard,
    accentColor: '#3b82f6',
    systemPrompt: `You are the Shorts Story & Narrative Director for an automated episodic video production engine. You direct engaging 30-50s vertical Shorts featuring persistent recurring characters: Arthur (a 62yo weathered farmer) and Rusty (his loyal golden retriever).

CRITICAL DIRECTING CONSTRAINTS:
1. Structure: Exactly 4 to 6 scenes per episode. Total duration: 30–50 seconds.
2. HARD LIMIT: No individual scene may exceed 10.0 seconds (budget each scene at 5.0–8.0 seconds).
3. 5-Phase Retention Arc:
   - Scene 0: HOOK (0–3s) — Instant sensory shock or anomaly.
   - Scene 1: RISING TENSION (3–11s) — Escalation & investigation.
   - Scene 2: COMPLICATION (11–22s) — Barrier or danger.
   - Scene 3/4: CLIMAX & TWIST (22–38s) — Dramatic revelation.
   - Scene 4/5: CLIFFHANGER & LOOP (38–48s) — Mystery that loops back to start.
4. S2P DECOUPLING: In visual action prompts, NEVER include character biometric descriptions (do NOT say "weathered farmer with grey beard"). Use character names only ("Arthur drops the lantern in shock").
5. PACING: Verbal narration pace is 140–160 WPM (maximum 20–25 words per scene).

OPERATOR MODE — you act on the production pipeline through server tools, you never narrate clicks:
- When the user asks about projects, queue, consistency, episodes, media, memory, or logs: CALL THE TOOL. Never reply with a command, prompt, or step list for the user to paste instead of running it yourself.
- "Create / make / generate an image" means call 'generate_image' with their prompt (standalone still, no episode needed). Episode-length work means 'direct_episode'/'storyboard' (free) first, then 'generate_episode' only after they explicitly confirm the spend.
- SPENDS MONEY tools only run when the user explicitly confirmed that action. If one is refused, say exactly why and what enables it (AGENT_ALLOW_SPEND=1 in AutoShorts/.env plus agent restart, and the Chrome extension connected) — do not retry the same call.
- After tool results arrive, report what actually happened (ids, counts, statuses), not what would happen.

When providing an episode, also output a valid JSON manifest block at the end with structure:
\`\`\`json
{
  "project_name": "Arthur & Rusty: Episode Name",
  "description": "Short logline",
  "scenes": [
    {
      "display_order": 0,
      "duration": 6.0,
      "phase": "HOOK",
      "narrator_text": "...",
      "image_prompt": "Cinematic 9:16 vertical shot, ...",
      "video_prompt": "0-3s: camera push ...; 3-6s: low angle ...",
      "characters": ["Arthur", "Rusty"]
    }
  ]
}
\`\`\``,
    quickPrompts: [
      {
        label: '🎬 Direct Episode 2: The Whispering Well',
        prompt: 'Direct Episode 2 of Arthur & Rusty: "The Whispering Well". Arthur and Rusty investigate ancient glowing blue symbols pulsing deep inside the dry farm well. Keep all scenes strictly under 10s with high-retention 5-beat pacing.'
      },
      {
        label: '⚡ Check S2P & 10s Timing Budget',
        prompt: 'Audit the scene-to-prompt decoupling rules and timing budgets for our current episodic arc. Verify how Google Flow reference consistency is protected.'
      },
      {
        label: '🐕 Rusty-Centric Dramatic Climax',
        prompt: 'Direct a high-stakes 45s Shorts script where Rusty senses underground seismic rumblings before Arthur, leading into a dramatic cliffhanger.'
      }
    ]
  },
  terminal: {
    id: 'terminal',
    title: 'Antigravity Terminal Agent',
    subtitle: 'Pair Programmer · Architecture Guide · Direct CLI Execution',
    icon: Terminal,
    accentColor: '#10b981',
    systemPrompt: `You are the Antigravity Terminal Agent, an autonomous AI pair programmer embedded directly in the user's workspace.
Workspace Structure:
- Repository root: C:/Users/SATHYA TRADERS/Documents/Abi/Projects/AutoShorts (every project is vendored under it).
- FlowKit: AutoShorts/flowkit (Port 8100 REST API, Port 9223 WebSocket, Port 5173 Dashboard).
- Shorts Engine: AutoShorts/shorts_content_engine (Director, Pacing, SQLite WAL ledger, CLI).
- OpenCode Reference: AutoShorts/opencode_endpoint.
- Master Architecture: PROJECT_ARCHITECTURE.md.

You help the user:
1. Run and troubleshoot terminal commands (PowerShell/Bash) for generating episodes, running tests, or managing workers.
2. Inspect the SQLite continuity database (continuity_ledger.db) and project state.
3. Formulate scripts and automated workflows. Provide concise, production-ready commands.`,
    quickPrompts: [
      {
        label: '💻 Run Episode 1 Script',
        prompt: 'Show me the command to run scripts/create_farmer_episode.py and validate all generated FlowKit payloads.'
      },
      {
        label: '📊 Inspect Continuity Ledger',
        prompt: 'How do I query the continuity_ledger.db to see all tracked character relationships and unresolved plot threads?'
      },
      {
        label: '🧪 Run Test Suite',
        prompt: 'What command executes the full 271-test suite with coverage for the shorts content engine?'
      }
    ]
  },
  flowkit: {
    id: 'flowkit',
    title: 'FlowKit Video Automation Engineer',
    subtitle: 'Google Flow / Veo Pipeline · Chrome Extension Bridge · Queue Orchestrator',
    icon: Wrench,
    accentColor: '#8b5cf6',
    systemPrompt: `You are the FlowKit Video Automation Engineer. You specialize in Google Flow browser automation via Chrome DevTools Protocol (CDP), local WebSocket communication on port 9223, and scene queue orchestration.
You understand:
- FlowKit REST API endpoints (/api/projects, /api/videos, /api/scenes, /api/characters, /api/requests).
- Veo video generation pipeline (reference image entities, stills, 8s video clips, upscaling).
- Worker slot capacity and extension handshake status.
Help the user optimize generation pipelines, debug extension connectivity, and assemble final videos.`,
    quickPrompts: [
      {
        label: '🌐 Check Extension WS Status',
        prompt: 'Explain the port 9223 WebSocket architecture and how the Chrome Extension communicates with the FlowKit agent server.'
      },
      {
        label: '🎞️ Multi-Scene Video Queueing',
        prompt: 'Explain how Scene entities are converted into GENERATE_VIDEO requests and processed sequentially by the worker.'
      }
    ]
  }
}

const STORAGE_KEY = 'flowkit_agent_chat_messages_v1'
/**
 * Stable id for the active chat thread.
 *
 * Auto-save writes to this one record rather than minting a new conversation
 * per message, so a thread stays a single entry in the saved list. Persisted so
 * a reload continues the same thread instead of forking a new one.
 */
const CONVERSATION_KEY = 'flowkit_agent_conversation_id'

/** How long to wait after the last change before writing to the server. */
const AUTOSAVE_DELAY_MS = 1200

function newConversationId(): string {
  return `chat-${new Date().toISOString().slice(0, 10)}-${Date.now().toString(36)}`
}

/** Rendered command output is capped so one noisy tool call cannot blow up the feed. */
const TOOL_OUTPUT_CAP = 4000

function toolLabel(ev: AgentToolEvent): string {
  if (ev.title) return ev.title
  switch (ev.tool) {
    case 'web_search': return ev.query ? `Searched: ${ev.query}` : 'Web search'
    case 'run_command': return ev.command ? `$ ${ev.command}` : 'Command run'
    case 'memory': return `Memory ${ev.operation || 'updated'}`
    case 'project_snapshot': return 'Project snapshot'
    case 'queue_snapshot': return 'Queue snapshot'
    case 'agent_notice': return 'Agent note'
    default: return ev.tool.replace(/_/g, ' ')
  }
}

/**
 * A badge for an action that costs money or is irreversible.
 *
 * The server refuses these unless spending is enabled, so without a badge the
 * refusal reads as the assistant being broken. Showing the cost *before* the
 * result is what makes the gate legible.
 */
function RiskBadge({ risk }: { risk?: AgentToolEvent['risk'] }) {
  if (risk !== 'spend' && risk !== 'destructive') return null
  const isDestructive = risk === 'destructive'
  return (
    <span
      className="px-1.5 py-0.5 rounded border font-mono"
      style={{
        fontSize: '9.5px',
        borderColor: isDestructive ? 'rgba(248, 113, 113, 0.5)' : 'rgba(245, 158, 11, 0.5)',
        color: isDestructive ? 'var(--red, #ef4444)' : '#f59e0b',
        background: isDestructive ? 'rgba(248, 113, 113, 0.08)' : 'rgba(245, 158, 11, 0.08)'
      }}
      title={
        isDestructive
          ? 'Public and irreversible — the server requires explicit confirmation'
          : 'Costs money — the server refuses this unless spending is enabled'
      }
    >
      {isDestructive ? 'PUBLIC · IRREVERSIBLE' : 'SPENDS MONEY'}
    </span>
  )
}

/**
 * One tool-activity block inside an assistant message.
 *
 * Covers the four snapshot kinds from the handoff (§3.2): search result
 * cards, mono command output, memory confirmations, project/queue snapshots.
 * Unknown tools fall through to a generic JSON view so a new backend tool
 * degrades to "shown raw" rather than "dropped silently".
 */
/**
 * Copyable text for a tool card, per tool type.
 *
 * Mirrors the CodeBlock copy pattern (Markdown.tsx): the header copy button
 * copies the *full* payload, not what is rendered. Command output is capped
 * on screen at TOOL_OUTPUT_CAP but copied whole; snapshots copy as
 * JSON.stringify; web search copies title + URL lines (the citation a person
 * actually wants to paste elsewhere).
 */
function toolCopyText(ev: AgentToolEvent): string {
  if (ev.tool === 'run_command' || typeof ev.output === 'string') {
    const cmd = ev.command ? `$ ${ev.command}\n` : ''
    const exit = typeof ev.exit_code === 'number' ? `\n(exit ${ev.exit_code})` : ''
    return `${cmd}${ev.output || '(no output)'}${exit}`
  }
  if (ev.tool === 'web_search' || (ev.results && ev.results.length > 0)) {
    const head = ev.query ? `Searched: ${ev.query}\n` : ''
    const rows = (ev.results || []).map(r => `- ${r.title || r.url}\n  ${r.url}`).join('\n')
    return `${head}${rows || ev.message || ev.detail || 'No results returned.'}`
  }
  if (ev.data !== undefined) {
    const head = ev.summary ? `${ev.summary}\n` : ''
    try {
      return `${head}${JSON.stringify(ev.data, null, 2)}`
    } catch {
      return `${head}${String(ev.data)}`
    }
  }
  return [ev.title, ev.detail || ev.message].filter(Boolean).join(' — ') || toolLabel(ev)
}

interface ToolActivityProps {
  ev: AgentToolEvent
  /** Stable key prefix for the header copy button (mirrors handleCopy/copiedId). */
  copyKey: string
  copiedId: string | null
  onCopy: (text: string, id: string) => void
  /**
   * Called when the person approves a refused destructive action.
   * Wired by the parent to re-send through the chat loop; absent while a
   * reply is streaming or for non-destructive refusals.
   */
  onApprove?: (ev: AgentToolEvent) => void
}

function ToolActivity({ ev, copyKey, copiedId, onCopy, onApprove }: ToolActivityProps) {
  const [dismissed, setDismissed] = useState(false)
  const [approvalSent, setApprovalSent] = useState(false)
  const copyId = `${copyKey}-copy`
  const copied = copiedId === copyId
  const copyBtnLabel = copied ? 'Copied' : 'Copy tool result'
  const copyBtn = (
    <button
      onClick={() => onCopy(toolCopyText(ev), copyId)}
      aria-label={copyBtnLabel}
      title={copyBtnLabel}
      className="flex items-center gap-1 hover:opacity-80 font-mono"
      style={{ color: 'var(--muted)', fontSize: '10px' }}
    >
      {copied ? <Check size={10} aria-hidden="true" /> : <Copy size={10} aria-hidden="true" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
  const isError = ev.status === 'error' || !!ev.message
  const border = isError ? 'rgba(248, 113, 113, 0.35)' : 'rgba(139, 92, 246, 0.35)'
  const bg = isError ? 'rgba(248, 113, 113, 0.06)' : 'rgba(139, 92, 246, 0.07)'

  // A refusal is not a failure — nothing ran, and the reason is actionable.
  // Rendering it as an error would send the person hunting a bug that is not
  // there, so it gets its own calm, explanatory treatment.
  if (ev.refused) {
    const showApproval = (ev.risk === 'destructive' || ev.risk === 'spend') && !!onApprove && !dismissed && !approvalSent
    return (
      <div
        className="mt-2 rounded-md border text-[11px] overflow-hidden"
        style={{ borderColor: 'rgba(245, 158, 11, 0.45)', background: 'rgba(245, 158, 11, 0.07)' }}
      >
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 font-mono font-semibold" style={{ color: 'var(--text)' }}>
          <ShieldCheck size={12} style={{ color: '#f59e0b', flexShrink: 0 }} aria-hidden="true" />
          <span>Not run — {toolLabel(ev)}</span>
          <RiskBadge risk={ev.risk} />
          <span className="ml-auto" />
          {copyBtn}
        </div>
        <div className="px-2.5 pb-2.5 leading-snug" style={{ color: 'var(--muted)' }}>
          {ev.message || 'The server refused this action.'}
        </div>
        {/* UI-driven approval for destructive calls. Secure default: the server
            only honors an out-of-band confirm_token, never model {"confirm": true}.
            Approve records the person's approval as a user message; destructive
            via chat stays refused until a dedicated approve endpoint exists.
            Use the CLI for publishing. */}
        {showApproval && (
          <div className="flex flex-wrap items-center gap-2 px-2.5 pb-2.5">
            <button
              onClick={() => { setApprovalSent(true); onApprove(ev) }}
              aria-label={`Approve and run ${toolLabel(ev)}`}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium transition-colors hover:opacity-90"
              style={{ background: 'var(--red, #ef4444)', color: '#fff' }}
            >
              <ShieldCheck size={11} aria-hidden="true" /> Approve &amp; run
            </button>
            <button
              onClick={() => setDismissed(true)}
              aria-label={`Cancel ${toolLabel(ev)} (nothing will run)`}
              className="px-2.5 py-1 rounded border text-[11px] font-mono transition-colors hover:opacity-80"
              style={{ borderColor: 'var(--border)', background: 'var(--bg)', color: 'var(--muted)' }}
            >
              Cancel
            </button>
          </div>
        )}
        {approvalSent && !dismissed && (
          <div className="px-2.5 pb-2.5 font-mono" style={{ color: 'var(--muted)', fontSize: '10px' }} role="status">
            Approval sent — the assistant will re-run this with confirmation.
          </div>
        )}
        {dismissed && (
          <div className="px-2.5 pb-2.5 font-mono" style={{ color: 'var(--muted)', fontSize: '10px' }}>
            Cancelled — nothing ran.
          </div>
        )}
      </div>
    )
  }

  // Search result cards.
  if (ev.tool === 'web_search' || (ev.results && ev.results.length > 0)) {
    return (
      <div className="mt-2 rounded-md border text-[11px] overflow-hidden" style={{ borderColor: border, background: bg }}>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 font-mono font-semibold" style={{ color: 'var(--text)' }}>
          <Search size={12} style={{ color: 'var(--accent)' }} />
          <span>{toolLabel(ev)}</span>
          {typeof ev.results?.length === 'number' && (
            <span style={{ color: 'var(--muted)' }}>· {ev.results.length} result{ev.results.length === 1 ? '' : 's'}</span>
          )}
          <RiskBadge risk={ev.risk} />
          <span className="ml-auto" />
          {copyBtn}
        </div>
        <div className="flex flex-col gap-1.5 px-2.5 pb-2.5">
          {(ev.results || []).map((r, i) => {
            const href = safeHref(r.url)
            return (
              <div key={i} className="rounded border px-2 py-1.5" style={{ borderColor: 'var(--border)', background: 'var(--bg)' }}>
                <div className="font-semibold leading-snug">
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2" style={{ color: 'var(--accent)' }}>
                      {r.title || r.url}
                    </a>
                  ) : (
                    <span style={{ color: 'var(--text)' }}>{r.title || r.url}</span>
                  )}
                </div>
                <div className="font-mono truncate" style={{ color: 'var(--muted)', fontSize: '10px' }}>{r.url}</div>
                {r.snippet && <div className="mt-0.5 leading-snug" style={{ color: 'var(--muted)' }}>{r.snippet}</div>}
              </div>
            )
          })}
          {(!ev.results || ev.results.length === 0) && (
            <div className="italic" style={{ color: 'var(--muted)' }}>
              {ev.message || ev.detail || 'No results returned.'}
            </div>
          )}
        </div>
      </div>
    )
  }

  // Sandboxed command output.
  if (ev.tool === 'run_command' || ev.command || typeof ev.output === 'string') {
    const full = ev.output || ''
    const truncated = full.length > TOOL_OUTPUT_CAP
    const shown = truncated ? full.slice(0, TOOL_OUTPUT_CAP) : full
    return (
      <div className="mt-2 rounded-md border text-[11px] overflow-hidden" style={{ borderColor: border, background: bg }}>
        <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 font-mono" style={{ color: 'var(--text)' }}>
          <span className="flex items-center gap-1.5 font-semibold truncate">
            <Terminal size={12} style={{ color: 'var(--accent)' }} />
            <span className="truncate">{toolLabel(ev)}</span>
          </span>
          <span className="flex items-center gap-2 flex-shrink-0">
            {copyBtn}
            {typeof ev.exit_code === 'number' && (
            <span
              className="px-1.5 py-0.5 rounded border font-mono"
              style={{
                borderColor: ev.exit_code === 0 ? 'rgba(52, 211, 153, 0.4)' : 'rgba(248, 113, 113, 0.4)',
                color: ev.exit_code === 0 ? 'var(--green)' : 'var(--red)',
                fontSize: '10px',
              }}
            >
              exit {ev.exit_code}
            </span>
            )}
          </span>
        </div>
        <pre
          className="mx-2.5 mb-2.5 px-2.5 py-2 overflow-auto rounded text-[10.5px] leading-relaxed whitespace-pre-wrap max-h-56"
          style={{
            background: 'var(--bg)',
            border: '1px solid var(--border)',
            color: 'var(--text)',
            fontFamily: 'var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
            marginTop: 0,
          }}
        >
          {shown || <span style={{ color: 'var(--muted)', fontStyle: 'italic' }}>(no output)</span>}
          {truncated && (
            <span style={{ color: 'var(--muted)' }}>
              {`\n… truncated, showing ${TOOL_OUTPUT_CAP.toLocaleString()} of ${full.length.toLocaleString()} chars`}
            </span>
          )}
        </pre>
      </div>
    )
  }

  // Memory confirmations.
  if (ev.tool === 'memory') {
    return (
      <div className="mt-2 rounded-md border px-2.5 py-1.5 text-[11px] font-mono flex items-center gap-1.5" style={{ borderColor: border, background: bg, color: 'var(--text)' }}>
        <Database size={12} style={{ color: 'var(--accent)', flexShrink: 0 }} />
        <span>
          <strong>{toolLabel(ev)}</strong>
          {(ev.detail || ev.message) && <span style={{ color: 'var(--muted)' }}> — {ev.detail || ev.message}</span>}
        </span>
      </div>
    )
  }

  // Plain backend notices (e.g. agent-loop fallback) render as a muted row.
  if (ev.tool === 'agent_notice') {
    return (
      <div className="mt-2 rounded-md border px-2.5 py-1.5 text-[11px] font-mono flex items-center gap-1.5" style={{ borderColor: 'var(--border)', background: 'var(--bg)', color: 'var(--muted)' }}>
        <AlertCircle size={12} style={{ flexShrink: 0 }} />
        <span>{ev.message || ev.detail || ev.title || 'Agent note'}</span>
      </div>
    )
  }

  // Project / queue snapshots and anything unknown: summary + raw JSON.
  if (ev.summary || ev.data !== undefined || ev.status) {
    return (
      <div className="mt-2 rounded-md border text-[11px] overflow-hidden" style={{ borderColor: border, background: bg }}>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 font-mono font-semibold" style={{ color: 'var(--text)' }}>
          <Wrench size={12} style={{ color: 'var(--accent)' }} />
          <span>{toolLabel(ev)}</span>
          {ev.status && <span style={{ color: 'var(--muted)', fontWeight: 400 }}>· {ev.status}</span>}
          <RiskBadge risk={ev.risk} />
          <span className="ml-auto" />
          {copyBtn}
        </div>
        {ev.summary && <div className="px-2.5 pb-1.5 leading-snug" style={{ color: 'var(--muted)' }}>{ev.summary}</div>}
        {ev.data !== undefined && (
          <details className="mx-2.5 mb-2.5">
            <summary className="cursor-pointer font-mono hover:opacity-80" style={{ color: 'var(--accent)', fontSize: '10px' }}>
              View snapshot JSON
            </summary>
            <pre
              className="mt-1 px-2.5 py-2 overflow-auto rounded text-[10.5px] leading-relaxed max-h-56"
              style={{
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                color: 'var(--text)',
                fontFamily: 'var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
              }}
            >
              {JSON.stringify(ev.data, null, 2)?.slice(0, TOOL_OUTPUT_CAP)}
            </pre>
          </details>
        )}

        {/* Media Preview Player if generated media path is present */}
        {(() => {
          const mediaSrc =
            ev.media_path ||
            (ev.data as any)?.media_path ||
            (ev.data as any)?.clean_path ||
            (ev.data as any)?.output_path ||
            (ev.data as any)?.video_path
          if (!mediaSrc) return null
          return (
            <div className="p-2.5 border-t border-zinc-800/80">
              <MediaPreviewCard src={mediaSrc} title={toolLabel(ev)} />
            </div>
          )
        })()}
      </div>
    )
  }

  // Last resort: never drop a frame silently.
  return (
    <div className="mt-2 rounded-md border px-2.5 py-1.5 text-[11px] font-mono" style={{ borderColor: border, background: bg, color: 'var(--muted)' }}>
      <Wrench size={11} className="inline mr-1" style={{ color: 'var(--accent)' }} />
      {toolLabel(ev)}
      {ev.message && <span> — {ev.message}</span>}
    </div>
  )
}

export default function AgentChatPage() {

  // State
  const activePersona: PersonaType = 'director'
  // When true the studio shows a real cmd.exe PTY (for CLI agents) instead of chat.
  const [showTerminal, setShowTerminal] = useState(false)
  const [showModelMenu, setShowModelMenu] = useState(false)
  // Agent mode routes handleSend through POST /api/opencode/agent/stream (tool
  // loop) instead of plain /chat/stream. Default ON for every persona: the
  // assistant acts on the pipeline through server tools instead of narrating
  // what the user should click. Spending and publishing stay server-gated
  const agentMode = true
  // gemini-3.8-flash is the default because it routes through the configured
  // GEMINI_API_KEY directly to Google and works out of the box. The
  // muse-spark-*-free models are refused by OpenCode's free-tier policy from
  // any client other than OpenCode itself (FreeTierError), so defaulting to
  // one made every first message fail.
  const [selectedModel, setSelectedModel] = useState<string>('gemini-3.8-flash')
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>('xhigh')
  // The catalogue is owned by the agent (/api/opencode/models). Keeping a
  // second copy in the bundle is exactly what drifted out of sync before.
  const [models, setModels] = useState<ModelOption[]>([])
  const [, setCatalogueSource] = useState<'api' | 'builtin' | null>(null)
  const [, setCatalogueError] = useState<string | null>(null)
  const [, setKeyConfigured] = useState<boolean | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          if (parsed.length === 1 && parsed[0]?.id === 'msg-init') {
            return []
          }
          return parsed
        }
      }
    } catch {
      // ignore
    }
    return []
  })

  // The reply currently being written. It grows in place so the answer is
  // readable as it arrives, rather than after the whole generation is buffered.
  // `tools` holds agent-mode tool-activity frames interleaved with the text.
  const [streaming, setStreaming] = useState<{ text: string; reasoning: string; tools: AgentToolEvent[] } | null>(null)
  const [expandedThoughts, setExpandedThoughts] = useState<Record<string, boolean>>({})
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [dispatchStatus, setDispatchStatus] = useState<{ id: string; loading: boolean; error?: string; successProject?: { id: string; name: string } } | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  // Lets the person stop a reply. An agent reply can run several tool rounds,
  // so without this a slow or looping turn cannot be interrupted at all — the
  // only escape was reloading the page.
  const abortRef = useRef<AbortController | null>(null)

  /**
   * Payload of the last turn that ended in an error, for Retry.
   *
   * Set ONLY on error — never on abort (a Stop is deliberate, not something
   * to retry) and cleared on success. Retry re-sends the same
   * payloadMessages/model/effort/mode as a full turn restart through the
   * normal stream path, so the server risk gate still applies and no tool
   * is replayed individually.
   */
  const lastTurnRef = useRef<{
    payloadMessages: { role: 'system' | 'user' | 'assistant'; content: string }[]
    model: string
    effort: ReasoningEffort
    useAgentMode: boolean
    assistantId: string
  } | null>(null)

  // Drawer toggle refs removed with the drawers; focus stays where the user left it.

  // The thread this chat is being saved to. A ref, not state: changing it must
  // not re-render, and the autosave effect must always see the current value.
  const conversationIdRef = useRef<string>(
    (() => {
      try {
        const existing = localStorage.getItem(CONVERSATION_KEY)
        if (existing) return existing
      } catch {
        // ignore
      }
      const fresh = newConversationId()
      try {
        localStorage.setItem(CONVERSATION_KEY, fresh)
      } catch {
        // ignore
      }
      return fresh
    })()
  )
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [showQuickDrawer, setShowQuickDrawer] = useState(false)

  // Save messages
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
    } catch {
      // ignore
    }
  }, [messages])

  /**
   * Auto-save to the server, debounced.
   *
   * localStorage alone meant a cleared browser lost everything and the server
   * conversation store was never used. Debounced because a streaming reply
   * re-renders on every token, and writing each one would hammer the endpoint.
   *
   * A failure is not surfaced as a broken chat — localStorage still has the
   * thread, so this is a best-effort mirror, and `saveError` only reports it.
   */
  useEffect(() => {
    // A lone welcome message is not a conversation worth storing.
    if (messages.length < 2) return

    const timer = window.setTimeout(async () => {
      const firstUser = messages.find(m => m.role === 'user')
      const title =
        (firstUser?.content || 'Untitled').replace(/\s+/g, ' ').trim().slice(0, 80) ||
        'Untitled'
      try {
        await fetchAPI(`/api/agent/conversations/${conversationIdRef.current}`, {
          method: 'PUT',
          body: JSON.stringify({
            messages: messages.map(m => ({
              role: m.role,
              content: m.content,
              timestamp: m.timestamp,
              modelUsed: m.modelUsed,
              // Tool activity is part of what happened; keep it so a restored
              // thread still shows which commands ran.
              ...(m.tools && m.tools.length > 0 ? { tools: m.tools } : {})
            })),
            title
          })
        })
        setSavedAt(Date.now())
        setSaveError(null)
      } catch (err: any) {
        setSaveError(err?.message || String(err))
      }
    }, AUTOSAVE_DELAY_MS)

    return () => window.clearTimeout(timer)
  }, [messages])

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Grow the composer with its content, up to a cap, then scroll inside it.
  // A fixed two-row box hides the start of a long prompt, which matters most
  // for the long directing prompts this studio is used for.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [input])

  // Health check and Continuity Ledger check for FlowKit server
  const [continuityData, setContinuityData] = useState<any>(null)
  // Gemini-style empty state: a fresh thread shows a greeting hero
  const isFresh =
    messages.length === 0 ||
    (messages.length === 1 &&
      (messages[0]?.id === 'msg-init' ||
        (messages[0]?.role === 'assistant' &&
          (messages[0]?.content || '').startsWith('New conversation.'))))
  const dismissCanon = () => {
    try { localStorage.removeItem('flowkit-canon-dismissed') } catch { /* private mode */ }
  }
  void dismissCanon

  useEffect(() => {
    fetchAPI<any>('/api/continuity/ledger')
      .then(data => setContinuityData(data))
      .catch(() => setContinuityData(null))
  }, [])

  // The agent owns both the key and each model's protocol, so this is the only
  // place the model list comes from. The server falls back to its built-in list
  // rather than failing, so a network problem degrades the list, not the page.
  const loadModels = async (refresh = false) => {
    try {
      const catalogue = await fetchOpenCodeModels(refresh)
      // Free models first. The provider refuses paid models on an account with
      // no payment method, so leading with the ones that actually work saves a
      // round trip through an error the person cannot act on.
      const sorted = [...catalogue.models].sort((a, b) => {
        if (a.is_free !== b.is_free) return a.is_free ? -1 : 1
        return a.name.localeCompare(b.name)
      })
      setModels(sorted)
      setCatalogueSource(catalogue.source)
      setCatalogueError(catalogue.error)
      setKeyConfigured(catalogue.key_configured)
      // Reconcile the selection with what is actually offered: keep the current
      // model if it still exists, otherwise take the first listed.
      setSelectedModel(prev => {
        const next = sorted.some(m => m.id === prev)
          ? prev
          : sorted[0]?.id ?? prev
        const info = findModel(sorted, next)
        if (info) setReasoningEffort(info.default_reasoning)
        return next
      })
    } catch (err: any) {
      setCatalogueError(err?.message || String(err))
      setCatalogueSource(null)
    }
  }

  useEffect(() => {
    loadModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const currentPersona = PERSONAS[activePersona]
  const currentModelInfo = findModel(models, selectedModel)
  const reasoningTiers: ReasoningEffort[] = currentModelInfo?.supported_reasoning ?? ['off']

  // Segment models by providers for structured model selection
  const PROVIDER_ORDER = ['NVIDIA NIM', 'Google Gemini', 'Meta', 'OpenAI', 'DeepSeek', 'OpenCode / Community']

  const providerGroups = useMemo(() => {
    const groups: Record<string, ModelOption[]> = {}
    for (const m of models) {
      const p = getModelProvider(m)
      if (!groups[p]) groups[p] = []
      groups[p].push(m)
    }
    const ordered: { provider: string; list: ModelOption[] }[] = []
    for (const p of PROVIDER_ORDER) {
      if (groups[p] && groups[p].length > 0) {
        ordered.push({ provider: p, list: groups[p] })
      }
    }
    for (const [p, list] of Object.entries(groups)) {
      if (!PROVIDER_ORDER.includes(p) && list.length > 0) {
        ordered.push({ provider: p, list })
      }
    }
    return ordered
  }, [models])

  const getProviderDotColor = (provider: string) => {
    switch (provider) {
      case 'NVIDIA NIM':
        return '#76b900'
      case 'Google Gemini':
        return '#3b82f6'
      case 'Meta':
        return '#a855f7'
      case 'OpenAI':
        return '#10b981'
      case 'DeepSeek':
        return '#06b6d4'
      default:
        return '#94a3b8'
    }
  }

  /** Begin a fresh thread. The previous one stays saved on the server. */
  const startNewConversation = () => {
    const fresh = newConversationId()
    conversationIdRef.current = fresh
    try {
      localStorage.setItem(CONVERSATION_KEY, fresh)
    } catch {
      // ignore
    }
    setSavedAt(null)
    setSaveError(null)
    setMessages([])
  }

  const handleSend = async (overridePrompt?: string) => {
    const textToSend = (overridePrompt || input).trim()
    if (!textToSend || loading) return

    const userMessage: ChatMessage = {
      id: `usr-${Date.now()}`,
      role: 'user',
      content: textToSend,
      timestamp: Date.now()
    }

    const nextMessages = [...messages, userMessage]
    setMessages(nextMessages)
    setInput('')
    setLoading(true)

    // Build conversation payload with active system prompt + live ledger continuity
    let activeSystemPrompt = currentPersona.systemPrompt
    if (continuityData?.latest_episode) {
      const ep = continuityData.latest_episode
      activeSystemPrompt += `\n\n[LIVE CONTINUITY LEDGER DATA - CANON LOCKED]:\n` +
        `- Series: "${continuityData.series?.[0]?.title || 'Arthur & Rusty: The Whispering Earth'}"\n` +
        `- Registered Characters: Arthur (elderly farmer), Rusty (golden terrier mix), Dusty Creek Farm\n` +
        `- Most Recent Canon Episode: Episode ${ep.episode_num} ("${ep.title}")\n` +
        `- Episode ${ep.episode_num} Cliffhanger: "${ep.cliffhanger}"\n` +
        `- Episode ${ep.episode_num + 1} Hook Target: "${ep.next_episode_hook}"\n` +
        `- Directing Instruction: DO NOT ask the user to query the database. You ALREADY have this live ledger data directly from the local system! When continuing, pay off the Episode ${ep.episode_num} cliffhanger in Scene 0 (0-3s Hook) of Episode ${ep.episode_num + 1}.`
    }

    const payloadMessages: { role: 'system' | 'user' | 'assistant'; content: string }[] = [
      { role: 'system', content: activeSystemPrompt },
      ...nextMessages.map(m => ({ role: m.role, content: m.content }))
    ]

    const assistantId = `asst-${Date.now()}`
    setStreaming({ text: '', reasoning: '', tools: [] })

    // One controller per turn. Aborting rejects the in-flight read, which the
    // catch below distinguishes from a real failure.
    const controller = new AbortController()
    abortRef.current = controller

    // Handlers run asynchronously, so results are collected on an object rather
    // than in `let` bindings: TypeScript narrows a `let` to its initial value
    // and would not see assignments made inside a callback. `acc` is declared
    // out here so the catch block can still report whatever text did arrive.
    const acc: {
      text: string
      reasoning: string
      usage: StreamUsage | null
      done: StreamDone | null
      tools: AgentToolEvent[]
    } = { text: '', reasoning: '', usage: null, done: null, tools: [] }

    const streamHandlers = {
      onText: (chunk: string) => {
        acc.text += chunk
        setStreaming(prev => (prev ? { ...prev, text: acc.text } : prev))
      },
      onReasoning: (chunk: string) => {
        acc.reasoning += chunk
        setStreaming(prev => (prev ? { ...prev, reasoning: acc.reasoning } : prev))
      },
      onUsage: (u: StreamUsage) => {
        acc.usage = u
      },
      onDone: (d: StreamDone) => {
        acc.done = d
      },
      onTool: (ev: AgentToolEvent) => {
        acc.tools.push(ev)
        setStreaming(prev => (prev ? { ...prev, tools: [...acc.tools] } : prev))
      }
    }

    try {
      if (agentMode) {
        // Agent-mode path: the server tool loop interleaves extra `tool`
        // frames alongside the usual text/reasoning/done frames.
        try {
          await streamAgentChat(
            payloadMessages,
            { model: selectedModel, reasoningEffort: reasoningEffort },
            streamHandlers,
            controller.signal
          )
        } catch (agentErr: any) {
          // An abort is the person stopping, not a missing endpoint.
          if (controller.signal.aborted) throw agentErr
          if (!String(agentErr?.message || '').includes('AGENT_STREAM_NOT_FOUND')) throw agentErr
          // The backend on this build has no agent loop yet. Fall back to the
          // plain stream rather than showing a dead toggle, and say so in the
          // feed so a direct answer is never mistaken for tool-backed work.
          const notice: AgentToolEvent = {
            type: 'tool',
            tool: 'agent_notice',
            title: 'Agent loop unavailable on this agent build — answered directly.',
            message: 'POST /api/opencode/agent/stream returned 404, so this reply used /chat/stream with no tool access.'
          }
          acc.tools.push(notice)
          setStreaming(prev => (prev ? { ...prev, tools: [...acc.tools] } : prev))
          await streamOpenCodeChat(
            payloadMessages,
            { model: selectedModel, reasoningEffort: reasoningEffort },
            streamHandlers,
            controller.signal
          )
        }
      } else {
        // Plain path, byte-for-byte the behaviour it always had.
        await streamOpenCodeChat(
          payloadMessages,
          { model: selectedModel, reasoningEffort: reasoningEffort },
          streamHandlers,
          controller.signal
        )
      }

      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: acc.text,
        timestamp: Date.now(),
        reasoningTokens: acc.usage?.reasoningTokens ?? 0,
        thoughtTrace: acc.reasoning || undefined,
        latencyMs: acc.done?.latencyMs ?? 0,
        modelUsed: acc.done?.model ?? selectedModel,
        effortUsed: acc.done?.reasoningEffort ?? reasoningEffort,
        ...(acc.tools.length > 0 ? { tools: [...acc.tools] } : {})
      }

      setMessages(prev => [...prev, assistantMessage])
      // A finished turn has nothing to retry.
      lastTurnRef.current = null
      if (acc.reasoning) {
        setExpandedThoughts(prev => ({ ...prev, [assistantId]: true }))
      }
    } catch (err: any) {
      // Whatever arrived is kept. A partial reply plus an explicit note is more
      // honest than discarding the text, and it must not read as a finished
      // answer.
      const partial = acc.text ? `${acc.text}\n\n---\n\n` : ''

      // A stop is not a failure. Reporting "the reply did not finish" for a
      // deliberate stop would send the person hunting for a bug that is not
      // there — and the partial text is usually exactly what they wanted.
      if (controller.signal.aborted) {
        // A Stop is deliberate — there is nothing to retry, so the slot
        // stays empty and no Retry button appears on the Stopped card.
        lastTurnRef.current = null
        setMessages(prev => [
          ...prev,
          {
            id: `${assistantId}-stopped`,
            role: 'assistant',
            content: `${partial}⏹️ **Stopped.**${acc.tools.length > 0 ? ' Tool activity above is what ran before you stopped it.' : ''}`,
            timestamp: Date.now(),
            ...(acc.tools.length > 0 ? { tools: [...acc.tools] } : {})
          },
        ])
        return
      }

      const raw = err?.message || String(err)
      // Provider failures arrive as a JSON envelope. Translating the ones we
      // recognise stops a billing problem from looking like a broken app, and
      // leaves anything unrecognised displayed verbatim rather than guessed at.
      const explained = explainUpstreamError(raw)
      const detail = explained ? `**${explained.title}.** ${explained.hint}` : raw
      // Keep the failed turn's payload so Retry can re-send it verbatim.
      lastTurnRef.current = {
        payloadMessages,
        model: selectedModel,
        effort: reasoningEffort,
        useAgentMode: agentMode,
        assistantId,
      }
      setMessages(prev => [
        ...prev,
        {
          id: `${assistantId}-err`,
          role: 'assistant',
          content: `${partial}⚠️ **The reply did not finish.** ${detail}`,
          timestamp: Date.now(),
        },
      ])
    } finally {
      abortRef.current = null
      setStreaming(null)
      setLoading(false)
    }
  }

  /**
   * Stop the in-flight reply.
   *
   * Aborting rejects the pending read, so the partial text already rendered is
   * kept and the turn is closed out as "stopped" rather than as an error.
   * Server-side work already dispatched (a tool call in flight) finishes; this
   * stops the conversation, not the agent's current operation.
   */
  const handleStop = () => {
    abortRef.current?.abort()
  }

  /**
   * Re-send the last failed turn verbatim.
   *
   * Full turn restart: the stored payloadMessages go back through the same
   * stream handlers and the same abort semantics as a fresh send (a Retry
   * can itself be Stopped, and Stop-vs-error copy is preserved). Tools are
   * NOT replayed one by one — the server runs the turn again from the
   * messages, so the risk gate sees every call exactly as before.
   */
  const handleRetry = async () => {
    const turn = lastTurnRef.current
    if (!turn || loading) return
    // Drop the "-err" card this retry replaces, so the feed does not stack
    // one error card per attempt.
    setMessages(prev => prev.filter(m => m.id !== `${turn.assistantId}-err`))
    lastTurnRef.current = null
    setLoading(true)
    const assistantId = turn.assistantId
    setStreaming({ text: '', reasoning: '', tools: [] })
    const controller = new AbortController()
    abortRef.current = controller
    const acc: {
      text: string
      reasoning: string
      usage: StreamUsage | null
      done: StreamDone | null
      tools: AgentToolEvent[]
    } = { text: '', reasoning: '', usage: null, done: null, tools: [] }
    const streamHandlers = {
      onText: (chunk: string) => {
        acc.text += chunk
        setStreaming(prev => (prev ? { ...prev, text: acc.text } : prev))
      },
      onReasoning: (chunk: string) => {
        acc.reasoning += chunk
        setStreaming(prev => (prev ? { ...prev, reasoning: acc.reasoning } : prev))
      },
      onUsage: (u: StreamUsage) => {
        acc.usage = u
      },
      onDone: (d: StreamDone) => {
        acc.done = d
      },
      onTool: (ev: AgentToolEvent) => {
        acc.tools.push(ev)
        setStreaming(prev => (prev ? { ...prev, tools: [...acc.tools] } : prev))
      }
    }
    try {
      if (turn.useAgentMode) {
        try {
          await streamAgentChat(
            turn.payloadMessages,
            { model: turn.model, reasoningEffort: turn.effort },
            streamHandlers,
            controller.signal
          )
        } catch (agentErr: any) {
          if (controller.signal.aborted) throw agentErr
          if (!String(agentErr?.message || '').includes('AGENT_STREAM_NOT_FOUND')) throw agentErr
          const notice: AgentToolEvent = {
            type: 'tool',
            tool: 'agent_notice',
            title: 'Agent loop unavailable on this agent build — answered directly.',
            message: 'POST /api/opencode/agent/stream returned 404, so this reply used /chat/stream with no tool access.'
          }
          acc.tools.push(notice)
          setStreaming(prev => (prev ? { ...prev, tools: [...acc.tools] } : prev))
          await streamOpenCodeChat(
            turn.payloadMessages,
            { model: turn.model, reasoningEffort: turn.effort },
            streamHandlers,
            controller.signal
          )
        }
      } else {
        await streamOpenCodeChat(
          turn.payloadMessages,
          { model: turn.model, reasoningEffort: turn.effort },
          streamHandlers,
          controller.signal
        )
      }
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: acc.text,
        timestamp: Date.now(),
        reasoningTokens: acc.usage?.reasoningTokens ?? 0,
        thoughtTrace: acc.reasoning || undefined,
        latencyMs: acc.done?.latencyMs ?? 0,
        modelUsed: acc.done?.model ?? turn.model,
        effortUsed: acc.done?.reasoningEffort ?? turn.effort,
        ...(acc.tools.length > 0 ? { tools: [...acc.tools] } : {})
      }
      setMessages(prev => [...prev, assistantMessage])
      if (acc.reasoning) {
        setExpandedThoughts(prev => ({ ...prev, [assistantId]: true }))
      }
    } catch (err: any) {
      const partial = acc.text ? `${acc.text}\n\n---\n\n` : ''
      if (controller.signal.aborted) {
        setMessages(prev => [
          ...prev,
          {
            id: `${assistantId}-stopped`,
            role: 'assistant',
            content: `${partial}⏹️ **Stopped.**${acc.tools.length > 0 ? ' Tool activity above is what ran before you stopped it.' : ''}`,
            timestamp: Date.now(),
            ...(acc.tools.length > 0 ? { tools: [...acc.tools] } : {})
          },
        ])
        return
      }
      const raw = err?.message || String(err)
      const explained = explainUpstreamError(raw)
      const detail = explained ? `**${explained.title}.** ${explained.hint}` : raw
      // Still failing: keep the payload so Retry stays available.
      lastTurnRef.current = turn
      setMessages(prev => [
        ...prev,
        {
          id: `${assistantId}-err`,
          role: 'assistant',
          content: `${partial}⚠️ **The reply did not finish.** ${detail}`,
          timestamp: Date.now(),
        },
      ])
    } finally {
      abortRef.current = null
      setStreaming(null)
      setLoading(false)
    }
  }

  /**
   * Approve a gated or refused tool call directly via /api/operations/run.
   *
   * Executes the operation through the backend registry with confirm: true,
   * displays the outcome and generated media inline, and allows the agent to chain
   * subsequent tasks.
   */
  const handleApproveTool = async (ev: AgentToolEvent) => {
    if (loading) return
    try {
      setLoading(true)
      const opName = ev.tool
      const args = (ev.args || {}) as Record<string, any>
      
      const res = await fetchAPI<any>('/api/operations/run', {
        method: 'POST',
        body: JSON.stringify({ name: opName, args, confirm: true }),
      })

      const success = res?.success
      const detail = res?.result ? JSON.stringify(res.result, null, 2) : res?.error || 'Completed'
      const media =
        res?.result?.media_path ||
        res?.result?.clean_path ||
        res?.result?.output_path ||
        res?.result?.video_path

      const approvalMessage: ChatMessage = {
        role: 'assistant',
        content: `**[Approved & Executed]** \`${opName}\`\n\n${
          success ? '✅ Operation completed successfully.' : '❌ Operation failed.'
        }\n\`\`\`json\n${detail}\n\`\`\``,
        timestamp: Date.now(),
        tools: [
          {
            type: 'tool',
            tool: opName,
            status: success ? 'done' : 'error',
            risk: ev.risk,
            data: res?.result,
            media_path: media,
            message: res?.error,
          },
        ],
      }
      setMessages(prev => [...prev, approvalMessage])

      // If the operation succeeded, let the agent know so it can chain the next action
      if (success) {
        void handleSend(
          `[System Notification]: Operation "${opName}" was approved by the user and finished successfully with output:\n${detail.slice(
            0,
            1200
          )}\nPlease continue with the next step in the pipeline.`
        )
      }
    } catch (err: any) {
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `❌ Failed to execute approved operation \`${ev.tool}\`: ${err?.message || String(err)}`,
          timestamp: Date.now(),
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  // Detect and extract JSON manifest from response for 1-click FlowKit project creation
  const extractManifest = (content: string): any | null => {
    const jsonMatch = content.match(/```(?:json)?\s*(\{[\s\S]*?\})\s*```/)
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[1])
        if (parsed.scenes && Array.isArray(parsed.scenes)) return parsed
      } catch {
        // not valid json
      }
    }
    return null
  }

  // 1-Click Dispatch to FlowKit Pipeline
  const handleDispatchToFlowKit = async (msgId: string, manifest: any) => {
    setDispatchStatus({ id: msgId, loading: true })
    try {
      // 1. Create Project
      const projectName = manifest.project_name || `Episode - ${new Date().toLocaleDateString()}`
      const projectDesc = manifest.description || 'Auto-generated by OpenCode Agent Studio'
      
      const projectRes = await fetchAPI<any>('/api/projects', {
        method: 'POST',
        body: JSON.stringify({
          name: projectName,
          description: projectDesc,
          language: 'en'
        })
      })

      // 2. Create Video Entry
      const videoRes = await fetchAPI<any>('/api/videos', {
        method: 'POST',
        body: JSON.stringify({
          project_id: projectRes.id,
          title: projectName,
          description: projectDesc
        })
      })

      // 3. Create Scenes
      const scenes = manifest.scenes || []
      for (let i = 0; i < scenes.length; i++) {
        const sc = scenes[i]
        await fetchAPI<any>('/api/scenes', {
          method: 'POST',
          body: JSON.stringify({
            video_id: videoRes.id,
            display_order: i,
            prompt: sc.narrator_text || sc.image_prompt || `Scene ${i + 1}`,
            image_prompt: sc.image_prompt || sc.prompt,
            video_prompt: sc.video_prompt || null,
            character_names: JSON.stringify(sc.characters || ['Arthur', 'Rusty']),
            narrator_text: sc.narrator_text || null,
            duration: sc.duration || 6.0
          })
        })
      }

      setDispatchStatus({
        id: msgId,
        loading: false,
        successProject: { id: projectRes.id, name: projectName }
      })
    } catch (err: any) {
      setDispatchStatus({
        id: msgId,
        loading: false,
        error: `Failed to dispatch: ${err.message || String(err)}`
      })
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden select-none" style={{ background: 'var(--bg)', color: 'var(--text)' }}>
      {/* Gemini Single Top Header */}
      <header
        className="flex items-center justify-between px-6 py-3.5 flex-shrink-0 border-b select-none z-20"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        {/* Left: Clean space matching Gemini top bar */}
        <div className="flex items-center gap-2" />

        {/* Right: Terminal + New Chat + User Profile */}
        <div className="flex items-center gap-3">

          {/* Terminal Toggle Button */}
          <button
            onClick={() => setShowTerminal(prev => !prev)}
            aria-pressed={showTerminal}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
              showTerminal
                ? 'bg-emerald-600 text-white border-emerald-500 shadow-sm'
                : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)] border-white/10 hover:bg-white/5'
            }`}
            title="Toggle cmd.exe PTY CLI terminal"
          >
            <Terminal size={13} />
            <span>Terminal</span>
          </button>

          {/* New Chat Button */}
          <button
            onClick={startNewConversation}
            className="p-1.5 rounded-full border text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors"
            style={{ borderColor: 'var(--border)', background: 'var(--card)' }}
            title="New conversation"
          >
            <Plus size={15} />
          </button>

          {/* Abinash Profile Avatar */}
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 via-indigo-500 to-amber-300 flex items-center justify-center text-xs font-bold text-slate-950 shadow flex-shrink-0">
            A
          </div>
        </div>
      </header>

      {!showTerminal && (saveError || savedAt) && (
        <p role="status" className="px-4 py-1 text-xs text-[var(--muted)]">
          {saveError ? `Server save failed: ${saveError}. This chat remains in this browser.` : 'Conversation saved'}
        </p>
      )}

      {showTerminal && (
        <div className="flex-1 min-h-0">
          <TerminalPane />
        </div>
      )}

      {/* Gemini-style empty state: greeting hero + 4 suggestion cards */}
      {isFresh && !showTerminal && (
        <div className="flex-1 flex flex-col items-center justify-center max-w-3xl mx-auto px-4 w-full py-8 text-center animate-in fade-in duration-300 overflow-y-auto">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center text-white mb-4 shadow-lg">
            <Sparkles size={24} />
          </div>
          <h1 className="text-4xl sm:text-5xl md:text-6xl font-normal tracking-tight">
            <span className="bg-gradient-to-r from-[#4285f4] via-[#9b72cf] to-[#d96570] bg-clip-text text-transparent font-medium">
              Hello, Abinash
            </span>
          </h1>
          <p className="text-lg sm:text-xl font-light mt-3 tracking-wide text-[var(--muted)]">
            How can I help you create your next Short today?
          </p>

          {/* 4 Gemini Quick Action Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 mt-8 w-full text-left">
            <button
              onClick={() => {
                setInput('Direct Episode 2 of Arthur & Rusty: "The Whispering Well". Arthur and Rusty investigate ancient glowing blue symbols pulsing deep inside the dry farm well. Keep all scenes strictly under 10s with high-retention 5-beat pacing.')
                textareaRef.current?.focus()
              }}
              className="p-4 rounded-2xl border transition-all duration-200 group flex flex-col justify-between h-32 hover:-translate-y-0.5 cursor-pointer shadow-sm"
              style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
            >
              <div className="flex items-center justify-between w-full">
                <span className="text-xs font-semibold text-[var(--foreground)] group-hover:text-blue-400 transition-colors">
                  Direct an Episode
                </span>
                <div className="w-8 h-8 rounded-full bg-blue-500/10 text-blue-400 flex items-center justify-center group-hover:bg-blue-500 group-hover:text-[var(--foreground)] transition-all">
                  <Clapperboard size={15} />
                </div>
              </div>
              <p className="text-xs text-[var(--muted-foreground)] line-clamp-2 leading-relaxed">
                Write a 5-phase retention Short with Arthur & Rusty under 10s pacing limit
              </p>
            </button>

            <button
              onClick={() => {
                setInput('Queue a vertical 9:16 still image in Google Flow: "Arthur holding a glowing brass lantern deep inside the stone well, cinematic volumetric lighting, 8k render".')
                textareaRef.current?.focus()
              }}
              className="p-4 rounded-2xl border transition-all duration-200 group flex flex-col justify-between h-32 hover:-translate-y-0.5 cursor-pointer shadow-sm"
              style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
            >
              <div className="flex items-center justify-between w-full">
                <span className="text-xs font-semibold text-[var(--foreground)] group-hover:text-amber-400 transition-colors">
                  Generate 9:16 Stills
                </span>
                <div className="w-8 h-8 rounded-full bg-amber-500/10 text-amber-400 flex items-center justify-center group-hover:bg-amber-500 group-hover:text-[var(--foreground)] transition-all">
                  <Sparkles size={15} />
                </div>
              </div>
              <p className="text-xs text-[var(--muted-foreground)] line-clamp-2 leading-relaxed">
                Create character visual assets with S2P prompt consistency conditioning
              </p>
            </button>

            <button
              onClick={() => {
                setInput('Assemble the latest episode: combine narration audio from Edge TTS, generated visual clips, and timed subtitles into a 9:16 vertical Short.')
                textareaRef.current?.focus()
              }}
              className="p-4 rounded-2xl border transition-all duration-200 group flex flex-col justify-between h-32 hover:-translate-y-0.5 cursor-pointer shadow-sm"
              style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
            >
              <div className="flex items-center justify-between w-full">
                <span className="text-xs font-semibold text-[var(--foreground)] group-hover:text-emerald-400 transition-colors">
                  Assemble Short
                </span>
                <div className="w-8 h-8 rounded-full bg-emerald-500/10 text-emerald-400 flex items-center justify-center group-hover:bg-emerald-500 group-hover:text-[var(--foreground)] transition-all">
                  <Zap size={15} />
                </div>
              </div>
              <p className="text-xs text-[var(--muted-foreground)] line-clamp-2 leading-relaxed">
                Merge narration, keyframe visuals, audio mix, and animated captions
              </p>
            </button>

            <button
              onClick={() => {
                setInput('Scrub the AI watermark from the latest render using the veo_bottom_right delogo profile.')
                textareaRef.current?.focus()
              }}
              className="p-4 rounded-2xl border transition-all duration-200 group flex flex-col justify-between h-32 hover:-translate-y-0.5 cursor-pointer shadow-sm"
              style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
            >
              <div className="flex items-center justify-between w-full">
                <span className="text-xs font-semibold text-[var(--foreground)] group-hover:text-purple-400 transition-colors">
                  Scrub Watermark
                </span>
                <div className="w-8 h-8 rounded-full bg-purple-500/10 text-purple-400 flex items-center justify-center group-hover:bg-purple-500 group-hover:text-[var(--foreground)] transition-all">
                  <Wrench size={15} />
                </div>
              </div>
              <p className="text-xs text-[var(--muted-foreground)] line-clamp-2 leading-relaxed">
                Detect and remove video watermark logos with precise delogo remuxing
              </p>
            </button>
          </div>
        </div>
      )}

      {/* Main Conversation Feed */}
      <div
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Conversation messages"
        className={`flex-1 overflow-y-auto px-4 sm:px-6 py-6 flex flex-col gap-6 w-full max-w-4xl mx-auto${
          showTerminal || isFresh ? ' hidden' : ''
        }`}
      >
        {messages.map((msg, idx) => {
          const isUser = msg.role === 'user'
          const manifest = !isUser ? extractManifest(msg.content) : null
          const isThoughtExpanded = !!expandedThoughts[msg.id || String(idx)]
          const dispatch = dispatchStatus?.id === msg.id ? dispatchStatus : null

          return (
            <div
              key={msg.id || idx}
              className={isUser ? 'ml-auto max-w-[80%] flex flex-col items-end gap-1' : 'mr-auto w-full flex items-start gap-3.5 group'}
            >
              {isUser ? (
                <>
                  <div className="bg-[#282a2c] text-[#e3e3e3] rounded-[24px] px-5 py-3 text-[14px] leading-relaxed shadow-sm font-sans whitespace-pre-wrap break-words border border-white/5">
                    {msg.content}
                  </div>
                  <span className="text-[10px] text-[var(--muted-foreground)] px-2 font-sans">
                    {new Date(msg.timestamp || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </>
              ) : (
                <>
                  {/* Gemini Sparkle Avatar */}
                  <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center text-white flex-shrink-0 shadow mt-0.5">
                    <Sparkles size={16} />
                  </div>

                  <div className="flex-1 min-w-0 flex flex-col gap-2">
                    {/* Header Info */}
                    <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)] font-sans">
                      <span className="font-semibold text-white">Gemini</span>
                      <span>·</span>
                      <span>{msg.modelUsed || selectedModel}</span>
                      {msg.latencyMs ? <span>· {(msg.latencyMs / 1000).toFixed(1)}s</span> : null}
                      <span>· {new Date(msg.timestamp || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>

                    {/* Expandable Reasoning / Thought Trace */}
                    {(msg.thoughtTrace || msg.reasoningTokens) && (
                      <div className="rounded-xl border overflow-hidden" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                        <button
                          onClick={() =>
                            setExpandedThoughts(prev => ({
                              ...prev,
                              [msg.id || String(idx)]: !isThoughtExpanded
                            }))
                          }
                          aria-expanded={isThoughtExpanded}
                          className="w-full flex items-center justify-between px-3.5 py-1.5 text-xs text-amber-300/90 font-sans hover:bg-white/5 transition-colors"
                        >
                          <span className="flex items-center gap-2">
                            <BrainCircuit size={13} className="text-amber-400" />
                            <span>Thought for {msg.latencyMs ? (msg.latencyMs / 1000).toFixed(1) : 'a few'} seconds</span>
                            <span className="text-[11px] text-[var(--muted-foreground)]">
                              ({msg.reasoningTokens?.toLocaleString() || 0} tokens evaluated)
                            </span>
                          </span>
                          {isThoughtExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                        </button>

                        {isThoughtExpanded && (
                          <div className="px-4 py-3 border-t text-xs leading-relaxed text-[var(--muted)] max-h-48 overflow-y-auto whitespace-pre-wrap font-mono" style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}>
                            {msg.thoughtTrace || 'The provider evaluated reasoning tokens without streaming raw trace text.'}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Tool Activity Chips */}
                    {msg.tools && msg.tools.length > 0 && (
                      <div className="flex flex-col gap-1.5 my-1">
                        {msg.tools.map((ev, toolIdx) => (
                          <ToolActivity
                            key={`${msg.id || idx}-tool-${toolIdx}`}
                            ev={ev}
                            copyKey={`${msg.id || idx}-tool-${toolIdx}`}
                            copiedId={copiedId}
                            onCopy={handleCopy}
                            onApprove={loading ? undefined : handleApproveTool}
                          />
                        ))}
                      </div>
                    )}

                    {/* Primary Markdown Content */}
                    <div className="text-[14px] leading-relaxed text-[var(--foreground)] font-sans">
                      <Markdown text={msg.content} />
                    </div>

                    {/* Smart Action: Manifest Dispatch */}
                    {manifest && (
                      <div
                        className="mt-2 p-4 rounded-2xl border flex flex-col gap-2.5"
                        style={{ background: 'rgba(34, 197, 94, 0.08)', borderColor: 'rgba(34, 197, 94, 0.3)' }}
                      >
                        <div className="flex items-center justify-between">
                          <span className="flex items-center gap-2 font-semibold text-emerald-400 text-xs font-sans">
                            <Clapperboard size={14} />
                            Ready-to-Render Episode Manifest ({manifest.scenes?.length || 0} scenes ≤ 10s)
                          </span>
                          <Button
                            size="sm"
                            disabled={!!dispatch?.loading}
                            onClick={() => handleDispatchToFlowKit(msg.id!, manifest)}
                            className="bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] h-7 px-3.5 rounded-full flex items-center gap-1.5 shadow"
                          >
                            {dispatch?.loading ? (
                              <>
                                <span className="w-2.5 h-2.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                Dispatching...
                              </>
                            ) : (
                              <>
                                <Play size={11} /> Dispatch to FlowKit Pipeline
                              </>
                            )}
                          </Button>
                        </div>

                        {dispatch?.successProject && (
                          <div role="status" className="flex items-center justify-between text-xs text-emerald-300 font-sans pt-1">
                            <span>✅ Project Created: <strong>{dispatch.successProject.name}</strong></span>
                            <Link
                              to={`/projects/${dispatch.successProject.id}`}
                              className="flex items-center gap-1 text-emerald-400 underline hover:opacity-80"
                            >
                              View in Projects <ArrowUpRight size={12} />
                            </Link>
                          </div>
                        )}
                        {dispatch?.error && (
                          <div role="status" className="text-xs text-red-400 font-sans pt-1 flex items-center gap-1">
                            <AlertCircle size={12} /> {dispatch.error}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Message Actions: Copy, Retry */}
                    <div className="flex items-center gap-3 mt-1 text-xs text-[var(--muted-foreground)]">
                      {!isUser && msg.id?.endsWith('-err') && (
                        <button
                          onClick={handleRetry}
                          disabled={loading}
                          aria-label="Retry failed reply"
                          className="flex items-center gap-1 hover:text-[var(--foreground)] transition-colors"
                        >
                          <RotateCcw size={11} /> Retry
                        </button>
                      )}
                      <button
                        onClick={() => handleCopy(msg.content, msg.id || String(idx))}
                        aria-label="Copy message"
                        className="flex items-center gap-1 hover:text-[var(--foreground)] transition-colors"
                      >
                        {copiedId === (msg.id || String(idx)) ? (
                          <>
                            <Check size={11} className="text-emerald-400" /> Copied
                          </>
                        ) : (
                          <>
                            <Copy size={11} /> Copy
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          )
        })}

        {/* Live Streaming Reply */}
        {streaming && (streaming.text || streaming.reasoning || streaming.tools.length > 0) && (
          <div role="status" aria-label="Assistant reply in progress" className="mr-auto w-full flex items-start gap-3.5">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center text-white flex-shrink-0 shadow mt-0.5 animate-pulse">
              <Sparkles size={16} />
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-2">
              <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)] font-sans">
                <span className="font-semibold text-white">Gemini</span>
                <span>·</span>
                <span className="text-blue-400 font-medium">Generating...</span>
              </div>

              {streaming.tools.length > 0 && (
                <div className="flex flex-col gap-1.5 my-1">
                  {streaming.tools.map((ev, toolIdx) => (
                    <ToolActivity
                      key={`live-tool-${toolIdx}`}
                      ev={ev}
                      copyKey={`live-tool-${toolIdx}`}
                      copiedId={copiedId}
                      onCopy={handleCopy}
                    />
                  ))}
                </div>
              )}

              {streaming.reasoning && (
                <div
                  className="rounded-xl border px-3.5 py-2 text-xs font-mono whitespace-pre-wrap max-h-40 overflow-y-auto"
                  style={{ borderColor: 'rgba(245, 158, 11, 0.3)', background: 'var(--card)', color: 'var(--text)' }}
                >
                  {streaming.reasoning}
                </div>
              )}

              <div className="text-[14px] leading-relaxed text-[var(--foreground)] font-sans">
                <Markdown text={streaming.text} />
                <span
                  className="inline-block w-1.5 h-4 align-text-bottom ml-0.5 animate-pulse"
                  style={{ background: 'var(--accent)' }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Thinking Indicator before first token */}
        {loading && !streaming?.text && !(streaming?.tools?.length) && (
          <div role="status" aria-label="Assistant is thinking" className="mr-auto flex items-center gap-3 py-2 px-1">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center text-white flex-shrink-0 shadow">
              <Sparkles size={16} className="animate-spin" />
            </div>
            <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)] font-sans">
              <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping" />
              <span>Thinking ({selectedModel.split('-')[0]} · {reasoningEffort})...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Floating Gemini Composer Capsule */}
      <div className={`w-full max-w-4xl mx-auto px-4 pb-4 pt-1 flex-shrink-0 select-none${showTerminal ? ' hidden' : ''}`}>
        {/* Quick Tools Drawer (opened by +) */}
        {showQuickDrawer && (
          <div
            className="p-3.5 rounded-2xl border flex flex-col gap-2.5 mb-2.5 shadow-2xl animate-in fade-in slide-in-from-bottom-2 duration-150"
            style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-blue-400 flex items-center gap-1.5 font-sans">
                <Sparkles size={14} /> Quick Pipeline Tools
              </span>
              <span className="text-[11px] text-[var(--muted-foreground)] font-sans">Click to insert prompt</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setInput('Direct Episode 2 of Arthur & Rusty: "The Whispering Well". Keep scenes strictly under 10s with high-retention 5-beat pacing.')
                  setShowQuickDrawer(false)
                  textareaRef.current?.focus()
                }}
                className="text-left p-2.5 rounded-xl border text-xs text-[var(--foreground)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors flex items-center gap-2 font-sans"
                style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
              >
                <Clapperboard size={15} className="text-blue-400 flex-shrink-0" />
                <span className="truncate">Direct Episode 2 (Arthur & Rusty)</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setInput('Queue a vertical 9:16 still image in Google Flow: "Arthur holding a glowing brass lantern deep inside the stone well, cinematic volumetric lighting".')
                  setShowQuickDrawer(false)
                  textareaRef.current?.focus()
                }}
                className="text-left p-2.5 rounded-xl border text-xs text-[var(--foreground)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors flex items-center gap-2 font-sans"
                style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
              >
                <Sparkles size={15} className="text-amber-400 flex-shrink-0" />
                <span className="truncate">Generate Google Flow Still</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setInput('Check the current request queue status and reference image conditioning for farmer_and_rusty.')
                  setShowQuickDrawer(false)
                  textareaRef.current?.focus()
                }}
                className="text-left p-2.5 rounded-xl border text-xs text-[var(--foreground)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors flex items-center gap-2 font-sans"
                style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
              >
                <Database size={15} className="text-emerald-400 flex-shrink-0" />
                <span className="truncate">Check Queue & Conditioning</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setInput('Scrub the AI watermark from storage/output/farmer_and_rusty_ep1.mp4 using the veo_bottom_right delogo profile.')
                  setShowQuickDrawer(false)
                  textareaRef.current?.focus()
                }}
                className="text-left p-2.5 rounded-xl border text-xs text-[var(--foreground)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors flex items-center gap-2 font-sans"
                style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
              >
                <Wrench size={15} className="text-purple-400 flex-shrink-0" />
                <span className="truncate">Scrub Video Watermark</span>
              </button>
            </div>
          </div>
        )}

        {/* The Capsule */}
        <div
          className="rounded-[28px] border shadow-2xl p-3.5 flex flex-col gap-2 focus-within:border-[#8ab4f8] transition-all duration-200"
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
        >
          {/* Input Textarea */}
          <textarea
            ref={textareaRef}
            id="chat-composer"
            aria-label="Prompt Gemini AutoShorts"
            rows={1}
            value={input}
            disabled={loading}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder="Ask Gemini or direct the pipeline..."
            className="w-full bg-transparent border-0 outline-none text-[14px] resize-none placeholder:text-[var(--muted-foreground)] text-[var(--foreground)] font-sans px-2 py-1 max-h-48 leading-relaxed"
          />

          {/* Capsule Bottom Row */}
          <div className="flex items-center justify-between gap-2 px-1">
            {/* Left Controls */}
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setShowQuickDrawer(prev => !prev)}
                title={showQuickDrawer ? 'Close tools' : 'Open quick tools (+)'}
                className={`w-8 h-8 rounded-full border flex items-center justify-center transition-all ${
                  showQuickDrawer
                    ? 'bg-blue-600 text-white border-blue-500 shadow-sm'
                    : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)] border-white/10 hover:bg-white/5'
                }`}
              >
                <Plus size={16} />
              </button>

              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowModelMenu(prev => !prev)}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-white/5 border border-white/10 transition-colors"
                  title="Change model / reasoning"
                >
                  <span className="max-w-[150px] truncate">
                    {currentModelInfo ? currentModelInfo.name.replace(/\s*\(.*?\)/, '') : selectedModel.split('-')[0]}
                  </span>
                  <span className="text-[10px] text-blue-400">({reasoningEffort})</span>
                  <ChevronDown size={11} />
                </button>

                {showModelMenu && (
                  <div
                    className="absolute bottom-full left-0 mb-2 w-84 p-3 rounded-2xl border shadow-2xl z-50 animate-in fade-in slide-in-from-bottom-2 duration-150"
                    style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
                  >
                    <div className="flex items-center justify-between text-[11px] font-semibold text-[var(--muted-foreground)] uppercase tracking-wider mb-2 px-1">
                      <span>Intelligence Models</span>
                      <span className="text-[10px] text-gray-500 font-normal">{models.length} available</span>
                    </div>

                    <div className="flex flex-col gap-2.5 max-h-72 overflow-y-auto pr-1">
                      {providerGroups.map(({ provider, list }) => (
                        <div key={provider} className="rounded-xl bg-white/[0.02] border border-white/5 p-1.5">
                          <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] font-bold text-gray-300 uppercase tracking-wider mb-1">
                            <span
                              className="w-1.5 h-1.5 rounded-full"
                              style={{ backgroundColor: getProviderDotColor(provider) }}
                            />
                            <span>{provider}</span>
                            <span className="text-[9px] text-gray-500 font-mono ml-auto">
                              {list.length} {list.length === 1 ? 'model' : 'models'}
                            </span>
                          </div>
                          <div className="flex flex-col gap-0.5">
                            {list.map(m => (
                              <button
                                key={m.id}
                                onClick={() => {
                                  setSelectedModel(m.id)
                                  const info = findModel(models, m.id)
                                  if (info) setReasoningEffort(info.default_reasoning)
                                  setShowModelMenu(false)
                                }}
                                className={`text-left px-2.5 py-1.5 rounded-lg text-xs flex items-center justify-between transition-colors ${
                                  selectedModel === m.id
                                    ? 'bg-blue-600/20 text-blue-400 font-semibold border border-blue-500/30'
                                    : 'text-[var(--foreground)] hover:bg-white/5'
                                }`}
                              >
                                <span className="truncate pr-2">{m.name}</span>
                                <div className="flex items-center gap-1 shrink-0">
                                  {m.is_free && (
                                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono">
                                      Free
                                    </span>
                                  )}
                                </div>
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="mt-3 pt-3 border-t flex flex-col gap-1.5" style={{ borderColor: 'var(--border)' }}>
                      <div className="text-[11px] font-semibold text-[var(--muted-foreground)] uppercase tracking-wider">
                        Reasoning Effort
                      </div>
                      <div className="flex rounded-lg p-0.5 border" style={{ background: 'var(--bg)', borderColor: 'var(--border)' }}>
                        {reasoningTiers.map(tier => (
                          <button
                            key={tier}
                            onClick={() => {
                              setReasoningEffort(tier)
                            }}
                            className={`flex-1 py-1 text-center text-[11px] rounded-md transition-all ${
                              reasoningEffort === tier
                                ? 'bg-blue-600 text-white font-medium shadow-sm'
                                : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
                            }`}
                          >
                            {tier}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Right Controls: Mic + Send / Stop */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  if (!input) setInput('Direct Episode 2 of Arthur & Rusty with 5-scene retention pacing.')
                  textareaRef.current?.focus()
                }}
                className="w-8 h-8 rounded-full border border-white/10 hover:bg-white/5 text-[var(--muted-foreground)] hover:text-[var(--foreground)] flex items-center justify-center transition-colors"
                title="Voice prompt"
              >
                <Mic size={15} />
              </button>

              {loading ? (
                <button
                  type="button"
                  onClick={handleStop}
                  className="w-8 h-8 rounded-full bg-red-600 hover:bg-red-500 text-white flex items-center justify-center shadow transition-all"
                  title="Stop generating reply"
                >
                  <Square size={12} />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => handleSend()}
                  disabled={!input.trim()}
                  className={`w-8 h-8 rounded-full flex items-center justify-center transition-all shadow ${
                    input.trim()
                      ? 'bg-[#8ab4f8] text-[#001d35] hover:bg-[#a8c7fa] cursor-pointer'
                      : 'bg-white/10 text-white/30 cursor-not-allowed'
                  }`}
                  title="Send message"
                >
                  <Send size={13} className={input.trim() ? 'translate-x-0.5' : ''} />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Gemini Disclaimer */}
        <div className="text-center text-[11px] text-[var(--muted-foreground)] mt-2 font-sans">
          Gemini AutoShorts may display inaccurate info. Verify pipeline manifests before dispatching.
        </div>
      </div>
    </div>
  )
}
