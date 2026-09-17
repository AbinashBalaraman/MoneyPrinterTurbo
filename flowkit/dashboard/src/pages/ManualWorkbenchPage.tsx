import { useState, useEffect } from 'react'
import {
  Play,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Copy,
  Check,
  Clapperboard,
  Film,
  Scissors,
  Sparkles,
  UploadCloud,
  Terminal,
  FileText,
  ListOrdered,
  Layers,
  ShieldCheck,
  Clock,
  Eye,
  Music,
  Image as ImageIcon,
} from 'lucide-react'
import { fetchAPI } from '../api/client'
import { Button } from '../components/ui/button'
import { MediaPreviewCard } from '../components/media/MediaPreviewCard'

interface MediaArtifact {
  name: string
  path: string
  type: 'video' | 'image' | 'audio'
  size_bytes: number
  mtime: string
  preview_url: string
}

interface OperationSpec {
  name: string
  department: string
  risk: 'read' | 'write' | 'spend' | 'destructive'
  description: string
  args: Record<string, any>
  takes_args: boolean
}

interface OperationsResponse {
  departments: string[]
  operations: OperationSpec[]
  by_department: Record<string, OperationSpec[]>
  capabilities: {
    allow_spend: boolean
    total: number
  }
}

interface RunResult {
  success: boolean
  operation: string
  department?: string
  risk?: string
  refused?: boolean
  result?: any
  error?: string
  timestamp: string
  durationMs: number
}

const DEPARTMENT_META: Record<string, { label: string; icon: typeof Clapperboard; desc: string }> = {
  ingest: { label: '1. Ingest', icon: ListOrdered, desc: 'Topic backlog, dedup ledger & batch orchestration' },
  director: { label: '2. Director', icon: Clapperboard, desc: 'Scriptwriting, pacing, 5-phase arc & continuity' },
  render: { label: '3. Render', icon: Sparkles, desc: 'Google Flow still & video generation and queue' },
  assembly: { label: '4. Assembly', icon: Scissors, desc: 'MoneyPrinterTurbo TTS, subtitles, BGM & concat' },
  post: { label: '5. Post-Process', icon: Film, desc: 'AI watermark removal (Veo/Gemini) & metadata' },
  publish: { label: '6. Publish', icon: UploadCloud, desc: 'Multi-platform distribution (YouTube, TikTok, Reels)' },
  ops: { label: '7. Operations', icon: Terminal, desc: 'Live log bus & workspace commands' },
}

export default function ManualWorkbenchPage() {
  const [catalog, setCatalog] = useState<OperationsResponse | null>(null)
  const [loadingCatalog, setLoadingCatalog] = useState(true)
  const [activeDept, setActiveDept] = useState<string>('director')
  const [runningOp, setRunningOp] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<RunResult | null>(null)
  const [copied, setCopied] = useState(false)

  // Stage form states
  const [directSeriesId, setDirectSeriesId] = useState('farmer_and_rusty')
  const [directEpisodeNum, setDirectEpisodeNum] = useState('2')
  
  const [stillPrompt, setStillPrompt] = useState('Cinematic vertical 9:16 portrait of an old farmer looking at glowing blue light in a dry well')
  const [stillOrientation, setStillOrientation] = useState<'VERTICAL' | 'HORIZONTAL'>('VERTICAL')
  
  const [scrubInput, setScrubInput] = useState('storage/test_video.mp4')
  const [scrubProfile, setScrubProfile] = useState('veo_bottom_right')
  const [scrubMode, setScrubMode] = useState('delogo')
  
  const [assemblyBatchFile, setAssemblyBatchFile] = useState('storage/tasks/batch_01.json')
  
  const [publishSeriesId, setPublishSeriesId] = useState('farmer_and_rusty')
  const [publishEpisodeNum, setPublishEpisodeNum] = useState('1')
  const [publishPlatforms, setPublishPlatforms] = useState('youtube,tiktok,instagram')
  const [publishConfirm, setPublishConfirm] = useState(false)

  const [batchCount, setBatchCount] = useState('1')
  const [batchSeriesId, setBatchSeriesId] = useState('farmer_and_rusty')

  const [manifestJson, setManifestJson] = useState(`{
  "scenes": [
    { "duration": 6.0, "phase": "HOOK", "narrator_text": "Beneath the red dirt, something woke up.", "image_prompt": "Cinematic vertical shot of dry farm field cracking open with blue light." },
    { "duration": 7.5, "phase": "RISING", "narrator_text": "Arthur felt the vibrations through his boots.", "image_prompt": "Weathered farmer looking down with furrowed brow holding lantern." },
    { "duration": 8.0, "phase": "COMPLICATION", "narrator_text": "Rusty refused to step near the old stone well.", "image_prompt": "Golden retriever barking nervously at ancient well." },
    { "duration": 7.0, "phase": "CLIMAX", "narrator_text": "A deep mechanical humming echoed from the darkness.", "image_prompt": "Close-up of glowing ancient runes carved inside stone well." },
    { "duration": 6.5, "phase": "LOOP", "narrator_text": "And the symbol matched the key around Arthur's neck.", "image_prompt": "Arthur pulling old brass amulet from shirt in shock." }
  ]
}`)

  const [artifacts, setArtifacts] = useState<MediaArtifact[]>([])
  const [loadingArtifacts, setLoadingArtifacts] = useState(false)
  const [artifactFilter, setArtifactFilter] = useState<'all' | 'video' | 'image' | 'audio'>('all')
  const [activePreview, setActivePreview] = useState<{ src: string; title?: string; type?: 'video' | 'image' | 'audio'; fileSize?: string } | null>(null)

  // Queue monitoring & batch scheduling states
  const [autoPollQueue, setAutoPollQueue] = useState(false)
  const [queueSummary, setQueueSummary] = useState<{ total?: number; outstanding?: number; request_counts?: Record<string, number> } | null>(null)
  
  const [scheduleIntervalHours, setScheduleIntervalHours] = useState('0')
  const [isScheduled, setIsScheduled] = useState(false)
  const [nextScheduleTime, setNextScheduleTime] = useState<string | null>(null)

  useEffect(() => {
    loadCatalog()
    loadArtifacts()
  }, [])

  // Auto-polling queue monitor
  useEffect(() => {
    if (!autoPollQueue) return
    const fetchQueue = async () => {
      try {
        const res = await fetchAPI<any>('/api/operations/run', {
          method: 'POST',
          body: JSON.stringify({ name: 'queue_status', args: {} }),
        })
        if (res?.success && res.result) {
          setQueueSummary(res.result)
        }
      } catch (e) {
        console.debug('Auto poll failed:', e)
      }
    }
    fetchQueue()
    const interval = setInterval(fetchQueue, 4000)
    return () => clearInterval(interval)
  }, [autoPollQueue])

  // Batch automation scheduler
  useEffect(() => {
    if (!isScheduled || scheduleIntervalHours === '0') {
      setNextScheduleTime(null)
      return
    }
    const hours = parseFloat(scheduleIntervalHours)
    const ms = hours * 3600 * 1000
    const next = new Date(Date.now() + ms)
    setNextScheduleTime(next.toLocaleTimeString())

    const timer = setTimeout(() => {
      executeOperation('run_batch', {
        series_id: batchSeriesId,
        episodes: parseInt(batchCount) || 1,
      })
      const nextRun = new Date(Date.now() + ms)
      setNextScheduleTime(nextRun.toLocaleTimeString())
    }, ms)

    return () => clearTimeout(timer)
  }, [isScheduled, scheduleIntervalHours, batchSeriesId, batchCount])

  const loadArtifacts = async () => {
    setLoadingArtifacts(true)
    try {
      const data = await fetchAPI<{ artifacts: MediaArtifact[]; total: number }>('/api/media/artifacts?limit=25')
      setArtifacts(data.artifacts || [])
    } catch (err) {
      console.debug('Failed to load media artifacts:', err)
    } finally {
      setLoadingArtifacts(false)
    }
  }

  const extractMedia = (res: any): { src: string; type?: 'video' | 'image' | 'audio'; title?: string } | null => {
    if (!res) return null
    const candidates: string[] = []
    const collect = (obj: any) => {
      if (!obj) return
      if (typeof obj === 'string') {
        if (obj.match(/\.(mp4|webm|mov|mkv|png|jpg|jpeg|webp|mp3|wav|ogg)$/i)) {
          candidates.push(obj)
        }
        return
      }
      if (typeof obj === 'object') {
        for (const k of ['clean_path', 'output_path', 'out_path', 'video_path', 'image_path', 'path', 'file', 'preview_url']) {
          if (obj[k] && typeof obj[k] === 'string' && obj[k].match(/\.(mp4|webm|mov|mkv|png|jpg|jpeg|webp|mp3|wav|ogg)$/i)) {
            candidates.push(obj[k])
          }
        }
        for (const val of Object.values(obj)) {
          collect(val)
        }
      }
    }
    collect(res)
    if (candidates.length > 0) {
      const src = candidates[0]
      const lower = src.toLowerCase()
      const type = (lower.endsWith('.mp4') || lower.endsWith('.webm') || lower.endsWith('.mov'))
        ? 'video'
        : (lower.endsWith('.mp3') || lower.endsWith('.wav'))
        ? 'audio'
        : 'image'
      return { src, type, title: src.split(/[\\/]/).pop() }
    }
    return null
  }

  const loadCatalog = async () => {
    setLoadingCatalog(true)
    try {
      const data = await fetchAPI<OperationsResponse>('/api/operations')
      setCatalog(data)
    } catch (err) {
      console.error('Failed to load operations catalog:', err)
    } finally {
      setLoadingCatalog(false)
    }
  }

  const executeOperation = async (name: string, args: Record<string, any> = {}, confirm = false) => {
    setRunningOp(name)
    const startTime = performance.now()
    try {
      const res = await fetchAPI<{
        success: boolean
        operation: string
        department?: string
        risk?: string
        refused?: boolean
        result?: any
        error?: string
      }>('/api/operations/run', {
        method: 'POST',
        body: JSON.stringify({ name, args, confirm }),
      })
      const durationMs = Math.round(performance.now() - startTime)
      setLastResult({
        ...res,
        timestamp: new Date().toLocaleTimeString(),
        durationMs,
      })

      // Auto-preview detected media artifact
      const media = extractMedia(res.result)
      if (media) {
        setActivePreview(media)
      }
      // Refresh artifacts list
      loadArtifacts()
    } catch (err: any) {
      const durationMs = Math.round(performance.now() - startTime)
      setLastResult({
        success: false,
        operation: name,
        error: err.message || String(err),
        timestamp: new Date().toLocaleTimeString(),
        durationMs,
      })
    } finally {
      setRunningOp(null)
    }
  }

  const copyResult = () => {
    if (!lastResult) return
    navigator.clipboard.writeText(JSON.stringify(lastResult, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const getRiskBadge = (risk: string) => {
    switch (risk) {
      case 'spend':
        return (
          <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-semibold tracking-wider">
            SPENDS MONEY
          </span>
        )
      case 'destructive':
        return (
          <span className="text-[10px] px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 font-semibold tracking-wider">
            DESTRUCTIVE · LIVE
          </span>
        )
      case 'write':
        return (
          <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-semibold tracking-wider">
            WRITE
          </span>
        )
      default:
        return (
          <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold tracking-wider">
            READ-ONLY
          </span>
        )
    }
  }

  return (
    <div className="flex flex-col h-full gap-5 pb-8 max-w-7xl mx-auto">
      {/* Top Banner */}
      <div
        className="rounded-xl p-5 border flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2.5">
            <Layers className="text-blue-400" size={18} />
            <h1 className="text-base font-bold tracking-tight">Manual Workbench</h1>
            <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase font-semibold">
              Component Controls
            </span>
          </div>
          <p className="text-xs" style={{ color: 'var(--muted)' }}>
            Access and run individual parts of the combined AutoShorts engine manually. Test scripts, render stills, cut video, scrub watermarks, or publish on demand.
          </p>
        </div>

        <div className="flex items-center gap-3 text-xs">
          <div
            className="flex items-center gap-2 px-3 py-1.5 rounded border"
            style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
          >
            <span
              className="w-2 h-2 rounded-full"
              style={{ background: catalog?.capabilities.allow_spend ? 'var(--green)' : 'var(--yellow)' }}
            />
            <span style={{ color: 'var(--muted)' }}>Spend Gate:</span>
            <span className="font-semibold" style={{ color: 'var(--text)' }}>
              {catalog?.capabilities.allow_spend ? 'Enabled' : 'Gated (Opt-in)'}
            </span>
          </div>

          <Button
            size="sm"
            variant="outline"
            onClick={loadCatalog}
            disabled={loadingCatalog}
            className="h-8 gap-1.5 text-xs"
          >
            <RefreshCw size={13} className={loadingCatalog ? 'animate-spin' : ''} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Recent Media Artifacts Strip */}
      <div
        className="rounded-xl border p-3 flex flex-col gap-2.5 transition-all"
        style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold">
            <Film size={14} className="text-emerald-400" />
            <span>Recent Pipeline Artifacts ({artifacts.length})</span>
            <span className="text-[10px] text-zinc-500 font-normal">
              Direct media playback from storage/ and output/
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            {(['all', 'video', 'image', 'audio'] as const).map((filter) => (
              <button
                key={filter}
                onClick={() => setArtifactFilter(filter)}
                className={`px-2 py-0.5 rounded text-[10px] uppercase font-mono transition-colors ${
                  artifactFilter === filter
                    ? 'bg-blue-600 text-white font-semibold'
                    : 'bg-zinc-800/80 text-zinc-400 hover:text-zinc-200'
                }`}
              >
                {filter}
              </button>
            ))}

            <button
              onClick={loadArtifacts}
              disabled={loadingArtifacts}
              title="Refresh artifacts"
              className="p-1 rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition ml-1"
            >
              <RefreshCw size={12} className={loadingArtifacts ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Artifact Chips Scrollbar */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs">
          {artifacts
            .filter((a) => artifactFilter === 'all' || a.type === artifactFilter)
            .map((art) => {
              const isSelected = activePreview?.src === art.preview_url || activePreview?.src === art.path
              return (
                <button
                  key={art.path}
                  onClick={() =>
                    setActivePreview({
                      src: art.preview_url,
                      title: art.name,
                      type: art.type,
                      fileSize: (art.size_bytes / (1024 * 1024)).toFixed(1) + ' MB',
                    })
                  }
                  className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-left shrink-0 transition-all ${
                    isSelected
                      ? 'bg-blue-600/20 border-blue-500 text-blue-300 shadow-md'
                      : 'bg-zinc-900/90 border-zinc-800 hover:border-zinc-700 text-zinc-300 hover:bg-zinc-850'
                  }`}
                >
                  {art.type === 'video' && <Film size={12} className="text-emerald-400 shrink-0" />}
                  {art.type === 'image' && <ImageIcon size={12} className="text-sky-400 shrink-0" />}
                  {art.type === 'audio' && <Music size={12} className="text-violet-400 shrink-0" />}
                  <div className="flex flex-col min-w-0">
                    <span className="text-[11px] font-medium truncate max-w-[140px]">{art.name}</span>
                    <span className="text-[9px] text-zinc-500 font-mono">
                      {(art.size_bytes / (1024 * 1024)).toFixed(1)}MB
                    </span>
                  </div>
                </button>
              )
            })}
          {artifacts.length === 0 && !loadingArtifacts && (
            <span className="text-[11px] text-zinc-500 py-1 italic">
              No media artifacts generated yet. Run an image generation, assembly or scrubber operation below.
            </span>
          )}
        </div>
      </div>

      {/* Main Grid: Department Stage Navigator & Interactive Workbench */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 flex-1">
        {/* Left Rail: Department Stage Buttons */}
        <div className="lg:col-span-3 flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold tracking-wider uppercase px-2 mb-1" style={{ color: 'var(--muted)' }}>
            Pipeline Departments
          </span>
          {Object.entries(DEPARTMENT_META).map(([deptKey, meta]) => {
            const Icon = meta.icon
            const isActive = activeDept === deptKey
            const deptOps = catalog?.by_department[deptKey] || []
            return (
              <button
                key={deptKey}
                onClick={() => setActiveDept(deptKey)}
                className="flex items-start gap-3 p-3 rounded-lg border text-left transition-all hover:opacity-90"
                style={{
                  background: isActive ? 'var(--card)' : 'transparent',
                  borderColor: isActive ? 'var(--accent)' : 'var(--border)',
                }}
              >
                <div
                  className="p-1.5 rounded mt-0.5"
                  style={{
                    background: isActive ? 'var(--accent)' : 'var(--surface)',
                    color: isActive ? 'white' : 'var(--muted)',
                  }}
                >
                  <Icon size={16} />
                </div>
                <div className="flex flex-col flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold" style={{ color: isActive ? 'var(--text)' : 'var(--muted)' }}>
                      {meta.label}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.2 rounded" style={{ background: 'var(--surface)', color: 'var(--muted)' }}>
                      {deptOps.length}
                    </span>
                  </div>
                  <span className="text-[10px] truncate mt-0.5" style={{ color: 'var(--muted)' }}>
                    {meta.desc}
                  </span>
                </div>
              </button>
            )
          })}
        </div>

        {/* Center/Right: Department Interactive Action Cards */}
        <div className="lg:col-span-9 flex flex-col gap-5">
          {/* Department Header */}
          <div
            className="p-4 rounded-lg border flex items-center justify-between"
            style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
          >
            <div>
              <h2 className="text-sm font-bold tracking-tight">
                {DEPARTMENT_META[activeDept]?.label || activeDept}
              </h2>
              <p className="text-xs mt-0.5" style={{ color: 'var(--muted)' }}>
                {DEPARTMENT_META[activeDept]?.desc}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[11px]" style={{ color: 'var(--muted)' }}>Available Tools:</span>
              <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-blue-500/10 text-blue-400">
                {catalog?.by_department[activeDept]?.length || 0}
              </span>
            </div>
          </div>

          {/* Department Panels */}

          {/* 1. INGEST PANEL */}
          {activeDept === 'ingest' && (
            <div className="flex flex-col gap-4">
              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ListOrdered size={15} className="text-blue-400" />
                    <span className="text-xs font-bold">List Topic Backlog & Ledger</span>
                  </div>
                  {getRiskBadge('read')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Inspects unclaimed and processed topics in <code className="text-xs">automation/topics.txt</code> alongside ledger states.
                </p>
                <div className="flex items-center gap-2 pt-2">
                  <Button
                    size="sm"
                    onClick={() => executeOperation('list_topics')}
                    disabled={runningOp === 'list_topics'}
                    className="h-8 gap-2 text-xs"
                  >
                    <Play size={13} />
                    Run list_topics
                  </Button>
                </div>
              </div>

              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Play size={15} className="text-amber-400" />
                    <span className="text-xs font-bold">Run Batch Pipeline</span>
                  </div>
                  {getRiskBadge('spend')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Runs N episodes through the unattended loop (direct → generate stills → assemble).
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Series ID</label>
                    <input
                      type="text"
                      value={batchSeriesId}
                      onChange={e => setBatchSeriesId(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Episodes Count</label>
                    <input
                      type="number"
                      min="1"
                      max="10"
                      value={batchCount}
                      onChange={e => setBatchCount(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                </div>
                <div className="pt-2">
                  <Button
                    size="sm"
                    onClick={() => executeOperation('run_batch', { series_id: batchSeriesId, episodes: parseInt(batchCount) || 1 })}
                    disabled={runningOp === 'run_batch'}
                    className="h-8 gap-2 text-xs bg-amber-600 hover:bg-amber-700"
                  >
                    <Play size={13} />
                    Execute Batch Run
                  </Button>
                </div>
              </div>

              {/* Scheduled Batch Execution Card */}
              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Clock size={15} className="text-violet-400" />
                    <span className="text-xs font-bold">Series Batch Automation &amp; Scheduler</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-semibold uppercase ${isScheduled ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-zinc-800 text-zinc-400'}`}>
                      {isScheduled ? 'ACTIVE SCHEDULE' : 'STANDBY'}
                    </span>
                  </div>
                  {getRiskBadge('spend')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Set an automated timer or interval to run multi-episode batches unattended in the background.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Interval Trigger</label>
                    <select
                      value={scheduleIntervalHours}
                      onChange={e => setScheduleIntervalHours(e.target.value)}
                      disabled={isScheduled}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    >
                      <option value="0">Manual / Off</option>
                      <option value="1">Every 1 Hour</option>
                      <option value="6">Every 6 Hours</option>
                      <option value="12">Every 12 Hours</option>
                      <option value="24">Daily (Every 24 Hours)</option>
                    </select>
                  </div>
                  <div className="md:col-span-2 flex flex-col justify-end">
                    <div className="flex items-center justify-between text-xs py-1.5 px-3 rounded border font-mono" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
                      <span className="text-zinc-400">Next Scheduled Trigger:</span>
                      <span className="font-semibold text-zinc-200">
                        {isScheduled && nextScheduleTime ? nextScheduleTime : 'Not scheduled'}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="pt-2 flex items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() => setIsScheduled(!isScheduled)}
                    disabled={scheduleIntervalHours === '0'}
                    className={`h-8 gap-2 text-xs font-semibold ${isScheduled ? 'bg-red-600 hover:bg-red-700 text-white' : 'bg-violet-600 hover:bg-violet-700 text-white'}`}
                  >
                    <Clock size={13} />
                    {isScheduled ? 'Pause Scheduled Automation' : 'Arm Batch Schedule'}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* 2. DIRECTOR PANEL */}
          {activeDept === 'director' && (
            <div className="flex flex-col gap-4">
              {/* Direct Episode */}
              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Clapperboard size={15} className="text-blue-400" />
                    <span className="text-xs font-bold">Direct Next Episode</span>
                  </div>
                  {getRiskBadge('write')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Generates an episode script with 5-phase retention arc and scene-to-prompt decoupling via SCE CLI.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Series ID</label>
                    <input
                      type="text"
                      value={directSeriesId}
                      onChange={e => setDirectSeriesId(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Episode Index</label>
                    <input
                      type="number"
                      value={directEpisodeNum}
                      onChange={e => setDirectEpisodeNum(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                </div>
                <div className="pt-2">
                  <Button
                    size="sm"
                    onClick={() => executeOperation('direct_episode', { series_id: directSeriesId, episode: parseInt(directEpisodeNum) || 1 })}
                    disabled={runningOp === 'direct_episode'}
                    className="h-8 gap-2 text-xs"
                  >
                    <Play size={13} />
                    Direct Episode
                  </Button>
                </div>
              </div>

              {/* Validate Script */}
              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileText size={15} className="text-emerald-400" />
                    <span className="text-xs font-bold">Validate Script Manifest</span>
                  </div>
                  {getRiskBadge('read')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Checks strict constraints: 4–6 scenes, ≤10.0s per scene, 30–50s total, and 5-phase retention arc.
                </p>
                <textarea
                  rows={6}
                  value={manifestJson}
                  onChange={e => setManifestJson(e.target.value)}
                  className="w-full p-2.5 rounded text-[11px] font-mono border outline-none"
                  style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                />
                <div className="pt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      try {
                        const parsed = JSON.parse(manifestJson)
                        executeOperation('validate_script', { manifest: parsed })
                      } catch (e: any) {
                        setLastResult({
                          success: false,
                          operation: 'validate_script',
                          error: `Invalid JSON format: ${e.message}`,
                          timestamp: new Date().toLocaleTimeString(),
                          durationMs: 0,
                        })
                      }
                    }}
                    disabled={runningOp === 'validate_script'}
                    className="h-8 gap-2 text-xs"
                  >
                    <CheckCircle2 size={13} />
                    Run validate_script
                  </Button>
                </div>
              </div>

              {/* Continuity Status */}
              <div className="p-4 rounded-lg border flex items-center justify-between" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold">Check Series Continuity</span>
                    {getRiskBadge('read')}
                  </div>
                  <p className="text-[11px] mt-0.5" style={{ color: 'var(--muted)' }}>
                    Inspects series canon, unresolved cliffhangers and character relationships in SQLite WAL.
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => executeOperation('continuity_status', { series_id: directSeriesId })}
                  disabled={runningOp === 'continuity_status'}
                  className="h-8 gap-2 text-xs"
                >
                  <Play size={13} />
                  Check Continuity
                </Button>
              </div>
            </div>
          )}

          {/* 3. RENDER (FLOWKIT) PANEL */}
          {activeDept === 'render' && (
            <div className="flex flex-col gap-4">
              {/* Standalone Image Generator */}
              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Sparkles size={15} className="text-amber-400" />
                    <span className="text-xs font-bold">Generate Standalone Flow Still</span>
                  </div>
                  {getRiskBadge('spend')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Queues a single high-fidelity still in Google Flow via Chrome extension bridge.
                </p>
                <div className="flex flex-col gap-2.5">
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Prompt</label>
                    <input
                      type="text"
                      value={stillPrompt}
                      onChange={e => setStillPrompt(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                  <div className="flex items-center gap-4">
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted)' }}>Orientation:</label>
                    <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                      <input
                        type="radio"
                        checked={stillOrientation === 'VERTICAL'}
                        onChange={() => setStillOrientation('VERTICAL')}
                      />
                      <span>Vertical 9:16</span>
                    </label>
                    <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                      <input
                        type="radio"
                        checked={stillOrientation === 'HORIZONTAL'}
                        onChange={() => setStillOrientation('HORIZONTAL')}
                      />
                      <span>Horizontal 16:9</span>
                    </label>
                  </div>
                </div>
                <div className="pt-2">
                  <Button
                    size="sm"
                    onClick={() => executeOperation('generate_image', { prompt: stillPrompt, orientation: stillOrientation })}
                    disabled={runningOp === 'generate_image'}
                    className="h-8 gap-2 text-xs bg-amber-600 hover:bg-amber-700"
                  >
                    <Sparkles size={13} />
                    Queue generate_image
                  </Button>
                </div>
              </div>

              {/* Status & Consistency Quick Checks */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="p-4 rounded-lg border flex flex-col justify-between gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                  <div>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-bold">Queue Monitor</span>
                        {autoPollQueue && (
                          <span className="flex h-2 w-2 relative">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                          </span>
                        )}
                      </div>
                      {getRiskBadge('read')}
                    </div>
                    <p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>
                      Inspects pending, processing and settled generation requests.
                    </p>

                    {queueSummary && (
                      <div className="mt-2.5 p-2 rounded border bg-zinc-900/80 border-zinc-800 text-[11px] font-mono flex items-center justify-between">
                        <span className="text-zinc-400">Total: <strong className="text-zinc-200">{queueSummary.total ?? 0}</strong></span>
                        <span className="text-amber-400">Outstanding: <strong>{queueSummary.outstanding ?? 0}</strong></span>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 pt-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => executeOperation('queue_status')}
                      disabled={runningOp === 'queue_status'}
                      className="h-8 gap-2 text-xs flex-1"
                    >
                      <Play size={13} />
                      Poll Now
                    </Button>
                    <Button
                      size="sm"
                      variant={autoPollQueue ? 'default' : 'outline'}
                      onClick={() => setAutoPollQueue(!autoPollQueue)}
                      className={`h-8 gap-1.5 text-xs ${autoPollQueue ? 'bg-emerald-600 hover:bg-emerald-700 text-white' : ''}`}
                    >
                      <RefreshCw size={12} className={autoPollQueue ? 'animate-spin' : ''} />
                      {autoPollQueue ? 'Auto (4s)' : 'Auto Poll'}
                    </Button>
                  </div>
                </div>

                <div className="p-4 rounded-lg border flex flex-col justify-between gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold">Reference Conditioning</span>
                      {getRiskBadge('read')}
                    </div>
                    <p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>
                      Audits scenes generated without reference image conditioning.
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => executeOperation('consistency_check')}
                    disabled={runningOp === 'consistency_check'}
                    className="h-8 gap-2 text-xs"
                  >
                    <Play size={13} />
                    Check consistency_check
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* 4. ASSEMBLY (MONEYPRINTERTURBO) PANEL */}
          {activeDept === 'assembly' && (
            <div className="flex flex-col gap-4">
              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Scissors size={15} className="text-amber-400" />
                    <span className="text-xs font-bold">Video Assembly Engine (MoneyPrinterTurbo)</span>
                  </div>
                  {getRiskBadge('spend')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Executes the root <code className="text-xs">cli.py --batch-file</code> assembly pipeline: TTS narration, automated subtitle timing, background music mixing and video concatenation.
                </p>
                <div>
                  <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Task / Batch File Path</label>
                  <input
                    type="text"
                    value={assemblyBatchFile}
                    onChange={e => setAssemblyBatchFile(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                    style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                  />
                  <span className="text-[10px] mt-1 block" style={{ color: 'var(--muted)' }}>
                    Relative to AutoShorts workspace root or absolute path.
                  </span>
                </div>
                <div className="pt-2">
                  <Button
                    size="sm"
                    onClick={() => executeOperation('assemble_episode', { batch_file: assemblyBatchFile })}
                    disabled={runningOp === 'assemble_episode'}
                    className="h-8 gap-2 text-xs bg-amber-600 hover:bg-amber-700"
                  >
                    <Scissors size={13} />
                    Run assemble_episode
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* 5. POST-PROCESS PANEL */}
          {activeDept === 'post' && (
            <div className="flex flex-col gap-4">
              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Film size={15} className="text-blue-400" />
                    <span className="text-xs font-bold">AI Watermark Scrub & Metadata Cleaner</span>
                  </div>
                  {getRiskBadge('write')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Removes bottom-right synthetic watermarks (Google Veo / Gemini) and scrubs container metadata from MP4 video.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="md:col-span-3">
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Input MP4 File Path</label>
                    <input
                      type="text"
                      value={scrubInput}
                      onChange={e => setScrubInput(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Profile</label>
                    <select
                      value={scrubProfile}
                      onChange={e => setScrubProfile(e.target.value)}
                      className="w-full px-2 py-1.5 rounded text-xs border outline-none"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    >
                      <option value="veo_bottom_right">Veo Bottom-Right (Google Flow)</option>
                      <option value="gemini_bottom_right">Gemini Bottom-Right</option>
                      <option value="custom">Custom Coordinates</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Removal Mode</label>
                    <select
                      value={scrubMode}
                      onChange={e => setScrubMode(e.target.value)}
                      className="w-full px-2 py-1.5 rounded text-xs border outline-none"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    >
                      <option value="delogo">Delogo (Inpainting removal)</option>
                      <option value="boxblur">Box Blur (Fast blur filter)</option>
                    </select>
                  </div>
                </div>
                <div className="pt-2">
                  <Button
                    size="sm"
                    onClick={() => executeOperation('scrub_video', { input_path: scrubInput, profile: scrubProfile, mode: scrubMode })}
                    disabled={runningOp === 'scrub_video'}
                    className="h-8 gap-2 text-xs"
                  >
                    <Film size={13} />
                    Execute scrub_video
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* 6. PUBLISH PANEL */}
          {activeDept === 'publish' && (
            <div className="flex flex-col gap-4">
              <div className="p-4 rounded-lg border flex flex-col gap-3" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <UploadCloud size={15} className="text-red-400" />
                    <span className="text-xs font-bold">Multi-Platform Publisher</span>
                  </div>
                  {getRiskBadge('destructive')}
                </div>
                <p className="text-xs" style={{ color: 'var(--muted)' }}>
                  Uploads completed video to YouTube Shorts, TikTok, and Instagram Reels. Public and irreversible.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Series ID</label>
                    <input
                      type="text"
                      value={publishSeriesId}
                      onChange={e => setPublishSeriesId(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Episode Number</label>
                    <input
                      type="number"
                      value={publishEpisodeNum}
                      onChange={e => setPublishEpisodeNum(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="text-[11px] block mb-1 font-semibold" style={{ color: 'var(--muted)' }}>Platforms (comma-separated)</label>
                    <input
                      type="text"
                      value={publishPlatforms}
                      onChange={e => setPublishPlatforms(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded text-xs border outline-none font-mono"
                      style={{ background: 'var(--surface)', borderColor: 'var(--border)', color: 'var(--text)' }}
                    />
                  </div>
                </div>

                <div className="p-3 rounded border flex items-center gap-3 bg-red-500/5 border-red-500/20">
                  <input
                    type="checkbox"
                    id="confirm-publish"
                    checked={publishConfirm}
                    onChange={e => setPublishConfirm(e.target.checked)}
                    className="rounded text-red-500 cursor-pointer"
                  />
                  <label htmlFor="confirm-publish" className="text-xs cursor-pointer text-red-300">
                    I explicitly confirm this upload to live public platforms (<code className="text-xs">confirm: true</code>).
                  </label>
                </div>

                <div className="flex items-center gap-3 pt-2">
                  <Button
                    size="sm"
                    onClick={() => executeOperation('publish_episode', {
                      series_id: publishSeriesId,
                      episode: parseInt(publishEpisodeNum) || 1,
                      platforms: publishPlatforms,
                      confirm: publishConfirm,
                    }, publishConfirm)}
                    disabled={runningOp === 'publish_episode'}
                    className="h-8 gap-2 text-xs bg-red-600 hover:bg-red-700"
                  >
                    <UploadCloud size={13} />
                    Publish Live Episode
                  </Button>

                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => executeOperation('publication_status')}
                    disabled={runningOp === 'publication_status'}
                    className="h-8 gap-2 text-xs"
                  >
                    Check publication_status
                  </Button>
                </div>
              </div>

              {/* Credentials & Distribution Health Check Card */}
              <div className="p-4 rounded-lg border flex items-center justify-between" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div>
                  <div className="flex items-center gap-2">
                    <ShieldCheck size={15} className="text-emerald-400" />
                    <span className="text-xs font-bold">Platform OAuth &amp; Distribution Credentials</span>
                    {getRiskBadge('read')}
                  </div>
                  <p className="text-[11px] mt-0.5" style={{ color: 'var(--muted)' }}>
                    Check if YouTube, TikTok, and Instagram API tokens are configured before publishing.
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => executeOperation('credentials_status')}
                  disabled={runningOp === 'credentials_status'}
                  className="h-8 gap-2 text-xs"
                >
                  <ShieldCheck size={13} />
                  Verify Credentials
                </Button>
              </div>
            </div>
          )}

          {/* 7. OPS PANEL */}
          {activeDept === 'ops' && (
            <div className="flex flex-col gap-4">
              <div className="p-4 rounded-lg border flex items-center justify-between" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div>
                  <div className="flex items-center gap-2">
                    <Terminal size={15} className="text-emerald-400" />
                    <span className="text-xs font-bold">Read Recent Logs</span>
                    {getRiskBadge('read')}
                  </div>
                  <p className="text-[11px] mt-0.5" style={{ color: 'var(--muted)' }}>
                    Fetch recent records directly from the live backend LogBus.
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => executeOperation('read_logs', { limit: 25 })}
                  disabled={runningOp === 'read_logs'}
                  className="h-8 gap-2 text-xs"
                >
                  <Play size={13} />
                  Fetch Logs
                </Button>
              </div>

              <div className="p-4 rounded-lg border flex items-center justify-between" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div>
                  <div className="flex items-center gap-2">
                    <ShieldCheck size={15} className="text-sky-400" />
                    <span className="text-xs font-bold">Pipeline API Key &amp; Environment Audit</span>
                    {getRiskBadge('read')}
                  </div>
                  <p className="text-[11px] mt-0.5" style={{ color: 'var(--muted)' }}>
                    Audit Google Flow, OpenCode, Suno, ElevenLabs, and social distribution tokens across .env.
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => executeOperation('credentials_status')}
                  disabled={runningOp === 'credentials_status'}
                  className="h-8 gap-2 text-xs"
                >
                  <ShieldCheck size={13} />
                  Audit Environment
                </Button>
              </div>
            </div>
          )}

          {/* Results Console */}
          <div
            className="rounded-lg border flex flex-col overflow-hidden"
            style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
          >
            <div
              className="px-4 py-2.5 border-b flex items-center justify-between text-xs font-semibold"
              style={{ borderColor: 'var(--border)', background: 'var(--card)' }}
            >
              <div className="flex items-center gap-2">
                <Terminal size={14} className="text-blue-400" />
                <span>Execution Output Console</span>
                {runningOp && (
                  <span className="flex items-center gap-1.5 text-[11px] text-blue-400">
                    <RefreshCw size={11} className="animate-spin" />
                    Running {runningOp}...
                  </span>
                )}
              </div>
              {lastResult && (
                <div className="flex items-center gap-3">
                  <span className="text-[10px] font-mono" style={{ color: 'var(--muted)' }}>
                    {lastResult.durationMs}ms · {lastResult.timestamp}
                  </span>
                  <button
                    onClick={copyResult}
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border transition-colors hover:opacity-80"
                    style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}
                  >
                    {copied ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                    {copied ? 'Copied' : 'Copy JSON'}
                  </button>
                </div>
              )}
            </div>

            {/* Active Media Preview Player */}
            {activePreview && (
              <div className="p-4 border-b border-zinc-800/80 bg-zinc-950/60">
                <MediaPreviewCard
                  src={activePreview.src}
                  title={activePreview.title}
                  type={activePreview.type}
                  fileSize={activePreview.fileSize}
                  onClose={() => setActivePreview(null)}
                />
              </div>
            )}

            <div className="p-4 overflow-auto max-h-80 min-h-32 text-xs font-mono" style={{ background: '#090913' }}>
              {lastResult ? (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {lastResult.success ? (
                        <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">
                          <CheckCircle2 size={12} /> SUCCESS: {lastResult.operation}
                        </span>
                      ) : lastResult.refused ? (
                        <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold">
                          <AlertTriangle size={12} /> REFUSED: {lastResult.operation}
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-red-500/10 text-red-400 border border-red-500/20 font-bold">
                          <XCircle size={12} /> ERROR: {lastResult.operation}
                        </span>
                      )}
                    </div>

                    {extractMedia(lastResult.result) && !activePreview && (
                      <button
                        onClick={() => {
                          const m = extractMedia(lastResult.result)
                          if (m) setActivePreview(m)
                        }}
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-blue-600/20 border border-blue-500/40 text-blue-300 text-xs font-medium hover:bg-blue-600/30 transition"
                      >
                        <Eye size={12} />
                        Preview Artifact
                      </button>
                    )}
                  </div>
                  <pre className="whitespace-pre-wrap leading-relaxed text-[11px]" style={{ color: lastResult.success ? '#93c5fd' : '#fca5a5' }}>
                    {JSON.stringify(lastResult.result || lastResult.error || lastResult, null, 2)}
                  </pre>
                </div>
              ) : (
                <span className="text-[11px]" style={{ color: 'var(--muted)' }}>
                  No operation executed yet. Select a pipeline department above and click Run to see live results here.
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
