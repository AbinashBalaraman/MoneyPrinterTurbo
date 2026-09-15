// Enums
export type RequestType = 'GENERATE_IMAGE' | 'REGENERATE_IMAGE' | 'EDIT_IMAGE' | 'GENERATE_VIDEO' | 'REGENERATE_VIDEO' | 'GENERATE_VIDEO_REFS' | 'UPSCALE_VIDEO' | 'GENERATE_CHARACTER_IMAGE' | 'REGENERATE_CHARACTER_IMAGE' | 'EDIT_CHARACTER_IMAGE'
export type StatusType = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
export type Orientation = 'VERTICAL' | 'HORIZONTAL'
export type ChainType = 'ROOT' | 'CONTINUATION' | 'INSERT'
export type EntityType = 'character' | 'location' | 'creature' | 'visual_asset' | 'generic_troop' | 'faction'
export type ProjectStatus = 'ACTIVE' | 'ARCHIVED' | 'DELETED'

// Models — match the Python models exactly
export interface Project {
  id: string
  name: string
  description: string | null
  story: string | null
  thumbnail_url: string | null
  language: string
  status: ProjectStatus
  user_paygate_tier: string | null
  material: string
  narrator_voice: string | null
  narrator_ref_audio: string | null
  created_at: string
  updated_at: string
}

export interface Character {
  id: string
  name: string
  entity_type: EntityType
  description: string | null
  image_prompt: string | null
  voice_description: string | null
  reference_image_url: string | null
  media_id: string | null
  created_at: string
  updated_at: string
}

export interface Video {
  id: string
  project_id: string
  title: string
  description: string | null
  display_order: number
  status: string
  orientation: string | null
  vertical_url: string | null
  horizontal_url: string | null
  thumbnail_url: string | null
  duration: number | null
  resolution: string | null
  /** Set once the video has been published to YouTube. Evidence a publish happened. */
  youtube_id: string | null
  privacy: string
  tags: string | null
  created_at: string
  updated_at: string
}

export interface Scene {
  id: string
  video_id: string
  display_order: number
  prompt: string | null
  image_prompt: string | null
  video_prompt: string | null
  character_names: string | null  // JSON string array
  parent_scene_id: string | null
  chain_type: ChainType
  source: string | null
  vertical_image_url: string | null
  vertical_image_media_id: string | null
  vertical_image_status: StatusType
  vertical_video_url: string | null
  vertical_video_media_id: string | null
  vertical_video_status: StatusType
  vertical_upscale_url: string | null
  vertical_upscale_media_id: string | null
  vertical_upscale_status: StatusType
  horizontal_image_url: string | null
  horizontal_image_media_id: string | null
  horizontal_image_status: StatusType
  horizontal_video_url: string | null
  horizontal_video_media_id: string | null
  horizontal_video_status: StatusType
  horizontal_upscale_url: string | null
  horizontal_upscale_media_id: string | null
  horizontal_upscale_status: StatusType
  narrator_text: string | null
  trim_start: number | null
  trim_end: number | null
  duration: number | null
  created_at: string
  updated_at: string
}

export interface Request {
  id: string
  project_id: string | null
  video_id: string | null
  scene_id: string | null
  character_id: string | null
  type: RequestType
  orientation: Orientation | null
  status: StatusType
  request_id: string | null
  media_id: string | null
  output_url: string | null
  error_message: string | null
  retry_count: number
  created_at: string
  updated_at: string
}

// WebSocket event
export interface WSEvent {
  type: string
  data: Record<string, unknown>
  timestamp: string
}

/**
 * A single structured log line from the backend log bus.
 *
 * `seq` is the contract: it increases monotonically, so a client that
 * reconnects with the last seq it saw receives exactly the records it missed.
 * Dedupe live records against the `latest_seq` from a `log_replay` payload.
 */
export interface LogRecord {
  seq: number
  ts: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'
  message: string
  stage: string | null
  source: string | null
  extra?: Record<string, unknown>
}

/**
 * A live log line, broadcast as it happens.
 *
 * Declared standalone rather than extending `WSEvent`: the generic event types
 * its payload as `Record<string, unknown>`, and narrowing that to a concrete
 * interface is not assignable. Log events are a distinct, well-typed stream —
 * narrow on `type` to reach them.
 */
export interface LogEvent {
  type: 'log'
  data: LogRecord
  timestamp: string
}

/** The gap a reconnecting client missed, sent once immediately after connect. */
export interface LogReplayEvent {
  type: 'log_replay'
  data: {
    records: LogRecord[]
    latest_seq: number
    retained: number
    dropped: number
  }
  timestamp?: string
}

export type LogLevel = LogRecord['level']

export const LOG_LEVELS: LogLevel[] = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

// AI video review — match agent/models/review.py exactly
export interface DimensionScores {
  character_consistency: number
  prompt_adherence: number
  motion_quality: number
  visual_fidelity: number
  temporal_coherence: number
  composition: number
}

export interface VideoError {
  severity: string // CRITICAL / HIGH / MINOR
  time_range: string
  description: string
}

export interface SegmentScore {
  time_range: string
  score: number
}

export interface SceneReview {
  scene_id: string
  overall_score: number
  verdict: string // excellent / good / acceptable / poor / unusable
  dimensions: DimensionScores
  errors: VideoError[]
  usable_segments: SegmentScore[]
  fix_guide: string
  frames_analyzed: number
  fps_used: number
  has_critical_errors: boolean
}

// ---- Publishing ----
// Outcomes reported by shorts_content_engine. Mirrors agent/models/publication.py.

export type PublicationStatus = 'requested' | 'published' | 'dry_run' | 'failed'

export interface Publication {
  id: string
  video_id: string
  project_id: string | null
  platform: string
  status: PublicationStatus
  post_id: string | null
  /** Present only for a real upload. A simulated result never carries one. */
  video_url: string | null
  error_message: string | null
  is_mock: boolean
  metadata: Record<string, unknown>
  published_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface PublicationSummary {
  total: number
  /** Real platform acknowledgements only. */
  live: number
  dry_run: number
  failed: number
  requested: number
  /** Something succeeded but none of it was real — nothing was posted. */
  is_dry_run: boolean
  /** No platform has ever been attempted. */
  is_unpublished: boolean
}

export interface PublicationListResponse {
  video_id: string
  publications: Publication[]
  summary: PublicationSummary
}
