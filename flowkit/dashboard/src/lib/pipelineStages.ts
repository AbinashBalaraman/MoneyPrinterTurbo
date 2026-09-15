/**
 * The end-to-end pipeline, as six stages.
 *
 * FlowKit only owns four of them. The rest — script, watermark removal,
 * publishing — happen in `shorts_content_engine`, which this dashboard cannot
 * reach. The previous rail showed only FlowKit's four stages and silently
 * omitted the rest, so the pipeline looked like it began at "Refs" and ended at
 * "Upscale". That is not the pipeline anyone is actually running.
 *
 * Rather than invent a seventh backend or render a button that does nothing,
 * each stage declares who owns it and whether this deployment can run it. A
 * stage that cannot be run says so. That is the whole point of the `wired`
 * flag: a stage that is visible but non-functional is worse than one that is
 * honestly absent.
 *
 * `stages` lists the log-record stage names that roll up into a node. It must
 * stay in sync with `agent/services/stages.py`; the vocabulary is deliberately
 * finer-grained than the rail so a log line keeps its precision.
 */

import type { Character, Request, Scene, Video } from '../types'
import { count, charStatus, sceneStageStatus, type StageCount } from './stageStats'

/** Stage names the backend may tag a log record with. Mirrors agent/services/stages.py. */
export type LogStage =
  | 'script'
  | 'refs'
  | 'images'
  | 'video'
  | 'upscale'
  | 'watermark'
  | 'assemble'
  | 'voiceover'
  | 'music'
  | 'publish'

/** The six rail nodes. */
export type RailKey = 'script' | 'images' | 'watermark' | 'assemble' | 'voiceover' | 'publish'

export type StageState = 'done' | 'running' | 'failed' | 'pending' | 'not_connected'

export type StageOwner = 'flowkit' | 'shorts_content_engine'

export interface RailStageDef {
  key: RailKey
  idx: string
  /** Log stages that roll up into this node. */
  stages: LogStage[]
  /** The system that actually performs this work. */
  owner: StageOwner
  /** Whether this deployment has a backend for the stage at all. */
  wired: boolean
}

/**
 * Every stage name, flattened. The console offers these as filters even before
 * they have emitted anything — otherwise a stage with no lines yet cannot be
 * selected, and the filter looks like it is missing options.
 */
export const ALL_LOG_STAGES: LogStage[] = [
  'script', 'refs', 'images', 'video', 'upscale', 'watermark', 'assemble', 'voiceover', 'music', 'publish',
]

export const RAIL_STAGES: RailStageDef[] = [
  { key: 'script', idx: '01', stages: ['script'], owner: 'shorts_content_engine', wired: false },
  { key: 'images', idx: '02', stages: ['refs', 'images'], owner: 'flowkit', wired: true },
  { key: 'watermark', idx: '03', stages: ['watermark'], owner: 'shorts_content_engine', wired: false },
  { key: 'assemble', idx: '04', stages: ['video', 'upscale', 'assemble'], owner: 'flowkit', wired: true },
  { key: 'voiceover', idx: '05', stages: ['voiceover', 'music'], owner: 'flowkit', wired: true },
  { key: 'publish', idx: '06', stages: ['publish'], owner: 'shorts_content_engine', wired: false },
]

export interface RailStatus {
  state: StageState
  counts: StageCount
  /** No backend for this stage in this deployment — the UI must say so. */
  notConnected: boolean
}

export interface RailContext {
  characters: Character[]
  scenes: Scene[]
  requests: Request[]
  video: Video | null
}

function emptyCounts(total = 0): StageCount {
  return { done: 0, processing: 0, failed: 0, pending: total, total }
}

function mergeCounts(parts: StageCount[]): StageCount {
  return parts.reduce<StageCount>(
    (acc, p) => ({
      done: acc.done + p.done,
      processing: acc.processing + p.processing,
      failed: acc.failed + p.failed,
      pending: acc.pending + p.pending,
      total: acc.total + p.total,
    }),
    { done: 0, processing: 0, failed: 0, pending: 0, total: 0 },
  )
}

/**
 * Collapse counts into a single node state.
 *
 * `running` means something is in flight *right now* — it drives a pulsing
 * indicator, so it must not fire merely because a stage is part-way done. A
 * stage that is 5-of-10 complete with nothing queued is not running; it is
 * incomplete, and the counts already say so.
 *
 * Activity outranks failure: if work is happening and something also failed,
 * the more actionable fact is that the stage is still moving.
 */
function stateFromCounts(c: StageCount): StageState {
  if (c.processing > 0) return 'running'
  if (c.failed > 0) return 'failed'
  if (c.total > 0 && c.done === c.total) return 'done'
  return 'pending'
}

export function railStatus(key: RailKey, ctx: RailContext): RailStatus {
  const { characters, scenes, requests, video } = ctx

  switch (key) {
    case 'images': {
      // Reference sheets and scene stills are separate work but one step of the
      // journey, so the node reports both rather than hiding refs inside it.
      const counts = mergeCounts([
        count(characters.map(c => charStatus(c, requests))),
        count(scenes.map(s => sceneStageStatus(s, 'image'))),
      ])
      return { state: stateFromCounts(counts), counts, notConnected: false }
    }

    case 'assemble': {
      const counts = mergeCounts([
        count(scenes.map(s => sceneStageStatus(s, 'video'))),
        count(scenes.map(s => sceneStageStatus(s, 'upscale'))),
      ])
      return { state: stateFromCounts(counts), counts, notConnected: false }
    }

    case 'voiceover': {
      // Only narration *text* is persisted (scene.narrator_text). Whether audio
      // has been synthesised is not stored anywhere, so the node reports text
      // coverage and does not pretend to know about the WAVs.
      const withText = scenes.filter(s => (s.narrator_text ?? '').trim().length > 0).length
      const counts: StageCount = {
        done: withText,
        processing: 0,
        failed: 0,
        pending: scenes.length - withText,
        total: scenes.length,
      }
      // Not stateFromCounts: partial coverage would read as "running" and pulse
      // the node, but nothing is running — no audio job is queued for the
      // scenes that lack text. Coverage is simply complete or not.
      const state: StageState =
        scenes.length > 0 && withText === scenes.length ? 'done' : 'pending'
      return { state, counts, notConnected: false }
    }

    case 'publish': {
      // The publish call belongs to shorts_content_engine. A stored youtube_id
      // is evidence it already happened, which is worth showing even though
      // this dashboard cannot trigger it.
      const published = video?.youtube_id ? 1 : 0
      const counts: StageCount = { done: published, processing: 0, failed: 0, pending: published ? 0 : 1, total: 1 }
      return {
        state: published ? 'done' : 'not_connected',
        counts,
        notConnected: published === 0,
      }
    }

    case 'script':
    case 'watermark':
    default: {
      // No backend in this deployment. Reporting zeroes would read as "not
      // started yet", which is a different and misleading claim.
      return { state: 'not_connected', counts: emptyCounts(0), notConnected: true }
    }
  }
}
