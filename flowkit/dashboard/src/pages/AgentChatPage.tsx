import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import TerminalPane from '@/components/chat/TerminalPane'
import {
  Bot,
  Send,
  Terminal,
  Clapperboard,
  Wrench,
  BrainCircuit,
  Zap,
  Copy,
  Check,
  RotateCcw,
  Download,
  Settings2,
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
import { useWebSocketContext } from '../api/useWebSocketContext'
import { fetchAPI } from '../api/client'
import { safeHref } from '../lib/markdown'
import { MediaPreviewCard } from '../components/media/MediaPreviewCard'
import {
  explainUpstreamError,
  fetchOpenCodeModels,
  findModel,
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
  const { isConnected: isExtensionConnected } = useWebSocketContext()

  // State
  const [activePersona] = useState<PersonaType>('director')
  // When true the studio shows a real cmd.exe PTY (for CLI agents) instead of chat.
  const [showTerminal, setShowTerminal] = useState(false)
  // Agent mode routes handleSend through POST /api/opencode/agent/stream (tool
  // loop) instead of plain /chat/stream. Default ON for every persona: the
  // assistant acts on the pipeline through server tools instead of narrating
  // what the user should click. Spending and publishing stay server-gated
  // Agent mode is always on: replies route through the server tool loop so
  // the assistant acts instead of narrating. Spending and publishing stay
  // server-gated, so this is safe without a toggle.
  const agentMode = true
  const [selectedModel, setSelectedModel] = useState<string>('muse-spark-1.3-contributor-free')
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
      if (saved) return JSON.parse(saved)
    } catch {
      // ignore
    }
    return [
      {
        id: 'msg-init',
        role: 'assistant',
        content: `👋 **Welcome to the Agent Studio!**\n\nI am connected to the **OpenCode AI Gateway** using free contributor models with reasoning capability up to **xhigh**.\n\n**Current Persona:** 🎬 **${PERSONAS.director.title}**\n- Enforces a ≤10s scene duration for Google Flow / Veo\n- Strict 5-phase retention arc (Hook, Tension, Twist, Cliffhanger)\n- Automatic S2P decoupling for character consistency\n\nReasoning traces and token counts shown on a reply come from the model that
produced it — nothing is estimated.

Pick a quick prompt below, or describe the episode you want directed.`,
        timestamp: Date.now()
      }
    ]
  })

  // The reply currently being written. It grows in place so the answer is
  // readable as it arrives, rather than after the whole generation is buffered.
  // `tools` holds agent-mode tool-activity frames interleaved with the text.
  const [streaming, setStreaming] = useState<{ text: string; reasoning: string; tools: AgentToolEvent[] } | null>(null)
  const [expandedThoughts, setExpandedThoughts] = useState<Record<string, boolean>>({})
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [dispatchStatus, setDispatchStatus] = useState<{ id: string; loading: boolean; error?: string; successProject?: { id: string; name: string } } | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [serverHealth, setServerHealth] = useState<boolean | null>(null)

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
  // Gemini-style empty state: a fresh thread (welcome message only) shows a
  // greeting instead of the wall of strips and history.
  const isFresh =
    messages.length === 1 &&
    (messages[0]?.id === 'msg-init' ||
      (messages[0]?.role === 'assistant' &&
        (messages[0]?.content || '').startsWith('New conversation.')))
  const dismissCanon = () => {
    try { localStorage.removeItem('flowkit-canon-dismissed') } catch { /* private mode */ }
  }
  void dismissCanon

  useEffect(() => {
    fetchAPI<any>('/health')
      .then(() => setServerHealth(true))
      .catch(() => setServerHealth(false))

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
  const catalogueReady = models.length > 0

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
    setMessages([
      {
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content: `New conversation. Ask anything — I act on the pipeline directly.` ,
        timestamp: Date.now()
      }
    ])
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

  const handleClearHistory = () => {
    if (
      confirm(
        'Clear this chat from the studio?\n\n' +
          'Saved conversations on the server are NOT deleted — they stay under Memory.'
      )
    ) {
      localStorage.removeItem(STORAGE_KEY)
      // A fresh thread, so the next message does not append to the one just
      // cleared (and does not overwrite its server copy).
      startNewConversation()
    }
  }

  const handleExportMarkdown = () => {
    const text = messages
      .map(m => `### ${m.role === 'user' ? '👤 USER' : '🤖 ' + (m.modelUsed || 'ASSISTANT')} (${new Date(m.timestamp || Date.now()).toLocaleTimeString()})\n\n${m.content}\n\n---`)
      .join('\n\n')
    const blob = new Blob([text], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `flowkit-agent-chat-${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
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
    <div className="flex flex-col h-full gap-3 overflow-hidden">
      {/* Studio Top Control Bar */}
      <div
        className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 rounded-lg border flex-shrink-0"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        {/* Left: Persona Tabs */}
        <div className="flex items-center gap-1.5 p-1 rounded-md border" style={{ background: 'var(--bg)', borderColor: 'var(--border)' }}>
                    <button
            onClick={() => setShowTerminal(true)}
            aria-pressed={showTerminal}
            title="Real cmd.exe PTY — run claude / codex / gemini CLI against the project"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition-all font-medium ${
              showTerminal ? 'shadow-sm text-white' : 'hover:opacity-80'
            }`}
            style={{
              background: showTerminal ? '#10b981' : 'transparent',
              color: showTerminal ? '#fff' : 'var(--muted)',
            }}
          >
            <Terminal size={14} />
            <span>Terminal</span>
          </button>

          {/* Tools + memory moved into the composer toolbar (Gemini-style). */}
          </div>

        {/* Model & reasoning live in the composer bar now (Gemini-style) —
            the header stays a slim status strip. */}

        {/* Right: Live Connection Badges & Action Buttons */}
        <div className="flex items-center gap-2">
          {/* Extension WS Status */}
          <div
            className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] border"
            style={{ borderColor: 'var(--border)', background: 'var(--bg)' }}
            title={isExtensionConnected ? 'FlowKit Chrome Extension WebSocket Connected on 9223' : 'Chrome Extension Disconnected'}
          >
            <span
              className="w-2 h-2 rounded-full"
              aria-hidden="true"
              style={{ background: isExtensionConnected ? 'var(--green)' : 'var(--red)' }}
            />
            <span style={{ color: isExtensionConnected ? 'var(--green)' : 'var(--muted)' }}>
              {isExtensionConnected ? 'CDP Extension' : 'No Extension'}
            </span>
          </div>

          {/* API Server Status */}
          <div
            className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] border"
            style={{ borderColor: 'var(--border)', background: 'var(--bg)' }}
            title={serverHealth ? 'FlowKit Agent Server Running on :8100' : 'FlowKit Agent Server Offline'}
          >
            <span
              className="w-2 h-2 rounded-full"
              aria-hidden="true"
              style={{ background: serverHealth ? 'var(--green)' : 'var(--red)' }}
            />
            <span style={{ color: serverHealth ? 'var(--green)' : 'var(--muted)' }}>
              :8100 API
            </span>
          </div>

          {/* Save state for the active thread. Auto-save is debounced, so
              without this there is no way to tell whether the server actually
              has the conversation. */}
          <div
            className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] border font-mono"
            style={{ borderColor: 'var(--border)', background: 'var(--bg)' }}
            title={
              saveError
                ? `Auto-save failed: ${saveError}. The thread is still in this browser.`
                : savedAt
                  ? `Saved to the server at ${new Date(savedAt).toLocaleTimeString()}`
                  : 'In this browser only — the server copy is written shortly after each reply'
            }
          >
            <span
              className="w-2 h-2 rounded-full"
              aria-hidden="true"
              style={{
                background: saveError ? 'var(--red)' : savedAt ? 'var(--green)' : 'var(--muted)'
              }}
            />
            <span style={{ color: saveError ? 'var(--red)' : 'var(--muted)' }}>
              {saveError ? 'Not saved' : savedAt ? 'Saved' : 'Local'}
            </span>
          </div>

          {/* New thread. The current one stays saved on the server. */}
          <button
            onClick={startNewConversation}
            aria-label="Start a new conversation (the current one stays saved)"
            className="p-1.5 rounded border transition-colors hover:opacity-80"
            style={{ borderColor: 'var(--border)', background: 'var(--card)', color: 'var(--muted)' }}
            title="Start a new conversation (the current one stays saved)"
          >
            <Plus size={14} aria-hidden="true" />
          </button>

        </div>
      </div>

      {showTerminal && (
        <div className="flex-1 min-h-0">
          <TerminalPane />
        </div>
      )}

      {/* Gemini-style empty state: greeting only, composer below does the rest */}
      {isFresh && !showTerminal && (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-4">
          <h1 className="text-4xl md:text-5xl font-normal tracking-tight text-white" style={{ fontFamily: 'var(--font-sans)' }}>
            Your move, Abinash!
          </h1>
          <p className="text-xs font-mono max-w-md" style={{ color: 'var(--muted)' }}>
            Autonomous Pipeline Agent · Direct episodes, generate Google Flow stills, assemble video, and scrub watermarks.
          </p>
        </div>
      )}

      {/* Main Conversation Feed: role=log announces new messages politely. */}
      <div
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Conversation messages"
        className={`flex-1 overflow-y-auto px-4 py-4 rounded-lg border flex flex-col gap-4${showTerminal || isFresh ? ' hidden' : ''}`}
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        {messages.map((msg, idx) => {
          const isUser = msg.role === 'user'
          const manifest = !isUser ? extractManifest(msg.content) : null
          const isThoughtExpanded = !!expandedThoughts[msg.id || String(idx)]
          // Narrow the shared dispatch state to this message once, so the
          // optional-chaining checks below can actually be verified by the
          // compiler instead of each access being flagged as possibly null.
          const dispatch = dispatchStatus?.id === msg.id ? dispatchStatus : null

          return (
            <div
              key={msg.id || idx}
              className={`flex flex-col gap-1.5 max-w-4xl ${
                isUser ? 'ml-auto items-end w-full' : 'mr-auto items-start w-full'
              }`}
            >
              {/* Message Header Pill */}
              <div className="flex items-center gap-2 text-[10px] px-1 text-muted-foreground font-mono">
                {isUser ? (
                  <span>👤 You</span>
                ) : (
                  <>
                    <span className="flex items-center gap-1 font-semibold text-blue-400">
                      <Bot size={11} /> {msg.modelUsed || 'OpenCode Director'}
                    </span>
                    {msg.effortUsed && (
                      <span className="px-1.5 py-0.2 rounded border border-blue-500/30 text-blue-300 bg-blue-500/10">
                        {msg.effortUsed} reasoning
                      </span>
                    )}
                    {msg.reasoningTokens ? (
                      <span className="flex items-center gap-0.5 px-1.5 py-0.2 rounded border border-amber-500/30 text-amber-300 bg-amber-500/10">
                        <Zap size={9} /> {msg.reasoningTokens.toLocaleString()} thought tokens
                      </span>
                    ) : null}
                    {msg.latencyMs ? (
                      <span>{(msg.latencyMs / 1000).toFixed(1)}s</span>
                    ) : null}
                  </>
                )}
                <span>· {new Date(msg.timestamp || Date.now()).toLocaleTimeString()}</span>
              </div>

              {/* Message Body Card */}
              <div
                className={`p-4 rounded-xl border text-xs leading-relaxed transition-all ${
                  isUser
                    ? 'rounded-tr-none'
                    : 'rounded-tl-none w-full'
                }`}
                style={{
                  background: 'var(--card)',
                  borderColor: isUser ? 'var(--border)' : 'rgba(59, 130, 246, 0.25)',
                  color: 'var(--text)'
                }}
              >
                {/* Expandable Reasoning / Thought Trace if available */}
                {!isUser && (msg.thoughtTrace || msg.reasoningTokens) && (
                  <div
                    className="mb-3 rounded-md border text-[11px] overflow-hidden"
                    style={{ borderColor: 'rgba(245, 158, 11, 0.3)', background: 'var(--surface)' }}
                  >
                    <button
                      onClick={() =>
                        setExpandedThoughts(prev => ({
                          ...prev,
                          [msg.id || String(idx)]: !isThoughtExpanded
                        }))
                      }
                      aria-expanded={isThoughtExpanded}
                      aria-label={`${isThoughtExpanded ? 'Collapse' : 'Expand'} reasoning trace`}
                      className="w-full flex items-center justify-between px-3 py-1.5 text-amber-300/90 font-mono transition-colors hover:bg-amber-500/10"
                    >
                      <span className="flex items-center gap-1.5">
                        <BrainCircuit size={12} className="text-amber-400" />
                        <span className="font-semibold">Deep Reasoning Trace</span>
                        <span className="text-[10px] text-amber-200/60">
                          ({msg.reasoningTokens?.toLocaleString() || 0} tokens evaluated)
                        </span>
                      </span>
                      {isThoughtExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    </button>

                    {isThoughtExpanded && (
                      <div className="px-3 py-2 border-t border-amber-500/20 font-mono text-[10.5px] leading-snug whitespace-pre-wrap text-amber-100/80 max-h-48 overflow-y-auto">
                        {msg.thoughtTrace ||
                          'The provider returned no reasoning text for this response \u2014 only the token count above.'}
                      </div>
                    )}
                  </div>
                )}

                {/* Tool activity the server actually ran while producing this
                    reply. Rendered above the prose because that is the order it
                    happened in: the assistant acted, then answered. A reply with
                    no tools renders exactly as it did before. */}
                {!isUser && msg.tools && msg.tools.length > 0 && (
                  <div className="mb-2 flex flex-col gap-1.5">
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

                {/* Primary content, rendered from the parsed Markdown tree.
                    Nothing here uses dangerouslySetInnerHTML, so model output
                    cannot inject markup. */}
                <Markdown text={msg.content} />

                {/* Smart Action: If Assistant output contains a JSON manifest, offer 1-click Dispatch to FlowKit */}
                {manifest && (
                  <div
                    className="mt-3 p-3 rounded-lg border flex flex-col gap-2"
                    style={{ background: 'rgba(34, 197, 94, 0.08)', borderColor: 'rgba(34, 197, 94, 0.3)' }}
                  >
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 font-bold text-green-400 text-xs font-mono">
                        <Clapperboard size={13} />
                        Ready-to-Render Episode Manifest Detected ({manifest.scenes?.length || 0} scenes ≤ 10s)
                      </span>
                      <Button
                        size="sm"
                        disabled={!!dispatch?.loading}
                        onClick={() => handleDispatchToFlowKit(msg.id!, manifest)}
                        className="bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] h-7 px-3 flex items-center gap-1"
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

                    {/* Dispatch Result Feedback */}
                    {dispatch?.successProject && (
                      <div role="status" className="flex items-center justify-between text-[11px] text-emerald-300 font-mono pt-1">
                        <span>
                          ✅ Project Created: <strong>{dispatch.successProject.name}</strong>
                        </span>
                        <Link
                          to={`/projects/${dispatch.successProject.id}`}
                          className="flex items-center gap-1 text-emerald-400 underline hover:opacity-80"
                        >
                          View in Projects <ArrowUpRight size={11} />
                        </Link>
                      </div>
                    )}
                    {dispatch?.error && (
                      <div role="status" className="text-[11px] text-red-400 font-mono pt-1 flex items-center gap-1">
                        <AlertCircle size={11} /> {dispatch.error}
                      </div>
                    )}
                  </div>
                )}

                {/* Message Actions Bottom Bar */}
                <div className="flex items-center justify-end gap-2 mt-2 pt-2 border-t border-slate-700/30 text-[10px] text-muted-foreground">
                  {/* Retry appears only on error cards (id *-err): re-sends the
                      stored turn verbatim. Stopped cards never offer it — a
                      Stop was deliberate. */}
                  {!isUser && msg.id?.endsWith('-err') && (
                    <button
                      onClick={handleRetry}
                      disabled={loading}
                      aria-label="Retry the failed reply"
                      title="Re-send the failed turn (same model, same tools)"
                      className="flex items-center gap-1 hover:text-white transition-colors disabled:opacity-50"
                    >
                      <RotateCcw size={11} aria-hidden="true" /> Retry
                    </button>
                  )}
                  <button
                    onClick={() => handleCopy(msg.content, msg.id || String(idx))}
                    aria-label={`Copy ${isUser ? 'your' : 'assistant'} message to clipboard`}
                    className="flex items-center gap-1 hover:text-white transition-colors"
                  >
                    {copiedId === (msg.id || String(idx)) ? (
                      <>
                        <Check size={11} className="text-green-400" aria-hidden="true" /> Copied
                      </>
                    ) : (
                      <>
                        <Copy size={11} aria-hidden="true" /> Copy Message
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          )
        })}

        {/* The reply being written. Rendered with the same component as a
            finished one so the layout does not jump when the stream ends.
            Tool activity alone is enough to show this: the model often calls a
            tool before it writes any prose, and an empty feed there reads as a
            hang. */}
        {streaming && (streaming.text || streaming.reasoning || streaming.tools.length > 0) && (
          <div role="status" aria-label="Assistant reply in progress" className="flex flex-col gap-1.5 max-w-4xl mr-auto items-start w-full">
            <div className="flex items-center gap-2 text-[10px] px-1 text-muted-foreground font-mono">
              <span className="flex items-center gap-1 font-semibold text-blue-400">
                <Bot size={11} /> {selectedModel}
              </span>
              <span className="px-1.5 py-0.2 rounded border border-blue-500/30 text-blue-300 bg-blue-500/10">
                writing
              </span>
            </div>
            <div
              className="p-4 rounded-xl border rounded-tl-none w-full text-xs leading-relaxed"
              style={{
                background: 'var(--card)',
                borderColor: 'rgba(59, 130, 246, 0.25)',
                color: 'var(--text)',
              }}
            >
              {streaming.tools.length > 0 && (
                <div className="mb-3 flex flex-col gap-1.5">
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
                  className="mb-3 rounded-md border px-3 py-2 text-[10.5px] font-mono whitespace-pre-wrap max-h-40 overflow-y-auto"
                  style={{
                    borderColor: 'rgba(245, 158, 11, 0.3)',
                    background: 'var(--surface)',
                    color: 'var(--text)',
                  }}
                >
                  {streaming.reasoning}
                </div>
              )}
              <Markdown text={streaming.text} />
              <span
                className="inline-block w-1.5 h-3.5 align-text-bottom ml-0.5 animate-pulse"
                style={{ background: 'var(--accent)' }}
              />
            </div>
          </div>
        )}

        {/* Spinner only before the first token, so it does not compete with the
            streaming text once that has started — and not while tool cards are
            already on screen, which would say "waiting" over visible progress. */}
        {loading && !streaming?.text && !(streaming?.tools?.length) && (
          <div role="status" aria-label="Assistant is thinking" className="flex items-center gap-3 p-3.5 rounded-xl border max-w-sm mr-auto" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
            <div className="relative flex items-center justify-center">
              <span className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <Zap size={10} className="absolute text-blue-400" />
            </div>
            <div className="flex flex-col">
              <span className="text-xs font-semibold text-blue-400 flex items-center gap-1 font-mono">
                {selectedModel.split('-')[0]} Thinking ({reasoningEffort}) ...
              </span>
              <span className="text-[10px] text-muted-foreground font-mono">
                Evaluating scene pacing & S2P consistency
              </span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Message Input Bar */}
      <div
        className={`p-3 rounded-lg border flex flex-col gap-2 flex-shrink-0${showTerminal ? ' hidden' : ''}`}
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        {/* Tools + memory live in the composer now — one control surface */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <label htmlFor="chat-model-select" className="sr-only">Model</label>
          <select
            id="chat-model-select"
            value={selectedModel}
            onChange={e => {
              const nextModel = e.target.value
              setSelectedModel(nextModel)
              const info = findModel(models, nextModel)
              if (info) setReasoningEffort(info.default_reasoning)
            }}
            disabled={!catalogueReady}
            title="Model"
            className="text-[11px] pl-2 pr-1 py-1 rounded-full border outline-none font-mono max-w-[240px] cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
            style={{ background: 'var(--card)', color: 'var(--text)', borderColor: 'var(--border)' }}
          >
            {models.map(m => (
              <option key={m.id} value={m.id}>
                {m.name} {m.is_free ? '· Free' : ''}
              </option>
            ))}
          </select>
          <label htmlFor="chat-reasoning-select" className="sr-only">Reasoning effort</label>
          <select
            id="chat-reasoning-select"
            value={reasoningEffort}
            onChange={e => setReasoningEffort(e.target.value as ReasoningEffort)}
            disabled={!catalogueReady || reasoningTiers.length === 1}
            title="Reasoning effort"
            className="text-[11px] pl-2 pr-1 py-1 rounded-full border outline-none font-mono cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
            style={{ background: 'var(--card)', color: 'var(--text)', borderColor: 'var(--border)' }}
          >
            {reasoningTiers.map(effort => (
              <option key={effort} value={effort}>
                {effort === 'xhigh' ? '⚡ xhigh' : effort === 'high' ? '🧠 high' : effort}
              </option>
            ))}
          </select>
          {currentModelInfo && (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full font-mono border"
              style={currentModelInfo.is_free
                ? { borderColor: 'rgba(52, 211, 153, 0.3)', color: 'var(--green)' }
                : { borderColor: 'rgba(245, 158, 11, 0.4)', color: 'var(--amber, #f59e0b)' }}
              title={currentModelInfo.is_free ? undefined : 'Paid models are refused unless this OpenCode account has a payment method.'}
            >
              {currentModelInfo.is_free ? 'FREE · $0' : 'PAID'}
            </span>
          )}
        </div>

        {/* Quick Tools Drawer (triggered by + button) */}
        {showQuickDrawer && (
          <div
            className="p-3 rounded-xl border flex flex-col gap-2 mb-1 animate-in fade-in slide-in-from-bottom-2 duration-150"
            style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold tracking-wider uppercase text-blue-400 flex items-center gap-1.5">
                <Sparkles size={13} /> Quick Tools & Actions
              </span>
              <span className="text-[10px]" style={{ color: 'var(--muted)' }}>Click to load into composer</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setInput('Direct Episode 2 of Arthur & Rusty: "The Whispering Well". Keep scenes strictly under 10s with high-retention 5-beat pacing.')
                  setShowQuickDrawer(false)
                }}
                className="text-left p-2 rounded-lg border text-xs text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors flex items-center gap-2"
                style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
              >
                <Clapperboard size={14} className="text-blue-400 flex-shrink-0" />
                <span className="truncate">Direct Episode 2 (Arthur & Rusty)</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setInput('Queue a vertical 9:16 still image in Google Flow: "Arthur holding a glowing brass lantern deep inside the stone well, cinematic lighting".')
                  setShowQuickDrawer(false)
                }}
                className="text-left p-2 rounded-lg border text-xs text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors flex items-center gap-2"
                style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
              >
                <Sparkles size={14} className="text-amber-400 flex-shrink-0" />
                <span className="truncate">Generate Google Flow Still</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setInput('Check the current request queue status and reference image conditioning for farmer_and_rusty.')
                  setShowQuickDrawer(false)
                }}
                className="text-left p-2 rounded-lg border text-xs text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors flex items-center gap-2"
                style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
              >
                <Database size={14} className="text-emerald-400 flex-shrink-0" />
                <span className="truncate">Check Queue & Conditioning</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setInput('Scrub the AI watermark from storage/output/farmer_and_rusty_ep1.mp4 using the veo_bottom_right delogo profile.')
                  setShowQuickDrawer(false)
                }}
                className="text-left p-2 rounded-lg border text-xs text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors flex items-center gap-2"
                style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
              >
                <Wrench size={14} className="text-purple-400 flex-shrink-0" />
                <span className="truncate">Scrub Video Watermark</span>
              </button>
            </div>
          </div>
        )}

        <div className="flex items-center gap-2">
          {/* Quick Tools + Button */}
          <button
            type="button"
            onClick={() => setShowQuickDrawer(prev => !prev)}
            title={showQuickDrawer ? 'Close tools drawer' : 'Open tools drawer (+)'}
            aria-label="Add tools"
            className={`w-9 h-9 rounded-full border flex items-center justify-center transition-all flex-shrink-0 ${
              showQuickDrawer
                ? 'bg-blue-600 text-white border-blue-500 shadow-sm'
                : 'text-slate-400 hover:text-white border-slate-700/80 bg-slate-800/50 hover:bg-slate-800'
            }`}
          >
            <Plus size={16} />
          </button>

          <textarea
            ref={textareaRef}
            id="chat-composer"
            aria-label={`Message ${currentPersona.title}`}
            rows={2}
            value={input}
            disabled={loading}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder={`Ask Gemini or direct the pipeline (Press Enter to send)...`}
            className="flex-1 bg-transparent border-0 outline-none text-xs resize-none placeholder:text-slate-500 font-sans overflow-y-auto"
            style={{ color: 'var(--text)', maxHeight: '200px' }}
          />

          {/* Voice / Mic Button */}
          <button
            type="button"
            onClick={() => {
              if (!input) {
                setInput('Audit the scene pacing and character consistency for our current series arc.')
              }
            }}
            title="Voice prompt"
            aria-label="Voice prompt"
            className="w-9 h-9 rounded-full border border-slate-700/80 bg-slate-800/40 hover:bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center transition-colors flex-shrink-0"
          >
            <Mic size={15} />
          </button>

          {/* While a reply is running the primary action becomes Stop. An agent
              turn can run several tool rounds, so without this the only way out
              of a slow or looping reply was reloading the page. */}
          {loading ? (
            <Button
              onClick={handleStop}
              aria-label="Stop generating reply"
              className="h-9 px-4 rounded-full flex items-center gap-1.5 font-medium transition-all"
              style={{ background: 'var(--red, #ef4444)', color: '#fff' }}
              title="Stop this reply (partial text is kept)"
            >
              <span>Stop</span>
              <Square size={11} aria-hidden="true" />
            </Button>
          ) : (
            <Button
              onClick={() => handleSend()}
              disabled={!input.trim()}
              aria-label="Send message"
              className="h-9 px-4 rounded-full flex items-center gap-1.5 font-medium transition-all shadow-sm"
              style={{ background: 'var(--accent)', color: '#fff' }}
            >
              <span>Send</span>
              <Send size={12} aria-hidden="true" />
            </Button>
          )}
        </div>

        {/* Bottom Hint */}
        <div className="flex items-center justify-between text-[10px] text-muted-foreground font-mono">
          <span className="flex items-center gap-2">
            <span>Active: <strong>{currentPersona.title}</strong></span>
            <span>·</span>
            <span>{capabilities ? `${capabilities.operation_count} tools` : 'tools'} · {agentMode ? 'agent on' : 'plain chat'}</span>
          </span>
          <span className="flex items-center gap-1">
            <ShieldCheck size={11} className="text-emerald-400" /> S2P Decoupling Active · ≤10s Limit
          </span>
        </div>
      </div>
    </div>
  )
}
