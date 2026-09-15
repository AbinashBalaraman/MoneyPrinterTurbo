import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchAPI } from '../../api/client'
import { useWebSocketContext } from '../../api/useWebSocketContext'
import { useTranslation } from '../../i18n/useTranslation'
import type { TranslationKey } from '../../i18n/translations'
import { statusLabel, stateLabel } from '../../i18n/labels'
import type { Project, Video, Character, Scene, Request, SceneReview, StatusType } from '../../types'
import { sceneStageStatus, charStatus, latestRequest, type SceneStage } from '../../lib/stageStats'
import { RAIL_STAGES, railStatus, type LogStage, type RailKey } from '../../lib/pipelineStages'
import { Button } from '../ui/button'
import { Avatar, AvatarFallback, AvatarGroup } from '../ui/avatar'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip'
import StageRail from './StageRail'
import StageLogs from './StageLogs'
import PublishPanel from './PublishPanel'
import SceneCard from './SceneCard'
import SceneDetailSheet from './SceneDetailSheet'

interface PipelineViewProps {
  projectId: string
  videoId: string
}

/** The two sub-views behind the Images node. */
type ImageView = 'refs' | 'image'
/** The two sub-views behind the Assemble node. */
type AssembleView = 'video' | 'upscale'

const RETRY_TYPE: Record<SceneStage, string> = {
  image: 'REGENERATE_IMAGE',
  video: 'REGENERATE_VIDEO',
  upscale: 'UPSCALE_VIDEO',
}

function Segmented<T extends string>({ value, options, onChange }: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div
      className="flex items-center gap-0.5 p-0.5 rounded border w-fit"
      style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
    >
      {options.map(o => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          aria-pressed={value === o.value}
          className="px-2.5 py-1 rounded text-[11px] font-medium"
          style={{
            background: value === o.value ? 'var(--accent)' : 'transparent',
            color: value === o.value ? '#fff' : 'var(--muted)',
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/**
 * A stage this deployment cannot run.
 *
 * Deliberately not a disabled button with a tooltip: a control that looks
 * operable but never does anything is the specific defect this replaces. The
 * panel states where the work actually happens and stops.
 */
function NotConnectedPanel({ name, system }: { name: string; system: string }) {
  const { t } = useTranslation()
  return (
    <div
      className="flex flex-col gap-2 p-5 rounded-md"
      style={{ background: 'var(--card)', border: '1px dashed var(--border)' }}
    >
      <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
        {t('pipeline.notConnected.title', { name })}
      </div>
      <p className="m-0 text-[11px] leading-relaxed max-w-[70ch]" style={{ color: 'var(--muted)' }}>
        {t('pipeline.notConnected.body', { system })}
      </p>
    </div>
  )
}

export default function PipelineView({ projectId, videoId }: PipelineViewProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [video, setVideo] = useState<Video | null>(null)
  const [characters, setCharacters] = useState<Character[]>([])
  const [scenes, setScenes] = useState<Scene[]>([])
  const [requests, setRequests] = useState<Request[]>([])

  const [activeRail, setActiveRail] = useState<RailKey>('images')
  const [imageView, setImageView] = useState<ImageView>('image')
  const [assembleView, setAssembleView] = useState<AssembleView>('video')
  const [sortFailedFirst, setSortFailedFirst] = useState(false)
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [reviews, setReviews] = useState<Record<string, SceneReview>>({})
  const [reviewRunning, setReviewRunning] = useState<{ sceneId: string; mode: 'light' | 'deep' } | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [retryingSceneId, setRetryingSceneId] = useState<string | null>(null)

  const { lastEvent, logs } = useWebSocketContext()

  const load = useCallback(async () => {
    const [p, v, c, s, r] = await Promise.all([
      fetchAPI<Project>(`/api/projects/${projectId}`),
      fetchAPI<Video>(`/api/videos/${videoId}`),
      fetchAPI<Character[]>(`/api/projects/${projectId}/characters`),
      fetchAPI<Scene[]>(`/api/scenes?video_id=${videoId}`),
      fetchAPI<Request[]>(`/api/requests?project_id=${projectId}`),
    ])
    setProject(p)
    setVideo(v)
    setCharacters(c)
    setScenes(s)
    setRequests(r)
  }, [projectId, videoId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!lastEvent) return
    // 'publication_update' fires when the directing engine reports a publish
    // outcome, which changes the video's youtube_id and so belongs here too.
    if (
      lastEvent.type === 'request_update' ||
      lastEvent.type === 'urls_refreshed' ||
      lastEvent.type === 'publication_update'
    ) {
      load()
    }
  }, [lastEvent, load])

  const videoRequests = requests.filter(r => r.video_id === videoId)
  const anyProcessing = videoRequests.some(r => r.status === 'PROCESSING')
  const pendingCount = videoRequests.filter(r => r.status === 'PENDING').length

  const railCtx = useMemo(
    () => ({ characters, scenes, requests, video }),
    [characters, scenes, requests, video],
  )
  const statusOf = useCallback((key: RailKey) => railStatus(key, railCtx), [railCtx])

  const logCountOf = useCallback((stages: LogStage[]) => {
    const wanted = new Set<string>(stages)
    return logs.reduce((n, r) => (r.stage && wanted.has(r.stage) ? n + 1 : n), 0)
  }, [logs])

  const activeDef = RAIL_STAGES.find(s => s.key === activeRail)!
  const activeName = t(`pipeline.railName.${activeRail}` as TranslationKey)
  const activeOwner = t(`pipeline.owner.${activeDef.owner}` as TranslationKey)

  // Which FlowKit sub-stage the grid shows, if any. Ref shows entities, not scenes.
  const gridStage: SceneStage | null =
    activeRail === 'images'
      ? (imageView === 'refs' ? null : 'image')
      : activeRail === 'assemble'
        ? assembleView
        : null

  const sheetStage: SceneStage = gridStage ?? 'image'

  let gridScenes = scenes.slice()
  if (gridStage && sortFailedFirst) {
    const rank: Record<StatusType, number> = { FAILED: 0, PROCESSING: 1, PENDING: 2, COMPLETED: 3 }
    gridScenes = gridScenes.sort(
      (a, b) => rank[sceneStageStatus(a, gridStage)] - rank[sceneStageStatus(b, gridStage)],
    )
  }

  const selectedScene = scenes.find(s => s.id === selectedSceneId) ?? null

  function openScene(sceneId: string) {
    setSelectedSceneId(sceneId)
    setSheetOpen(true)
    setReviewError(null)
  }

  async function runReview(mode: 'light' | 'deep') {
    if (!selectedScene) return
    setReviewRunning({ sceneId: selectedScene.id, mode })
    setReviewError(null)
    try {
      const result = await fetchAPI<SceneReview>(
        `/api/videos/${videoId}/scenes/${selectedScene.id}/review?project_id=${projectId}&mode=${mode}`,
        { method: 'POST' },
      )
      setReviews(prev => ({ ...prev, [selectedScene.id]: result }))
    } catch (e) {
      setReviewError(e instanceof Error ? e.message : 'Review failed')
    } finally {
      setReviewRunning(null)
    }
  }

  async function retryStage() {
    if (!selectedScene) return
    setRetryingSceneId(selectedScene.id)
    try {
      await fetchAPI('/api/requests', {
        method: 'POST',
        body: JSON.stringify({ type: RETRY_TYPE[sheetStage], scene_id: selectedScene.id, project_id: projectId, video_id: videoId }),
      })
      await load()
    } catch (e) {
      console.error(e)
    } finally {
      setRetryingSceneId(null)
    }
  }

  /** Scene grid shared by the Images and Assemble nodes. */
  function renderSceneGrid(stage: SceneStage) {
    return (
      <>
        <div className="flex items-center justify-between gap-4">
          <h2 className="m-0 text-xs tracking-widest uppercase" style={{ color: 'var(--text)' }}>
            {t('pipeline.stageHeading', { idx: activeDef.idx, name: t(`pipeline.railName.${stage}` as TranslationKey) })}
          </h2>
          <div className="flex items-center gap-2">
            <span className="text-[10px] tracking-wide uppercase" style={{ color: 'var(--muted)' }}>{t('pipeline.sort')}</span>
            <Button variant="outline" size="sm" onClick={() => setSortFailedFirst(v => !v)}>
              {sortFailedFirst ? t('pipeline.sortFailuresFirst') : t('pipeline.sortSceneOrder')}
            </Button>
          </div>
        </div>

        <div className="grid gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(268px, 1fr))' }}>
          {gridScenes.map(scene => {
            const req = latestRequest(requests, scene.id, stage)
            return (
              <SceneCard
                key={scene.id}
                scene={scene}
                stage={stage}
                retries={req?.retry_count ?? 0}
                verdict={stage === 'video' ? reviews[scene.id]?.verdict : undefined}
                onClick={() => openScene(scene.id)}
              />
            )
          })}
        </div>
      </>
    )
  }

  function renderRefsGrid() {
    return (
      <div>
        <div className="text-xs mb-2.5 font-semibold uppercase tracking-wider" style={{ color: 'var(--muted)' }}>
          {t('pipeline.refsHeading', { n: characters.length })}
        </div>
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))' }}>
          {characters.map(c => {
            const st = charStatus(c, requests)
            return (
              <div key={c.id} className="flex flex-col gap-1.5 p-2.5 rounded-md text-xs" style={{ background: 'var(--card)', border: '1px solid var(--border)' }}>
                <div className="w-full rounded overflow-hidden flex items-center justify-center" style={{ aspectRatio: '3/4', background: 'var(--surface)', maxHeight: '100px' }}>
                  {c.reference_image_url ? (
                    <img src={c.reference_image_url} alt={c.name} className="w-full h-full object-cover" />
                  ) : (
                    <span style={{ color: 'var(--muted)', fontSize: '10px' }}>{t('pipeline.noImage')}</span>
                  )}
                </div>
                <div className="font-semibold truncate" style={{ color: 'var(--text)' }}>{c.name}</div>
                <div style={{ color: 'var(--muted)', fontSize: '10px' }}>{c.entity_type}</div>
                <div className="flex items-center gap-1.5" style={{ fontSize: '10px' }}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: `var(--${st === 'COMPLETED' ? 'green' : st === 'PROCESSING' ? 'yellow' : st === 'FAILED' ? 'red' : 'border'})` }} />
                  <span style={{ color: 'var(--muted)' }}>{statusLabel(t, st)}</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  function renderVoiceover() {
    const voiced = scenes.filter(s => (s.narrator_text ?? '').trim().length > 0)
    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <h2 className="m-0 text-xs tracking-widest uppercase" style={{ color: 'var(--text)' }}>
            {t('pipeline.stageHeading', { idx: activeDef.idx, name: activeName })}
          </h2>
          <span className="text-[11px]" style={{ color: 'var(--muted)' }}>
            {t('pipeline.voiceover.coverage', { done: voiced.length, total: scenes.length })}
          </span>
        </div>

        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
          {scenes.map(s => {
            const text = (s.narrator_text ?? '').trim()
            return (
              <div
                key={s.id}
                className="flex flex-col gap-1.5 p-2.5 rounded-md"
                style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
              >
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: text ? 'var(--green)' : 'var(--border)' }} />
                  <span className="text-[11px] font-semibold" style={{ color: 'var(--text)' }}>
                    {t('sceneCard.scene', { n: s.display_order + 1 })}
                  </span>
                </div>
                <div className="text-[11px] leading-snug" style={{ color: text ? 'var(--text)' : 'var(--muted)' }}>
                  {text || t('pipeline.voiceover.noText')}
                </div>
              </div>
            )
          })}
        </div>

        <p className="m-0 text-[11px] leading-relaxed max-w-[70ch]" style={{ color: 'var(--muted)' }}>
          {t('pipeline.voiceover.caveat')}
        </p>
      </div>
    )
  }

  function renderPublish() {
    return <PublishPanel videoId={videoId} youtubeId={video?.youtube_id ?? null} />
  }

  function renderPanel() {
    switch (activeRail) {
      case 'script':
      case 'watermark':
        return <NotConnectedPanel name={activeName} system={activeOwner} />
      case 'voiceover':
        return renderVoiceover()
      case 'publish':
        return renderPublish()
      case 'images':
        return (
          <div className="flex flex-col gap-3.5">
            <Segmented
              value={imageView}
              onChange={setImageView}
              options={[
                { value: 'refs', label: t('pipeline.railName.refs') },
                { value: 'image', label: t('pipeline.railName.image') },
              ]}
            />
            {imageView === 'refs' ? renderRefsGrid() : renderSceneGrid('image')}
          </div>
        )
      case 'assemble':
        return (
          <div className="flex flex-col gap-3.5">
            <Segmented
              value={assembleView}
              onChange={setAssembleView}
              options={[
                { value: 'video', label: t('pipeline.railName.video') },
                { value: 'upscale', label: t('pipeline.railName.upscale') },
              ]}
            />
            {renderSceneGrid(assembleView)}
          </div>
        )
      default:
        return null
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-6 pb-4" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2.5 text-[10px] tracking-widest uppercase" style={{ color: 'var(--muted)' }}>
            <span style={{ color: 'var(--accent)' }}>{t('app.breadcrumbRoot')}</span>
            <span>/</span>
            <span>{project?.name ?? '…'}</span>
            <span>/</span>
            <span style={{ color: 'var(--text)' }}>{video?.title ?? '…'}</span>
          </div>
          <div className="flex items-baseline gap-3.5">
            <h1 className="m-0 text-xl font-semibold tracking-tight" style={{ color: 'var(--text)' }}>{t('pipeline.heading')}</h1>
            <span className="text-[11px]" style={{ color: 'var(--muted)' }}>{t('pipeline.sceneCount', { n: scenes.length })}</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {characters.length > 0 && (
            <div className="flex flex-col gap-1.5 items-end">
              <span className="text-[9px] tracking-widest uppercase" style={{ color: 'var(--muted)' }}>{t('pipeline.castEntities')}</span>
              <AvatarGroup>
                {characters.map(c => (
                  <Tooltip key={c.id}>
                    <TooltipTrigger asChild>
                      <Avatar>
                        <AvatarFallback>{c.name.slice(0, 2).toUpperCase()}</AvatarFallback>
                      </Avatar>
                    </TooltipTrigger>
                    <TooltipContent>
                      <div className="flex flex-col gap-1 max-w-[240px]">
                        <span className="text-[11px] tracking-wide">{c.name} · {c.entity_type}</span>
                        {c.description && <span className="text-[11px] opacity-75 leading-snug">{c.description}</span>}
                      </div>
                    </TooltipContent>
                  </Tooltip>
                ))}
              </AvatarGroup>
            </div>
          )}
          <div className="w-px h-8" style={{ background: 'var(--border)' }} />
          <div className="flex items-center gap-2">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: anyProcessing ? 'var(--yellow)' : 'var(--muted)', animation: anyProcessing ? 'pulse 1.6s ease-in-out infinite' : 'none' }}
            />
            <span className="text-[11px]" style={{ color: anyProcessing ? 'var(--yellow)' : 'var(--muted)' }}>
              {stateLabel(t, anyProcessing ? 'RUNNING' : 'IDLE')}
            </span>
            <span className="text-[11px]" style={{ color: 'var(--muted)' }}>· {t('pipeline.queue', { n: pendingCount })}</span>
          </div>
        </div>
      </div>

      <StageRail
        active={activeRail}
        onSelect={setActiveRail}
        statusOf={statusOf}
        logCountOf={logCountOf}
      />

      {renderPanel()}

      <StageLogs
        stages={activeDef.stages}
        stageLabel={activeName}
        notConnected={statusOf(activeRail).notConnected}
        onOpenConsole={() => navigate(`/logs?stage=${activeDef.stages[0]}`)}
      />

      <SceneDetailSheet
        key={selectedSceneId}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        scene={selectedScene}
        stage={sheetStage}
        stageName={t(`pipeline.railName.${sheetStage}` as TranslationKey)}
        characters={characters}
        requests={selectedScene ? requests.filter(r => r.scene_id === selectedScene.id) : []}
        review={selectedScene ? reviews[selectedScene.id] : undefined}
        reviewRunning={!!selectedScene && reviewRunning?.sceneId === selectedScene.id}
        runningMode={reviewRunning?.mode ?? null}
        reviewError={reviewError}
        onRunReview={runReview}
        onRetry={retryStage}
        retrying={!!selectedScene && retryingSceneId === selectedScene.id}
      />
    </div>
  )
}
