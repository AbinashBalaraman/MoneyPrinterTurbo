import { Card, CardHeader, CardTitle, CardDescription, CardAction, CardContent } from '../ui/card'
import { Progress } from '../ui/progress'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip'
import { useTranslation } from '../../i18n/useTranslation'
import type { StageState } from '../../lib/pipelineStages'
import type { StageCount } from '../../lib/stageStats'

interface StageNodeProps {
  idx: string
  name: string
  subtitle: string
  counts: StageCount
  state: StageState
  /** No backend for this stage — show that plainly instead of a zeroed bar. */
  notConnected: boolean
  isActive: boolean
  onClick: () => void
  /** Live line count from the log bus for this node's stages. */
  logCount?: number
  /** Rendered inside the not-connected tooltip, e.g. the owning system. */
  ownerNote?: string
}

const STATE_COLOR: Record<StageState, string> = {
  done: 'var(--green)',
  running: 'var(--yellow)',
  failed: 'var(--red)',
  pending: 'var(--border)',
  not_connected: 'var(--muted)',
}

export default function StageNode({
  idx, name, subtitle, counts, state, notConnected, isActive, onClick, logCount = 0, ownerNote,
}: StageNodeProps) {
  const { t } = useTranslation()
  const { done, processing, failed, pending, total } = counts
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)
  const stateColor = STATE_COLOR[state]

  // A live stage with nothing selected still needs to read as alive, so the
  // accent follows the state rather than only the selection.
  const accent = isActive ? 'var(--accent)' : stateColor

  const card = (
    <button
      onClick={onClick}
      aria-pressed={isActive}
      className="flex-1 min-w-0 text-left"
      style={{ opacity: notConnected && !isActive ? 0.72 : 1 }}
    >
      <Card
        className="gap-3 py-4"
        style={notConnected ? { borderStyle: 'dashed' } : undefined}
      >
        <div style={{ height: 2, margin: '-16px 0 0', background: accent }} />
        <CardHeader>
          <CardTitle>
            <span className="text-[10px] tracking-widest" style={{ color: 'var(--muted)' }}>{idx}</span>
            <span className="ml-2 text-sm tracking-wide uppercase">{name}</span>
          </CardTitle>
          <CardDescription>
            <span className="text-xs">{subtitle}</span>
          </CardDescription>
          <CardAction>
            {notConnected ? (
              <span className="text-[10px] tracking-widest uppercase" style={{ color: 'var(--muted)' }}>
                {t('pipeline.notConnectedShort')}
              </span>
            ) : (
              <>
                <span className="text-lg tracking-tight" style={{ color: isActive ? 'var(--accent)' : 'var(--text)' }}>{done}</span>
                <span className="text-xs" style={{ color: 'var(--muted)' }}>/{total}</span>
              </>
            )}
          </CardAction>
        </CardHeader>
        <CardContent>
          {notConnected ? (
            <div className="text-[10px] tracking-wide" style={{ color: 'var(--muted)' }}>
              {t('pipeline.notConnected')}
            </div>
          ) : (
            <>
              <Progress value={pct} />
              <div className="flex flex-wrap gap-x-3 gap-y-1.5 mt-3 text-[10px] tracking-wide" style={{ color: 'var(--muted)' }}>
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5" style={{ background: 'var(--green)' }} />{done} {t('stageNode.done')}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5" style={{ background: 'var(--yellow)' }} />{processing} {t('stageNode.proc')}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5" style={{ background: 'var(--red)' }} />{failed} {t('stageNode.fail')}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5" style={{ background: 'var(--border)' }} />{pending} {t('stageNode.pend')}
                </span>
              </div>
            </>
          )}

          {logCount > 0 && (
            <div className="flex items-center gap-1.5 mt-3 text-[10px] tracking-wide" style={{ color: 'var(--accent)' }}>
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ background: 'var(--accent)', animation: state === 'running' ? 'pulse 1.6s ease-in-out infinite' : 'none' }}
              />
              {t('pipeline.logs.forStage', { n: logCount })}
            </div>
          )}
        </CardContent>
      </Card>
    </button>
  )

  if (!ownerNote) return card

  return (
    <Tooltip>
      <TooltipTrigger asChild>{card}</TooltipTrigger>
      <TooltipContent>
        <span className="text-[11px] leading-snug">{ownerNote}</span>
      </TooltipContent>
    </Tooltip>
  )
}
