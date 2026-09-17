import { useState, useEffect } from 'react'
import { BrowserRouter, NavLink, Routes, Route, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { LayoutDashboard, FolderOpen, Film, ScrollText, BookOpen, Bot, Sun, Moon, ChevronsLeft, ChevronsRight, Sparkles, Wrench, Plus } from 'lucide-react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { WebSocketProvider } from './api/WebSocketContext'
import { useWebSocketContext } from './api/useWebSocketContext'
import { LanguageProvider } from './i18n/LanguageContext'
import { useTranslation } from './i18n/useTranslation'
import { LANGS, LANG_LABELS, type Lang } from './i18n/translations'
import type { TranslationKey } from './i18n/translations'
import { fetchAPI } from './api/client'
import type { Project } from './types'
import DashboardPage from './pages/DashboardPage'
import ProjectsPage from './pages/ProjectsPage'
import LogsPage from './pages/LogsPage'
import GalleryPage from './pages/GalleryPage'
import GuidePage from './pages/GuidePage'
import AgentChatPage from './pages/AgentChatPage'
import ManualWorkbenchPage from './pages/ManualWorkbenchPage'

const NAV: { to: string; icon: any; labelKey: TranslationKey; exact: boolean }[] = [
  { to: '/agent-studio', icon: Bot, labelKey: 'nav.agentStudio', exact: false },
  { to: '/manual', icon: Wrench, labelKey: 'nav.manual', exact: false },
  { to: '/projects', icon: FolderOpen, labelKey: 'nav.projects', exact: false },
  { to: '/gallery', icon: Film, labelKey: 'nav.gallery', exact: false },
  { to: '/dashboard', icon: LayoutDashboard, labelKey: 'nav.dashboard', exact: true },
  { to: '/logs', icon: ScrollText, labelKey: 'nav.logs', exact: false },
  { to: '/guide', icon: BookOpen, labelKey: 'nav.guide', exact: false },
]

const BREADCRUMB_TAB_KEY: Record<string, TranslationKey> = {
  overview: 'app.breadcrumbTab.overview',
  characters: 'app.breadcrumbTab.characters',
  videos: 'app.breadcrumbTab.videos',
  pipeline: 'app.breadcrumbTab.pipeline',
}

function useClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

function useBreadcrumbs() {
  const { t } = useTranslation()
  const loc = useLocation()
  const { id } = useParams<{ id?: string }>()
  const [searchParams] = useSearchParams()
  const [projectName, setProjectName] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    fetchAPI<Project>(`/api/projects/${id}`).then(p => setProjectName(p.name)).catch(() => setProjectName(null))
  }, [id])

  const crumbs: string[] = []
  if (loc.pathname === '/' || loc.pathname.startsWith('/agent-studio')) crumbs.push(t('app.breadcrumb.agentStudio'))
  else if (loc.pathname.startsWith('/manual')) crumbs.push('manual workbench')
  else if (loc.pathname.startsWith('/dashboard')) crumbs.push(t('app.breadcrumb.dashboard'))
  else if (loc.pathname.startsWith('/projects')) {
    crumbs.push(t('app.breadcrumb.projects'))
    if (id) {
      crumbs.push(projectName ?? '…')
      const tab = searchParams.get('tab')
      const tabKey = tab ? BREADCRUMB_TAB_KEY[tab] : undefined
      if (tabKey) crumbs.push(t(tabKey))
    }
  } else if (loc.pathname.startsWith('/gallery')) crumbs.push(t('app.breadcrumb.gallery'))
  else if (loc.pathname.startsWith('/logs')) crumbs.push(t('app.breadcrumb.logs'))
  else if (loc.pathname.startsWith('/guide')) crumbs.push(t('app.breadcrumb.guide'))

  return crumbs
}

function LanguageSwitcher() {
  const { lang, setLang } = useTranslation()
  return (
    <select
      value={lang}
      onChange={e => setLang(e.target.value as Lang)}
      className="text-[10px] px-2 py-1 rounded outline-none w-full"
      style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }}
    >
      {LANGS.map(l => (
        <option key={l} value={l}>{LANG_LABELS[l]}</option>
      ))}
    </select>
  )
}

function Sidebar() {
  const { t } = useTranslation()
  const loc = useLocation()
  const { worker } = useWebSocketContext()
  const [health, setHealth] = useState<{ extension_connected: boolean } | null>(null)
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem('flowkit-sidebar') === 'collapsed' } catch { return false }
  })
  const toggleCollapsed = () => {
    setCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem('flowkit-sidebar', next ? 'collapsed' : 'open') } catch { /* private mode */ }
      return next
    })
  }

  useEffect(() => {
    fetchAPI<{ extension_connected: boolean }>('/health').then(setHealth).catch(() => setHealth(null))
  }, [])

  const isManual = loc.pathname.startsWith('/manual')
  const isAgent = loc.pathname === '/' || loc.pathname.startsWith('/agent-studio')

  return (
    <aside className={`${collapsed ? 'w-14' : 'w-60'} flex-shrink-0 flex flex-col border-r transition-all duration-200 select-none`} style={{ background: 'var(--sidebar)', borderColor: 'var(--border)' }}>
      {/* Brand & Collapse Header */}
      <div className={`px-4 py-3.5 flex items-center justify-between border-b${collapsed ? ' justify-center px-0' : ''}`} style={{ borderColor: 'var(--border)' }}>
        <NavLink to="/agent-studio" className="flex items-center gap-2.5 hover:opacity-90 transition-opacity">
          <div className="w-6 h-6 rounded-md flex items-center justify-center bg-gradient-to-br from-blue-500 via-indigo-500 to-purple-600 text-white shadow-sm flex-shrink-0">
            <Sparkles size={14} />
          </div>
          {!collapsed && (
            <div className="flex items-baseline gap-1.5">
              <span className="text-sm font-semibold tracking-tight text-white">Gemini</span>
              <span className="text-[10px] text-blue-400 font-mono font-medium tracking-wide">AutoShorts</span>
            </div>
          )}
        </NavLink>

        {!collapsed && (
          <button
            onClick={toggleCollapsed}
            aria-label="Collapse sidebar"
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
          >
            <ChevronsLeft size={16} />
          </button>
        )}
      </div>

      {/* Mode Switcher: Agent (Chat) vs Manual (Tools Workbench) */}
      {!collapsed ? (
        <div className="px-3 pt-3 pb-1">
          <div className="flex rounded-lg p-0.5 border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
            <NavLink
              to="/agent-studio"
              className={`flex-1 py-1 text-center text-xs font-semibold rounded-md transition-all ${
                isAgent
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Chat
            </NavLink>
            <NavLink
              to="/manual"
              className={`flex-1 py-1 text-center text-xs font-semibold rounded-md transition-all flex items-center justify-center gap-1 ${
                isManual
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <span>Manual</span>
              <span className="text-[8px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 font-mono">BETA</span>
            </NavLink>
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center py-2 gap-1 border-b" style={{ borderColor: 'var(--border)' }}>
          <NavLink
            to="/agent-studio"
            title="Agent Chat"
            className={`p-2 rounded-lg transition-colors ${isAgent ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
          >
            <Bot size={16} />
          </NavLink>
          <NavLink
            to="/manual"
            title="Manual Workbench"
            className={`p-2 rounded-lg transition-colors ${isManual ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
          >
            <Wrench size={16} />
          </NavLink>
        </div>
      )}

      {/* New Chat / Session Action Pill */}
      {!collapsed && (
        <div className="px-3 py-2">
          <NavLink
            to="/agent-studio"
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-full border text-xs font-semibold text-slate-200 hover:bg-slate-800/60 transition-all hover:shadow-sm"
            style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
          >
            <Plus size={14} className="text-blue-400" />
            <span>New chat</span>
          </NavLink>
        </div>
      )}

      {/* Nav List */}
      <nav className="flex-1 overflow-y-auto px-2.5 py-2 flex flex-col gap-0.5">
        {NAV.map(({ to, icon: Icon, labelKey, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-xs transition-colors hover:bg-slate-800/40${collapsed ? ' justify-center px-0' : ''}`}
            title={t(labelKey)}
            style={({ isActive }) => ({
              background: isActive ? 'var(--card)' : 'transparent',
              color: isActive ? 'var(--text)' : 'var(--muted)',
              borderLeft: !collapsed && isActive ? '2px solid var(--accent)' : '2px solid transparent',
            })}
          >
            <Icon size={14} className="flex-shrink-0" />
            {!collapsed && <span className="truncate">{t(labelKey)}</span>}
          </NavLink>
        ))}

        {!collapsed && (
          <>
            {/* Recents Section */}
            <div className="mt-4 pt-3 border-t px-2" style={{ borderColor: 'var(--border)' }}>
              <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block mb-2">
                Recents
              </span>
              <div className="flex flex-col gap-1">
                <NavLink
                  to="/agent-studio"
                  className="text-xs text-slate-400 hover:text-white truncate px-2 py-1 rounded hover:bg-slate-800/30 transition-colors"
                >
                  🌾 Arthur & Rusty: Ep 2
                </NavLink>
                <NavLink
                  to="/manual"
                  className="text-xs text-slate-400 hover:text-white truncate px-2 py-1 rounded hover:bg-slate-800/30 transition-colors"
                >
                  ⚡ Stickman Legends: Render
                </NavLink>
                <NavLink
                  to="/projects"
                  className="text-xs text-slate-400 hover:text-white truncate px-2 py-1 rounded hover:bg-slate-800/30 transition-colors"
                >
                  🎬 One-off Stills Generation
                </NavLink>
              </div>
            </div>
          </>
        )}
      </nav>

      {/* Bottom Profile Footer: Abinash Pro + Settings */}
      <div className="mt-auto p-3 border-t flex flex-col gap-2.5" style={{ borderColor: 'var(--border)', background: 'var(--sidebar)' }}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 to-amber-400 flex items-center justify-center text-xs font-bold text-slate-900 shadow">
              A
            </div>
            <button
              onClick={toggleCollapsed}
              className="p-1 rounded text-slate-400 hover:text-white"
              title="Expand sidebar"
            >
              <ChevronsRight size={14} />
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 via-indigo-400 to-amber-300 flex items-center justify-center text-xs font-bold text-slate-950 shadow flex-shrink-0">
                  A
                </div>
                <div className="flex flex-col min-w-0">
                  <span className="text-xs font-bold text-white truncate">Abinash</span>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-semibold text-blue-400 tracking-wider">Pro</span>
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: health?.extension_connected ? 'var(--green)' : 'var(--red)' }}
                      title={health?.extension_connected ? 'Chrome Extension Active' : 'Extension Disconnected'}
                    />
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <LanguageSwitcher />
              </div>
            </div>

            <div className="flex items-center justify-between text-[10px] pt-1" style={{ color: 'var(--muted)' }}>
              <span>FlowKit Workers: {worker ? `${worker.active}/${worker.active + worker.slots}` : '—'}</span>
              <span style={{ color: health?.extension_connected ? 'var(--green)' : 'var(--red)' }}>
                {health?.extension_connected ? 'Flow Live' : 'Flow Off'}
              </span>
            </div>
          </>
        )}
      </div>
    </aside>
  )
}

const THEME_KEY = 'flowkit-theme'

type Theme = 'dark' | 'light'

function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // ignore (private mode)
  }
  return 'dark'
}

/** Sun/moon toggle for the opt-in light theme. Dark stays the default:
    first paint is set by the pre-hydration script in index.html (same key),
    this component only owns subsequent toggles. Persisted in localStorage. */
function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('light', theme === 'light')
    root.classList.toggle('dark', theme !== 'light')
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch {
      // ignore
    }
  }, [theme])

  const isLight = theme === 'light'
  return (
    <button
      onClick={() => setTheme(isLight ? 'dark' : 'light')}
      aria-label={isLight ? 'Switch to dark theme' : 'Switch to light theme'}
      aria-pressed={isLight}
      title={isLight ? 'Dark theme' : 'Light theme'}
      className="p-1.5 rounded border transition-colors hover:opacity-80"
      style={{ borderColor: 'var(--border)', background: 'var(--card)', color: 'var(--muted)' }}
    >
      {isLight ? <Moon size={13} aria-hidden="true" /> : <Sun size={13} aria-hidden="true" />}
    </button>
  )
}

function Header() {
  const { t } = useTranslation()
  const { isConnected } = useWebSocketContext()
  const crumbs = useBreadcrumbs()
  const clock = useClock()
  const loc = useLocation()
  const isAgentChat = loc.pathname === '/' || loc.pathname.startsWith('/agent-studio')

  if (isAgentChat) {
    // AgentChatPage provides its own unified Gemini header
    return null
  }

  return (
    <header className="flex items-center gap-4 px-5 h-13 flex-shrink-0 border-b" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
      <div className="flex items-center gap-2 text-[11px] tracking-wide" style={{ color: 'var(--muted)' }}>
        <span style={{ color: 'var(--accent)' }}>{t('app.breadcrumbRoot')}</span>
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-2">
            <span>/</span>
            <span style={{ color: i === crumbs.length - 1 ? 'var(--text)' : 'var(--muted)' }}>{c}</span>
          </span>
        ))}
      </div>
      <span className="ml-auto" />
      <div className="flex items-center gap-3.5 text-[10px]" style={{ color: 'var(--muted)' }}>
        <span className="tracking-wide">{clock.toLocaleTimeString()}</span>
        <ThemeToggle />
        <span className="flex items-center gap-1.5 px-2.5 py-1 rounded border" style={{ borderColor: 'var(--border)', color: isConnected ? 'var(--green)' : 'var(--red)' }}>
          <span
            className="w-1.5 h-1.5 rounded-full"
            aria-hidden="true"
            style={{ background: isConnected ? 'var(--green)' : 'var(--red)', animation: isConnected ? 'pulse 2s ease-in-out infinite' : 'none' }}
          />
          {isConnected ? t('app.wsLive') : t('app.wsDisconnected')}
        </span>
      </div>
    </header>
  )
}

function Layout() {
  const loc = useLocation()
  const isAgentChat = loc.pathname === '/' || loc.pathname.startsWith('/agent-studio')

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg)', color: 'var(--text)' }}>
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header />
        <main className={`flex-1 overflow-auto ${isAgentChat ? 'p-0 flex flex-col' : 'p-5'}`}>
          <Routes>
            <Route path="/" element={<AgentChatPage />} />
            <Route path="/agent-studio" element={<AgentChatPage />} />
            <Route path="/manual" element={<ManualWorkbenchPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:id" element={<ProjectsPage />} />
            <Route path="/gallery" element={<GalleryPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/guide" element={<GuidePage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <LanguageProvider>
        <WebSocketProvider>
          <TooltipProvider>
            <Layout />
          </TooltipProvider>
        </WebSocketProvider>
      </LanguageProvider>
    </BrowserRouter>
  )
}
