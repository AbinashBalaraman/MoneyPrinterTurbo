import { useState, useRef, useEffect } from 'react'
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Download,
  Film,
  Music,
  Image as ImageIcon,
  Copy,
  Check,
  Smartphone,
  Monitor,
} from 'lucide-react'

interface MediaPreviewProps {
  src: string
  title?: string
  type?: 'video' | 'image' | 'audio' | 'auto'
  aspectRatio?: '9:16' | '16:9' | 'auto'
  fileSize?: string | number
  onClose?: () => void
}

export function MediaPreviewCard({
  src,
  title,
  type = 'auto',
  aspectRatio = '9:16',
  fileSize,
  onClose,
}: MediaPreviewProps) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [isVertical, setIsVertical] = useState(aspectRatio === '9:16')
  const [copied, setCopied] = useState(false)

  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  // Detect type if auto
  const detectedType = (() => {
    if (type !== 'auto') return type
    const lower = src.toLowerCase()
    if (lower.endsWith('.mp4') || lower.endsWith('.webm') || lower.endsWith('.mov') || lower.endsWith('.mkv')) return 'video'
    if (lower.endsWith('.mp3') || lower.endsWith('.wav') || lower.endsWith('.ogg') || lower.endsWith('.m4a')) return 'audio'
    return 'image'
  })()

  // Ensure src points to /api/media/file if it's a relative path or direct path
  const resolvedSrc = (() => {
    if (src.startsWith('http://') || src.startsWith('https://') || src.startsWith('data:') || src.startsWith('blob:')) {
      return src
    }
    if (src.startsWith('/api/media/file')) {
      return src
    }
    return `/api/media/file?path=${encodeURIComponent(src)}`
  })()

  useEffect(() => {
    setIsPlaying(false)
    setCurrentTime(0)
  }, [src])

  const togglePlay = () => {
    if (detectedType === 'video' && videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause()
      } else {
        videoRef.current.play()
      }
      setIsPlaying(!isPlaying)
    } else if (detectedType === 'audio' && audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause()
      } else {
        audioRef.current.play()
      }
      setIsPlaying(!isPlaying)
    }
  }

  const toggleMute = () => {
    if (detectedType === 'video' && videoRef.current) {
      videoRef.current.muted = !isMuted
      setIsMuted(!isMuted)
    } else if (detectedType === 'audio' && audioRef.current) {
      audioRef.current.muted = !isMuted
      setIsMuted(!isMuted)
    }
  }

  const handleTimeUpdate = () => {
    if (detectedType === 'video' && videoRef.current) {
      setCurrentTime(videoRef.current.currentTime)
    } else if (detectedType === 'audio' && audioRef.current) {
      setCurrentTime(audioRef.current.currentTime)
    }
  }

  const handleLoadedMetadata = () => {
    if (detectedType === 'video' && videoRef.current) {
      setDuration(videoRef.current.duration)
      // Auto-detect aspect ratio from intrinsic video dimensions
      if (videoRef.current.videoHeight > videoRef.current.videoWidth) {
        setIsVertical(true)
      } else if (videoRef.current.videoWidth > videoRef.current.videoHeight) {
        setIsVertical(false)
      }
    } else if (detectedType === 'audio' && audioRef.current) {
      setDuration(audioRef.current.duration)
    }
  }

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value)
    setCurrentTime(time)
    if (detectedType === 'video' && videoRef.current) {
      videoRef.current.currentTime = time
    } else if (detectedType === 'audio' && audioRef.current) {
      audioRef.current.currentTime = time
    }
  }

  const cycleSpeed = () => {
    const speeds = [1, 1.5, 2]
    const nextSpeed = speeds[(speeds.indexOf(playbackRate) + 1) % speeds.length]
    setPlaybackRate(nextSpeed)
    if (videoRef.current) videoRef.current.playbackRate = nextSpeed
    if (audioRef.current) audioRef.current.playbackRate = nextSpeed
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(src)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const formatTime = (secs: number) => {
    if (isNaN(secs)) return '0:00'
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div className="rounded-xl border border-zinc-700/60 bg-zinc-950/80 backdrop-blur-md overflow-hidden shadow-2xl flex flex-col transition-all">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3.5 py-2.5 bg-zinc-900/90 border-b border-zinc-800 text-xs">
        <div className="flex items-center gap-2 min-w-0">
          {detectedType === 'video' && <Film className="h-4 w-4 text-emerald-400 shrink-0" />}
          {detectedType === 'image' && <ImageIcon className="h-4 w-4 text-sky-400 shrink-0" />}
          {detectedType === 'audio' && <Music className="h-4 w-4 text-violet-400 shrink-0" />}
          <span className="font-medium text-zinc-200 truncate">{title || src.split('/').pop() || 'Media Preview'}</span>
          {fileSize && <span className="text-[10px] text-zinc-500 font-mono">({fileSize})</span>}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {detectedType === 'video' && (
            <button
              onClick={() => setIsVertical(!isVertical)}
              title={isVertical ? 'Switch to Widescreen Frame' : 'Switch to 9:16 Shorts Frame'}
              className="p-1 rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
            >
              {isVertical ? <Smartphone className="h-3.5 w-3.5" /> : <Monitor className="h-3.5 w-3.5" />}
            </button>
          )}

          <button
            onClick={handleCopy}
            title="Copy path"
            className="p-1 rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          </button>

          <a
            href={resolvedSrc}
            download
            title="Download file"
            className="p-1 rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
          >
            <Download className="h-3.5 w-3.5" />
          </a>

          {onClose && (
            <button
              onClick={onClose}
              className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition ml-1"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Main Preview Stage */}
      <div className="relative flex items-center justify-center bg-black/90 p-2 min-h-[220px]">
        {detectedType === 'video' && (
          <div
            className={`relative flex items-center justify-center transition-all duration-300 rounded-lg overflow-hidden ${
              isVertical ? 'w-[200px] h-[356px] border border-zinc-800' : 'w-full max-w-[500px] aspect-video'
            }`}
          >
            <video
              ref={videoRef}
              src={resolvedSrc}
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={handleLoadedMetadata}
              onEnded={() => setIsPlaying(false)}
              className="w-full h-full object-contain cursor-pointer"
              onClick={togglePlay}
              playsInline
            />

            {/* Centered play overlay when paused */}
            {!isPlaying && (
              <button
                onClick={togglePlay}
                className="absolute inset-0 m-auto h-12 w-12 rounded-full bg-black/60 border border-white/20 flex items-center justify-center text-white hover:scale-105 hover:bg-black/80 transition shadow-lg"
              >
                <Play className="h-6 w-6 ml-1 text-white fill-white" />
              </button>
            )}

            {/* Top Shorts Indicator Badge */}
            {isVertical && (
              <div className="absolute top-2 left-2 px-1.5 py-0.5 rounded bg-black/70 border border-white/10 text-[9px] font-mono text-zinc-300 uppercase tracking-wider">
                9:16 Shorts
              </div>
            )}
          </div>
        )}

        {detectedType === 'image' && (
          <div
            className={`relative flex items-center justify-center rounded-lg overflow-hidden ${
              isVertical ? 'w-[200px] h-[356px] border border-zinc-800' : 'w-full max-w-[500px] max-h-[360px]'
            }`}
          >
            <img
              src={resolvedSrc}
              alt={title || 'Generated Still'}
              className="w-full h-full object-contain"
            />
            {isVertical && (
              <div className="absolute top-2 left-2 px-1.5 py-0.5 rounded bg-black/70 border border-white/10 text-[9px] font-mono text-sky-300 uppercase tracking-wider">
                9:16 Frame
              </div>
            )}
          </div>
        )}

        {detectedType === 'audio' && (
          <div className="w-full max-w-[420px] py-6 px-4 flex flex-col items-center gap-4">
            <audio
              ref={audioRef}
              src={resolvedSrc}
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={handleLoadedMetadata}
              onEnded={() => setIsPlaying(false)}
            />
            {/* Animated Waveform Bars */}
            <div className="flex items-center gap-1 h-12 w-full justify-center px-4">
              {[40, 65, 25, 80, 50, 95, 30, 70, 85, 45, 60, 90, 35, 75, 55, 80, 45, 90, 60, 30].map(
                (height, i) => (
                  <div
                    key={i}
                    className={`w-1 rounded-full transition-all duration-200 ${
                      isPlaying
                        ? 'bg-violet-400 animate-pulse'
                        : 'bg-zinc-700'
                    }`}
                    style={{
                      height: isPlaying ? `${Math.max(15, (height * (1 + (i % 3) * 0.2)) % 100)}%` : '20%',
                      animationDelay: `${i * 0.05}s`,
                    }}
                  />
                )
              )}
            </div>
            <div className="text-xs text-zinc-400 font-mono">
              {formatTime(currentTime)} / {formatTime(duration)}
            </div>
          </div>
        )}
      </div>

      {/* Media Controller Bar for Audio & Video */}
      {(detectedType === 'video' || detectedType === 'audio') && (
        <div className="px-3.5 py-2.5 bg-zinc-900 border-t border-zinc-800 flex flex-col gap-2">
          {/* Progress Seek Bar */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-zinc-400 w-8">{formatTime(currentTime)}</span>
            <input
              type="range"
              min={0}
              max={duration || 100}
              step={0.1}
              value={currentTime}
              onChange={handleSeek}
              className="flex-1 h-1 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
            <span className="text-[10px] font-mono text-zinc-500 w-8 text-right">{formatTime(duration)}</span>
          </div>

          {/* Buttons row */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <button
                onClick={togglePlay}
                className="p-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 transition"
              >
                {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 fill-current" />}
              </button>

              <button
                onClick={toggleMute}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
              >
                {isMuted ? <VolumeX className="h-4 w-4 text-red-400" /> : <Volume2 className="h-4 w-4" />}
              </button>

              <button
                onClick={cycleSpeed}
                className="px-2 py-0.5 rounded text-[11px] font-mono bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition"
              >
                {playbackRate}x
              </button>
            </div>

            <div className="text-[11px] text-zinc-500 font-mono">
              {detectedType === 'video' ? (isVertical ? '1080x1920' : '1920x1080') : 'Stereo 44.1kHz'}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
