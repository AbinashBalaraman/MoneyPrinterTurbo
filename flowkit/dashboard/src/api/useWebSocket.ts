import { useState, useEffect, useRef, useCallback } from 'react'
import type { WSEvent } from '../types'

/**
 * Dashboard WebSocket client.
 *
 * `getSince` lets a consumer supply a resume cursor. On every (re)connect the
 * value is appended as `?since=<seq>`, and the server replays exactly the log
 * records emitted after it. Without this, anything produced during a drop was
 * lost permanently — the reconnect would silently resume from "now".
 */
export function useWebSocket(
  onMessage?: (event: WSEvent) => void,
  getSince?: () => number,
) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState<WSEvent | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const retriesRef = useRef(0)
  const onMessageRef = useRef(onMessage)
  const getSinceRef = useRef(getSince)
  const connectRef = useRef<() => void>(() => {})

  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])
  useEffect(() => { getSinceRef.current = getSince }, [getSince])

  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // Read the cursor at connect time rather than capturing it, so a reconnect
    // asks for the gap since the last record actually received.
    const since = getSinceRef.current?.() ?? 0
    const query = since > 0 ? `?since=${since}` : ''
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/dashboard${query}`)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
      retriesRef.current = 0
    }

    ws.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data)
        setLastEvent(event)
        onMessageRef.current?.(event)
      } catch {
        // malformed frame — ignore
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
      wsRef.current = null
      const delay = Math.min(1000 * 2 ** retriesRef.current, 30000)
      retriesRef.current++
      setTimeout(() => connectRef.current(), delay)
    }

    ws.onerror = () => ws.close()
  }, [])

  useEffect(() => { connectRef.current = connect }, [connect])

  useEffect(() => {
    connect()
    return () => { wsRef.current?.close() }
  }, [connect])

  return { isConnected, lastEvent }
}
