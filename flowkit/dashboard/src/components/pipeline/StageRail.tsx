import { useTranslation } from '../../i18n/useTranslation'
import type { TranslationKey } from '../../i18n/translations'
import { RAIL_STAGES, type LogStage, type RailKey, type RailStatus } from '../../lib/pipelineStages'
import StageNode from './StageNode'

interface StageRailProps {
  active: RailKey
  onSelect: (key: RailKey) => void
  statusOf: (key: RailKey) => RailStatus
  /** Live log-line count for a node, so activity is visible on the rail itself. */
  logCountOf: (stages: LogStage[]) => number
}

/**
 * The six end-to-end pipeline stages.
 *
 * Stages owned by another service render as explicitly not-connected rather
 * than as a zeroed progress bar, because "0 of 0" reads as "nothing has
 * happened yet" — a different, and false, claim.
 */
export default function StageRail({ active, onSelect, statusOf, logCountOf }: StageRailProps) {
  const { t } = useTranslation()

  return (
    <div className="flex items-stretch gap-2.5">
      {RAIL_STAGES.map(def => {
        const status = statusOf(def.key)
        const owner = t(`pipeline.owner.${def.owner}` as TranslationKey)
        const name = t(`pipeline.railName.${def.key}` as TranslationKey)

        return (
          <StageNode
            key={def.key}
            idx={def.idx}
            name={name}
            subtitle={t(`pipeline.railSubtitle.${def.key}` as TranslationKey)}
            counts={status.counts}
            state={status.state}
            notConnected={status.notConnected}
            isActive={active === def.key}
            onClick={() => onSelect(def.key)}
            logCount={logCountOf(def.stages)}
            ownerNote={
              def.wired
                ? undefined
                : `${t('pipeline.notConnected.title', { name })} — ${t('pipeline.runsIn', { system: owner })}`
            }
          />
        )
      })}
    </div>
  )
}
