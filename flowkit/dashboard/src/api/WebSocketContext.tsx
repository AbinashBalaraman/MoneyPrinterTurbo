import { useCallback, useRef, useState, type ReactNode } from 'react'
import { useWebSocket } from './useWebSocket'
import { WebSocketContext, type WorkerSnapshot } from './useWebSocketContext'
import type { LogEvent, LogRecord, LogReplayEvent, WSEvent } from '../types'

const MAX_EVENTS = 200
/** Client-side cap. The server keeps its own bounded history; this only bounds
 *  what the browser holds in memory for rendering. */
const MAX_LOGS = 5000

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<WSEvent[]>([])
  const [worker, setWorker] = useState<WorkerSnapshot | null>(null)
  const [logs, setLogs] = useState<LogRecord[]>([])
  const [logMeta, setLogMeta] = useState({ retained: 0, dropped: 0 })

  // Highest seq already in the buffer. This doubles as the resume cursor, so a
  // reconnect asks for exactly what is missing.
  const maxSeqRef = useRef(0)

  const appendLogs = useCallback((incoming: LogRecord[]) => {
    if (incoming.length === 0) return
    const cursor = maxSeqRef.current
    const fresh = incoming.filter(r => r.seq > cursor)
    if (fresh.length === 0) return

    // Advance the cursor to the true maximum rather than trusting ordering, so
    // a replayed batch arriving out of order cannot cause a later record to be
    // treated as a duplicate and dropped.
    maxSeqRef.current = fresh.reduce((max, r) => (r.seq > max ? r.seq : max), cursor)

    setLogs(prev => {
      const next = [...prev, ...fresh]
      return next.length > MAX_LOGS ? next.slice(next.length - MAX_LOGS) : next
    })
  }, [])

  const handleMessage = useCallback((event: WSEvent) => {
    // The initial snapshot and keepalive ping are sent directly by the WS endpoint (agent/main.py),
    // not through event_bus, so they don't share WSEvent's {type, data, timestamp} shape.
    const raw = event as unknown as { type: string; worker?: WorkerSnapshot }

    if (raw.type === 'snapshot') {
      if (raw.worker) setWorker(raw.worker)
      return
    }
    if (raw.type === 'ping') return

    if (raw.type === 'log') {
      appendLogs([(event as unknown as LogEvent).data])
      return
    }

    if (raw.type === 'log_replay') {
      const data = (event as unknown as LogReplayEvent).data
      appendLogs(data.records)
      setLogMeta({ retained: data.retained ?? 0, dropped: data.dropped ?? 0 })
      return
    }

    setEvents(prev => [event, ...prev].slice(0, MAX_EVENTS))
  }, [appendLogs])

  const getSince = useCallback(() => maxSeqRef.current, [])

  const clearLogs = useCallback(() => {
    setLogs([])
    // The cursor is deliberately NOT reset: the server's sequence numbers keep
    // advancing, so resuming from 0 would replay history the user just cleared.
    // Clearing means "start fresh from now".
  }, [])

  const { isConnected, lastEvent } = useWebSocket(handleMessage, getSince)

  return (
    <WebSocketContext.Provider
      value={{ isConnected, lastEvent, events, worker, logs, logMeta, clearLogs }}
    >
      {children}
    </WebSocketContext.Provider>
  )
}
