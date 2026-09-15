import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchAPI } from '../../api/client'
import { useWebSocketContext } from '../../api/useWebSocketContext'
import { useTranslation } from '../../i18n/useTranslation'
import type { TranslationKey } from '../../i18n/translations'
import type { Publication, PublicationListResponse, PublicationStatus } from '../../types'
import { Button } from '../ui/button'

const PUBLISHER = 'shorts_content_engine'

const STATUS_TONE: Record<PublicationStatus, string> = {
  published: 'var(--green)',
  dry_run: 'var(--yellow)',
  failed: 'var(--red)',
  requested: 'var(--accent)',
}

const STATUS_KEY: Record<PublicationStatus, TranslationKey> = {
  published: 'publish.status.published',
  dry_run: 'publish.status.dry_run',
  failed: 'publish.status.failed',
  requested: 'publish.status.requested',
}

function timeOf(ts: string | null): string {
  if (!ts) return '—'
  const m = /(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(ts)
  return m ? `${m[1]} ${m[2]}` : ts
}

interface PublishPanelProps {
  videoId: string
  /** Fallback signal for videos published before outcomes were reported here. */
  youtubeId?: string | null
}

/**
 * Per-platform publish outcomes.
 *
 * This dashboard cannot upload — publishing belongs to shorts_content_engine,
 * which is headless. So the panel reports what that engine told us and nothing
 * more.
 *
 * The rule it exists to protect: **a dry run is never rendered as a post.** A
 * simulated result gets no link (there is no URL to link to), a distinct
 * banner, and its own status label. The old behaviour — a simulated upload
 * recorded as published — made an empty pipeline look like it had shipped.
 */
export default function PublishPanel({ videoId, youtubeId }: PublishPanelProps) {
  const { t } = useTranslation()
  const { lastEvent } = useWebSocketContext()

  const [data, setData] = useState<PublicationListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [queueing, setQueueing] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await fetchAPI<PublicationListResponse>(`/api/videos/${videoId}/publications`))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load publications')
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (lastEvent?.type === 'publication_update') load()
  }, [lastEvent, load])

  /** Latest outcome per platform — the row a user actually wants to see. */
  const rows = useMemo(() => {
    const latest = new Map<string, Publication>()
    for (const p of data?.publications ?? []) {
      if (!latest.has(p.platform)) latest.set(p.platform, p)
    }
    return Array.from(latest.values()).sort((a, b) => a.platform.localeCompare(b.platform))
  }, [data])

  const summary = data?.summary

  async function retry(platform?: string) {
    const key = platform ?? '*'
    setQueueing(key)
    setNotice(null)
    try {
      const next = await fetchAPI<PublicationListResponse>(
        `/api/videos/${videoId}/publications/retry`,
        { method: 'POST', body: JSON.stringify(platform ? { platforms: [platform] } : {}) },
      )
      setData(next)
      setNotice(t('publish.retryQueued', { system: PUBLISHER }))
    } catch (e) {
      setNotice(e instanceof Error ? e.message : t('publish.retryFailed'))
    } finally {
      setQueueing(null)
    }
  }

  /** A real upload always has a URL; a simulation never does. Never invent one. */
  function renderResult(p: Publication) {
    if (p.status === 'failed') {
      return <span style={{ color: 'var(--red)' }}>{p.error_message ?? '—'}</span>
    }
    if (p.status === 'requested') {
      return <span style={{ color: 'var(--accent)' }}>{t('publish.queued', { system: PUBLISHER })}</span>
    }
    if (p.is_mock || p.status === 'dry_run') {
      return <span style={{ color: 'var(--muted)', fontStyle: 'italic' }}>{t('publish.simulated')}</span>
    }
    if (p.video_url) {
      return (
        <a
          className="underline"
          style={{ color: 'var(--accent)' }}
          href={p.video_url}
          target="_blank"
          rel="noreferrer"
        >
          {p.post_id ?? t('publish.open')}
        </a>
      )
    }
    return <span style={{ color: 'var(--muted)' }}>{p.post_id ?? t('publish.noUrl')}</span>
  }

  if (loading) {
    return (
      <div className="text-[11px] p-4" style={{ color: 'var(--muted)' }}>…</div>
    )
  }

  if (error) {
    return (
      <div
        className="flex items-center justify-between gap-4 p-4 rounded-md"
        style={{ background: 'var(--card)', border: '1px solid var(--red)' }}
      >
        <span className="text-[11px]" style={{ color: 'var(--red)' }}>{error}</span>
        <Button variant="outline" size="sm" onClick={load}>{t('publish.refresh')}</Button>
      </div>
    )
  }

  // Nothing reported yet. If the video carries a youtube_id it was published
  // before this reporting existed, which is worth saying rather than hiding.
  if (!summary || summary.total === 0) {
    return (
      <div
        className="flex flex-col gap-2 p-5 rounded-md"
        style={{ background: 'var(--card)', border: '1px dashed var(--border)' }}
      >
        <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
          {t('publish.empty')}
        </div>
        <p className="m-0 text-[11px] leading-relaxed max-w-[70ch]" style={{ color: 'var(--muted)' }}>
          {t('publish.emptyHint', { system: PUBLISHER })}
        </p>
        {youtubeId && (
          <a
            className="text-[11px] underline w-fit"
            style={{ color: 'var(--accent)' }}
            href={`https://youtu.be/${youtubeId}`}
            target="_blank"
            rel="noreferrer"
          >
            {t('pipeline.notConnected.publishDone', { id: youtubeId })}
          </a>
        )}
      </div>
    )
  }

  const retryable = rows.filter(r => r.status !== 'published' || r.is_mock)

  return (
    <div className="flex flex-col gap-3">
      {/* Honest banner: the whole point is that a dry run cannot look live. */}
      {summary.is_dry_run ? (
        <div
          className="flex flex-col gap-1.5 p-3.5 rounded-md"
          style={{ background: 'rgba(245, 158, 11, 0.10)', border: '1px solid var(--yellow)' }}
        >
          <div className="text-[12px] font-semibold tracking-wide" style={{ color: 'var(--yellow)' }}>
            {t('publish.dryRunBanner')}
          </div>
          <p className="m-0 text-[11px] leading-relaxed max-w-[75ch]" style={{ color: 'var(--muted)' }}>
            {t('publish.dryRunExplain')}
          </p>
        </div>
      ) : (
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-1 p-3.5 rounded-md text-[11px]"
          style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
        >
          <span style={{ color: summary.live > 0 ? 'var(--green)' : 'var(--muted)' }}>
            {summary.live === 1
              ? t('publish.liveBanner', { n: summary.live })
              : t('publish.liveBannerPlural', { n: summary.live })}
          </span>
          {summary.dry_run > 0 && (
            <span style={{ color: 'var(--yellow)' }}>{summary.dry_run} × {t('publish.status.dry_run')}</span>
          )}
          {summary.failed > 0 && (
            <span style={{ color: 'var(--red)' }}>{summary.failed} × {t('publish.status.failed')}</span>
          )}
          {summary.requested > 0 && (
            <span style={{ color: 'var(--accent)' }}>{summary.requested} {t('publish.status.requested')}</span>
          )}
        </div>
      )}

      {/* Per-platform outcomes */}
      <div className="rounded-md overflow-hidden" style={{ border: '1px solid var(--border)' }}>
        <div
          className="grid px-3 py-2 text-[10px] tracking-widest uppercase"
          style={{ gridTemplateColumns: '140px 110px 1fr 130px 96px', background: 'var(--surface)', color: 'var(--muted)' }}
        >
          <span>{t('publish.col.platform')}</span>
          <span>{t('publish.col.status')}</span>
          <span>{t('publish.col.result')}</span>
          <span>{t('publish.col.when')}</span>
          <span />
        </div>

        {rows.map(p => (
          <div
            key={p.id}
            className="grid px-3 py-2.5 items-center text-[11px]"
            style={{
              gridTemplateColumns: '140px 110px 1fr 130px 96px',
              borderTop: '1px solid var(--border)',
              // Simulated rows read as provisional at a glance, not just by label.
              borderLeft: `2px solid ${STATUS_TONE[p.status]}`,
              background: p.is_mock ? 'rgba(245, 158, 11, 0.04)' : 'transparent',
            }}
          >
            <span className="font-semibold" style={{ color: 'var(--text)' }}>{p.platform}</span>
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: STATUS_TONE[p.status] }} />
              <span style={{ color: STATUS_TONE[p.status] }}>{t(STATUS_KEY[p.status])}</span>
            </span>
            <span className="truncate">{renderResult(p)}</span>
            <span style={{ color: 'var(--muted)' }}>{timeOf(p.published_at ?? p.created_at)}</span>
            <span className="flex justify-end">
              {/* Offer a retry for anything that is not live and not already queued. */}
              {p.status !== 'requested' && (p.status !== 'published' || p.is_mock) && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={queueing !== null}
                  onClick={() => retry(p.platform)}
                >
                  {queueing === p.platform ? t('publish.queueing') : t('publish.retry')}
                </Button>
              )}
            </span>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-4">
        <span className="text-[10px] leading-relaxed" style={{ color: 'var(--muted)' }}>
          {t('publish.ownerNote', { system: PUBLISHER })}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="outline" size="sm" onClick={load}>{t('publish.refresh')}</Button>
          <Button
            size="sm"
            disabled={queueing !== null || retryable.length === 0}
            onClick={() => retry()}
          >
            {queueing === '*' ? t('publish.queueing') : t('publish.retryAll')}
          </Button>
        </div>
      </div>

      {retryable.length === 0 && (
        <span className="text-[10px]" style={{ color: 'var(--green)' }}>{t('publish.nothingToRetry')}</span>
      )}
      {notice && (
        <span className="text-[10px]" style={{ color: 'var(--muted)' }}>{notice}</span>
      )}
    </div>
  )
}
