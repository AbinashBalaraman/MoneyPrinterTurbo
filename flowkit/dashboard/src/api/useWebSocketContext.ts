import { createContext, useContext } from 'react'
import type { LogRecord, WSEvent } from '../types'

export interface WorkerSnapshot {
  active: number
  slots: number
}

export interface LogMeta {
  /** Records the server is currently retaining in its bounded history. */
  retained: number
  /** Records the server dropped because a subscriber queue was full. */
  dropped: number
}

export interface WebSocketContextValue {
  isConnected: boolean
  lastEvent: WSEvent | null
  /** Rolling log of real event_bus events (request_update, worker_tick, urls_refreshed), newest first. */
  events: WSEvent[]
  /** From the initial /ws/dashboard snapshot message: real active/slots worker counts. */
  worker: WorkerSnapshot | null
  /** Structured log records from the backend log bus, oldest first. */
  logs: LogRecord[]
  logMeta: LogMeta
  /** Drop the client-side buffer. New records keep arriving; history does not. */
  clearLogs: () => void
}

export const WebSocketContext = createContext<WebSocketContextValue | null>(null)

export function useWebSocketContext() {
  const ctx = useContext(WebSocketContext)
  if (!ctx) throw new Error('useWebSocketContext must be used within a WebSocketProvider')
  return ctx
}
