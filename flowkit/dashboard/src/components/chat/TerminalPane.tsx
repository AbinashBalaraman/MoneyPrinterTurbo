import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'

/** Terminal colours follow the app theme (read from CSS vars) rather than being hardcoded. */
function themeFromCss() {
  const s = getComputedStyle(document.documentElement)
  const pick = (name: string, fallback: string) =>
    (s.getPropertyValue(name) || '').trim() || fallback
  return {
    background: pick('--bg', '#0b0f14'),
    foreground: pick('--text', '#d7dee7'),
    cursor: pick('--accent', '#10b981'),
    selectionBackground: 'rgba(16, 185, 129, 0.25)',
  }
}

function buildUrl(cwd?: string) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const base = `${proto}://${location.host}/ws/terminal`
  return cwd ? `${base}?cwd=${encodeURIComponent(cwd)}` : base
}

export default function TerminalPane({ cwd }: { cwd?: string }) {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    const term = new Terminal({
      convertEol: true,
      cursorBlink: true,
      fontFamily: 'Consolas, "Courier New", monospace',
      fontSize: 13,
      theme: themeFromCss(),
      allowProposedApi: true,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.loadAddon(new WebLinksAddon())
    term.open(host)

    const ws = new WebSocket(buildUrl(cwd))
    ws.binaryType = 'arraybuffer'

    ws.onmessage = (ev: MessageEvent) => {
      if (typeof ev.data === 'string') term.write(ev.data)
      else new Response(ev.data).text().then(t => term.write(t))
    }
    ws.onclose = () => term.writeln('\r\n\x1b[90m[terminal closed]\x1b[0m')
    ws.onerror = () => term.writeln('\r\n\x1b[31m[terminal connection error]\x1b[0m')

    ws.onopen = () => {
      // Tell the PTY our real size before the first prompt is drawn.
      ws.send(JSON.stringify({ type: 'resize', rows: term.rows, cols: term.cols }))
    }

    const dataSub = term.onData(d => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data: d }))
      }
    })
    const resizeSub = term.onResize(({ rows, cols }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', rows, cols }))
      }
    })

    const ro = new ResizeObserver(() => {
      try {
        fit.fit()
      } catch {
        /* host not laid out yet */
      }
    })
    ro.observe(host)
    requestAnimationFrame(() => {
      try {
        fit.fit()
      } catch {
        /* noop */
      }
    })

    return () => {
      ro.disconnect()
      dataSub.dispose()
      resizeSub.dispose()
      ws.close()
      term.dispose()
    }
  }, [cwd])

  return (
    <div
      ref={hostRef}
      className="w-full h-full overflow-hidden rounded-md border p-2"
      style={{ background: 'var(--bg)', borderColor: 'var(--border)' }}
    />
  )
}
