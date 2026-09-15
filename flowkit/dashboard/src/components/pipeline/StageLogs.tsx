import { useEffect, useMemo, useRef, useState } from 'react'
import { useWebSocketContext } from '../../api/useWebSocketContext'
import { useTranslation } from '../../i18n/useTranslation'
import type { LogRecord } from '../../types'
import type { LogStage } from '../../lib/pipelineStages'
import { LogRowView } from '../logs/LogRow'
import { Button } from '../ui/button'

/** How many lines the inline panel keeps in the DOM. */
const VISIBLE_LIMIT = 200
/** Distance from the bottom, in px, still considered "at the bottom". */
const STICK_THRESHOLD = 24

interface StageLogsProps {
  /** Log stages rolled up into the selected rail node. */
  stages: LogStage[]
  stageLabel: string
  /** True when no backend emits lines for this stage at all. */
  notConnected: boolean
  onOpenConsole: () => void
}

/**
 * Live log lines for the selected pipeline stage.
 *
 * This is the answer to "logs are not visible in the processing tabs": the rail
 * and the logs are the same screen, filtered by the stage the backend actually
 * tagged. When a stage has emitted nothing it says so, and when a stage has no
 * backend it says that instead — an empty box is not an explanation.
 */
export default function StageLogs({ stages, stageLabel, notConnected, onOpenConsole }: StageLogsProps) {
  const { t } = useTranslation()
  const { logs, isConnected } = useWebSocketContext()

  const scrollerRef = useRef<HTMLDivElement>(null)
  const [following, setFollowing] = useState(true)
  const [copiedSeq, setCopiedSeq] = useState<number | null>(null)

  const filtered = useMemo(() => {
    const wanted = new Set<string>(stages)
    return logs.filter(r => r.stage != null && wanted.has(r.stage)).slice(-VISIBLE_LIMIT)
  }, [logs, stages])

  useEffect(() => {
    if (!following) return
    const el = scrollerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [filtered.length, following])

  function handleScroll() {
    const el = scrollerRef.current
    if (!el) return
    setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD)
  }

  function copy(record: LogRecord) {
    const line = `${record.ts} ${record.level} [${record.stage ?? '-'}] ${record.message}`
    void navigator.clipboard?.writeText(line)
    setCopiedSeq(record.seq)
    window.setTimeout(() => setCopiedSeq(s => (s === record.seq ? null : s)), 1200)
  }

  return (
    <section
      className="flex flex-col rounded-md overflow-hidden"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <header
        className="flex items-center justify-between gap-4 px-3 py-2"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="text-[10px] tracking-widest uppercase" style={{ color: 'var(--muted)' }}>
            {t('pipeline.logs.heading')}
          </span>
          <span className="text-[11px] truncate" style={{ color: 'var(--text)' }}>{stageLabel}</span>
          <span className="text-[10px]" style={{ color: 'var(--muted)' }}>· {filtered.length}</span>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <span className="flex items-center gap-1.5 text-[10px] tracking-wide" style={{ color: isConnected ? 'var(--green)' : 'var(--muted)' }}>
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: isConnected ? 'var(--green)' : 'var(--muted)' }}
            />
            {isConnected ? t('logs.console.live') : t('logs.console.disconnected')}
          </span>
          <Button variant="ghost" size="sm" onClick={onOpenConsole}>
            {t('pipeline.logs.openConsole')}
          </Button>
        </div>
      </header>

      {filtered.length === 0 ? (
        <div className="px-3 py-6 text-[11px] leading-relaxed" style={{ color: 'var(--muted)' }}>
          {notConnected
            ? t('pipeline.logs.emptyNotConnected')
            : t('pipeline.logs.empty', { stage: stageLabel })}
        </div>
      ) : (
        <div
          ref={scrollerRef}
          onScroll={handleScroll}
          className="overflow-y-auto"
          style={{ maxHeight: 260 }}
        >
          {filtered.map(record => (
            <LogRowView key={record.seq} record={record} compact onSelect={copy} />
          ))}
        </div>
      )}

      {filtered.length > 0 && (
        <footer
          className="flex items-center justify-between px-3 py-1.5 text-[10px]"
          style={{ borderTop: '1px solid var(--border)', color: 'var(--muted)' }}
        >
          <span style={{ color: copiedSeq != null ? 'var(--green)' : 'var(--muted)' }}>
            {copiedSeq != null ? t('logs.console.copied') : t('logs.console.clickToCopy')}
          </span>
          <button
            className="tracking-wide"
            style={{ color: following ? 'var(--accent)' : 'var(--muted)' }}
            onClick={() => {
              setFollowing(true)
              const el = scrollerRef.current
              if (el) el.scrollTop = el.scrollHeight
            }}
          >
            {following ? t('logs.console.following') : t('logs.console.paused')}
          </button>
        </footer>
      )}
    </section>
  )
}
