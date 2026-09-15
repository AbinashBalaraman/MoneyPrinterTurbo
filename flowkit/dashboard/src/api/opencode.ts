/**
 * OpenCode client for the FlowKit dashboard.
 *
 * The browser talks to the FlowKit agent at `/api/opencode/*`. It never talks
 * to opencode.ai, and it never holds an API key: the agent owns the credential
 * and resolves which protocol each model speaks.
 *
 * Why this file looks the way it does
 * -----------------------------------
 * It used to do the opposite. It carried a live API key in the JS bundle
 * (`DEFAULT_OPENCODE_KEY`) and guessed each model's protocol from its id:
 *
 *     endpoint: isResponses ? 'responses' : 'chat/completions'
 *
 * That guess is the "models are mismatching" bug. A model whose real endpoint
 * was `responses` but whose id did not contain `muse-spark` was sent to
 * `chat/completions`, and the request failed in a way that looked like a broken
 * model rather than a routing bug. The catalogue and the protocol now come from
 * `agent/services/opencode_models.py`, which is the single source of truth.
 */

export type ReasoningEffort = 'xhigh' | 'high' | 'medium' | 'low' | 'off'

/**
 * Canonical protocol name. Note the hyphen: `chat-completions` is the *name*,
 * `/chat/completions` is the URL path. Only the server translates between them.
 */
export type EndpointType = 'responses' | 'chat-completions'

export interface ChatMessage {
  id?: string
  role: 'system' | 'user' | 'assistant'
  content: string
  timestamp?: number
  reasoningTokens?: number
  thoughtTrace?: string
  latencyMs?: number
  modelUsed?: string
  effortUsed?: ReasoningEffort
  /** Tool-activity frames collected on the agent-mode path. Absent on /chat/stream. */
  tools?: AgentToolEvent[]
}

/** A model as described by the server. Mirrors `ModelInfo.to_dict()`. */
export interface ModelOption {
  id: string
  name: string
  endpoint_type: EndpointType
  supported_reasoning: ReasoningEffort[]
  default_reasoning: ReasoningEffort
  is_free: boolean
  supports_vision: boolean
  context_window: number
  max_output_tokens: number
  /** `api` when it came from the live list, `builtin` when from the fallback. */
  source: 'api' | 'builtin'
}

/** Response of `GET /api/opencode/models`. */
export interface ModelCatalogue {
  models: ModelOption[]
  /**
   * Where the list came from. The UI shows this rather than implying the list
   * is live when the network or key was unavailable.
   */
  source: 'api' | 'builtin'
  key_configured: boolean
  error: string | null
}

/** Response of `GET /api/opencode/status`. Never contains the key itself. */
export interface OpenCodeStatus {
  configured: boolean
  base_url: string
  models_cached: number
  models_builtin: number
  source: 'api' | 'builtin'
  error: string | null
}

export interface ChatResponseResult {
  text: string
  thoughtTrace?: string
  reasoningTokens: number
  inputTokens: number
  outputTokens: number
  totalTokens: number
  latencyMs: number
  model: string
  /** Which protocol the server actually used. Surfaced so a routing bug is visible. */
  endpointType: EndpointType
  reasoningEffort: ReasoningEffort
}

/**
 * Pull a human-readable message out of an error response.
 *
 * FastAPI puts a string in `detail` for HTTPException but a list of field
 * errors for validation failures, so both shapes are handled.
 */
async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join('; ')
    }
    if (detail) return JSON.stringify(detail)
    return `HTTP ${res.status}`
  } catch {
    return res.statusText || `HTTP ${res.status}`
  }
}

// ---------------------------------------------------------------------------
// Upstream error explanation
// ---------------------------------------------------------------------------

export interface UpstreamExplanation {
  /** Short, plain-language statement of what went wrong. */
  title: string
  /** What the person can actually do about it. */
  hint: string
  /** False when retrying the same model could still succeed. */
  switchModel: boolean
}

/**
 * Turn a provider failure into something a person can act on.
 *
 * OpenCode relays provider errors as a JSON envelope, occasionally nested
 * inside another JSON string, for example:
 *
 *   {"error":{"type":"CreditsError","message":"No payment method. Add a …"}}
 *
 * Rendered raw that is unreadable, and the natural reaction is to assume the
 * app itself is broken. Anything unrecognised returns `null` so the caller can
 * fall back to the original text instead of inventing a cause.
 */
export function explainUpstreamError(raw: string): UpstreamExplanation | null {
  const payload = unwrapErrorPayload(raw)
  if (!payload) return null

  const type = String(payload.type ?? '')
  const message = String(payload.message ?? '')

  if (type === 'CreditsError' || /no payment method/i.test(message)) {
    return {
      title: 'This model needs a paid account',
      hint:
        'Your OpenCode account has no payment method, so paid models are refused. ' +
        'Models whose id ends in `-free` still work — switch to one of those.',
      switchModel: true
    }
  }

  if (type === 'FreeUsageLimitError' || /free usage limit/i.test(message)) {
    return {
      title: 'The free quota for this model is used up',
      hint: 'Pick a different `-free` model, or wait for the quota to reset.',
      switchModel: true
    }
  }

  if (/model is unavailable/i.test(message)) {
    return {
      title: 'The provider has this model offline',
      hint: 'This is upstream, not local. Choose another model and try again.',
      switchModel: true
    }
  }

  if (type === 'authentication_error' || /invalid api key|unauthoriz/i.test(message)) {
    return {
      title: 'The OpenCode key was rejected',
      hint: 'Set OPENCODE_API_KEY in the repository .env, then restart the agent.',
      switchModel: false
    }
  }

  if (/rate.?limit/i.test(message)) {
    return {
      title: 'Rate limited by the provider',
      hint: 'Wait a moment and retry, or switch models.',
      switchModel: false
    }
  }

  return null
}

/**
 * Dig a provider error object out of the envelopes seen in practice.
 *
 * The payload may be an object, a JSON string, or a JSON string containing
 * another JSON string, so unwrap up to a few levels before giving up.
 */
function unwrapErrorPayload(raw: string): { type?: string; message?: string } | null {
  const levels: Record<string, any>[] = []
  let current: unknown = raw

  for (let depth = 0; depth < 4 && typeof current === 'string'; depth++) {
    const text = current.trim()
    if (!text.startsWith('{')) break
    try {
      current = JSON.parse(text)
    } catch {
      break
    }
    if (current && typeof current === 'object') {
      levels.push(current as Record<string, any>)
    }
  }

  for (const level of levels) {
    // `{type, error:{type, message}}` and `{error:{type, message}}` both occur.
    const inner =
      level.error && typeof level.error === 'object' ? (level.error as Record<string, any>) : level
    const type = inner.type ?? level.type
    const message = inner.message ?? level.message
    if (type || message) return { type, message }
  }

  return null
}

/** Whether the agent has an OpenCode key configured. */
export async function fetchOpenCodeStatus(): Promise<OpenCodeStatus> {
  const res = await fetch('/api/opencode/status')
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

/**
 * Fetch the model catalogue from the agent.
 *
 * `refresh` bypasses the server-side TTL cache. The server falls back to its
 * built-in list rather than failing, so a network problem degrades the list
 * instead of breaking the page.
 */
export async function fetchOpenCodeModels(refresh = false): Promise<ModelCatalogue> {
  const res = await fetch(`/api/opencode/models${refresh ? '?refresh=true' : ''}`)
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

/** Look a model up in a fetched catalogue. Returns undefined rather than guessing. */
export function findModel(models: ModelOption[], modelId: string): ModelOption | undefined {
  return models.find(m => m.id === modelId)
}

/**
 * Send a completion through the agent.
 *
 * No `apiKey` option: the key lives in server config and is injected server-side.
 * An unknown model or an unsupported reasoning tier is rejected by the server
 * with a specific message rather than silently falling back to another model.
 */
export async function sendOpenCodeChat(
  messages: { role: 'system' | 'user' | 'assistant'; content: string }[],
  options: {
    model: string
    reasoningEffort?: ReasoningEffort
    temperature?: number
  }
): Promise<ChatResponseResult> {
  const res = await fetch('/api/opencode/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: options.model,
      messages,
      reasoning_effort: options.reasoningEffort,
      temperature: options.temperature ?? 0.7
    })
  })

  if (!res.ok) throw new Error(await readError(res))

  const data = await res.json()
  return {
    text: data.text ?? '',
    thoughtTrace: data.thought_trace ?? undefined,
    reasoningTokens: data.reasoning_tokens ?? 0,
    inputTokens: data.input_tokens ?? 0,
    outputTokens: data.output_tokens ?? 0,
    totalTokens: data.total_tokens ?? 0,
    latencyMs: data.latency_ms ?? 0,
    model: data.model,
    endpointType: data.endpoint_type,
    reasoningEffort: data.reasoning_effort
  }
}

export interface StreamUsage {
  reasoningTokens: number
  inputTokens: number
  outputTokens: number
  totalTokens: number
}

export interface StreamDone {
  model: string
  endpointType: EndpointType
  reasoningEffort: ReasoningEffort
  latencyMs: number
}

export interface StreamHandlers {
  onText?: (chunk: string) => void
  onReasoning?: (chunk: string) => void
  onUsage?: (usage: StreamUsage) => void
  onDone?: (info: StreamDone) => void
  /**
   * Extra frames emitted only by the agent-mode endpoint
   * (`POST /api/opencode/agent/stream`). Plain `/chat/stream` never sends
   * them, so a handler set without `onTool` simply ignores them.
   */
  onTool?: (event: AgentToolEvent) => void
}

/**
 * One tool-activity frame from the agent loop.
 *
 * The backend streams these between text deltas while it acts: web-search
 * results, sandboxed command output, memory-operation confirmations, and
 * project/queue snapshots. Every field except `type`/`tool` is optional
 * because each tool reports a different payload; unknown tools still arrive
 * here so the UI can render them generically instead of dropping them.
 */
export interface AgentToolEvent {
  type: 'tool'
  /** Tool name, e.g. `web_search`, `run_command`, `memory`, `project_snapshot`. */
  tool: string
  /** Lifecycle marker when the backend sends one (`start` / `done` / `error`). */
  status?: string
  /**
   * What the operation costs, from the server's operations catalog.
   * `spend` costs money, `destructive` is public/irreversible. Carried on the
   * frame so the card can warn *before* the result is read.
   */
  risk?: 'read' | 'write' | 'spend' | 'destructive'
  /** True when the server refused the call on risk grounds — nothing ran. */
  refused?: boolean
  /**
   * Tool arguments as sent (when the backend includes them). Optional:
   * current frames carry tool-specific fields (command/query/results/…) but
   * not raw args. The destructive-approval card therefore re-confirms via
   * the chat loop (model re-invokes with {"confirm": true}) instead of
   * replaying args — no new server route. If the backend ever echoes args
   * here, the UI can offer exact-args replay.
   */
  args?: Record<string, unknown>
  /** Human-readable label for the activity row. */
  title?: string
  /** `web_search`: the query that was run. */
  query?: string
  /** `web_search`: result cards. */
  results?: { title: string; url: string; snippet: string }[]
  /** `run_command`: the command that was executed. */
  command?: string
  /** `run_command`: captured output (capped server-side; UI caps rendering too). */
  output?: string
  exit_code?: number | null
  /** `memory`: which operation ran (`read` / `write` / `append` / …). */
  operation?: string
  /** `memory`: short confirmation detail. */
  detail?: string
  /** Snapshot tools: one-line summary. */
  summary?: string
  /** Snapshot tools / unknown tools: structured payload, rendered as JSON. */
  data?: unknown
  /** Error text when `status` is `error`. */
  message?: string
}

/** Translate one SSE frame, invoking the matching handler. */
function handleFrame(frame: string, handlers: StreamHandlers): void {
  for (const line of frame.split('\n')) {
    if (!line.startsWith('data:')) continue
    const raw = line.slice(5).trim()
    if (!raw) continue

    let event: any
    try {
      event = JSON.parse(raw)
    } catch {
      // One malformed frame is not worth aborting the whole reply over.
      continue
    }

    switch (event.type) {
      case 'text':
        handlers.onText?.(event.text ?? '')
        break
      case 'reasoning':
        handlers.onReasoning?.(event.text ?? '')
        break
      case 'usage':
        handlers.onUsage?.({
          reasoningTokens: event.reasoning_tokens ?? 0,
          inputTokens: event.input_tokens ?? 0,
          outputTokens: event.output_tokens ?? 0,
          totalTokens: event.total_tokens ?? 0
        })
        break
      case 'error':
        // Thrown rather than swallowed: a stream that failed must not be
        // rendered as if the model finished answering.
        throw new Error(event.message || 'The model stream failed.')
      case 'tool':
        // Agent-mode only. Plain /chat/stream never sends these; a handler
        // set without onTool drops them, which keeps the old path untouched.
        handlers.onTool?.(event as AgentToolEvent)
        break
      case 'done':
        handlers.onDone?.({
          model: event.model,
          endpointType: event.endpoint_type,
          reasoningEffort: event.reasoning_effort,
          latencyMs: event.latency_ms ?? 0
        })
        break
    }
  }
}

/**
 * Drain an SSE response, dispatching each frame to `handlers`.
 *
 * Shared by both stream endpoints so the agent path cannot drift from the
 * plain path: same framing, same error semantics, plus optional `tool`
 * frames on the agent endpoint.
 */
async function pumpSSE(res: Response, handlers: StreamHandlers): Promise<void> {
  if (!res.body) throw new Error('Streaming is unavailable in this browser.')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE frames are separated by a blank line.
      for (;;) {
        const sep = buffer.indexOf('\n\n')
        if (sep === -1) break
        const frame = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        handleFrame(frame, handlers)
      }
    }
  } finally {
    reader.cancel().catch(() => {})
  }
}

/**
 * Stream a completion, reporting deltas as they arrive.
 *
 * Same validation and same server-side key injection as `sendOpenCodeChat`; the
 * difference is that text is surfaced while it is produced. Resolves when the
 * stream ends, and throws on a transport failure or an `error` frame.
 */
export async function streamOpenCodeChat(
  messages: { role: 'system' | 'user' | 'assistant'; content: string }[],
  options: {
    model: string
    reasoningEffort?: ReasoningEffort
    temperature?: number
  },
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch('/api/opencode/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: options.model,
      messages,
      reasoning_effort: options.reasoningEffort,
      temperature: options.temperature ?? 0.7
    }),
    signal
  })

  // Rejections (unknown model, bad reasoning tier, no key) come back as an
  // ordinary JSON response before any streaming begins.
  if (!res.ok) throw new Error(await readError(res))
  await pumpSSE(res, handlers)
}

/**
 * Stream a completion through the agent tool loop.
 *
 * Same request shape as `streamOpenCodeChat`, but the server runs the
 * prompt-level tool protocol around the model (web search, memory ops,
 * project/queue snapshots, sandboxed commands) and interleaves extra `tool`
 * frames, delivered to `handlers.onTool`. Text/reasoning/usage/done frames
 * are identical, so callers accumulate them exactly as before.
 *
 * Throws an `AGENT_STREAM_NOT_FOUND …` error when the backend does not have
 * the endpoint yet, so the caller can fall back to `streamOpenCodeChat`
 * rather than showing a dead toggle.
 */
export async function streamAgentChat(
  messages: { role: 'system' | 'user' | 'assistant'; content: string }[],
  options: {
    model: string
    reasoningEffort?: ReasoningEffort
    temperature?: number
  },
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch('/api/opencode/agent/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: options.model,
      messages,
      reasoning_effort: options.reasoningEffort,
      temperature: options.temperature ?? 0.7
    }),
    signal
  })

  if (res.status === 404) {
    throw new Error(
      `AGENT_STREAM_NOT_FOUND: POST /api/opencode/agent/stream is not on this agent build.`
    )
  }
  if (!res.ok) throw new Error(await readError(res))
  await pumpSSE(res, handlers)
}
