import { useSearchParams } from 'react-router-dom'
import { ScrollText, ListChecks } from 'lucide-react'
import LogConsole from '../components/logs/LogConsole'
import LogViewer from '../components/logs/LogViewer'
import { useTranslation } from '../i18n/useTranslation'

type Tab = 'console' | 'requests'

/**
 * Logs page.
 *
 * Two distinct things live here and they are not interchangeable: the live
 * console streams structured backend log lines, while the request view is a
 * table of FlowKit generation requests. The page previously only had the
 * latter, which is why "logs" appeared to be missing.
 */
export default function LogsPage() {
  const { t } = useTranslation()
  const [searchParams, setSearchParams] = useSearchParams()

  // Both the stage filter and the active tab live in the URL. A stage node on
  // the pipeline rail links to `/logs?stage=images`, so the reader lands on the
  // log lines for the thing they clicked, and the view survives a refresh.
  const initialStage = searchParams.get('stage') ?? undefined
  const tab: Tab = searchParams.get('tab') === 'requests' ? 'requests' : 'console'
  const setTab = (next: Tab) => {
    const params = new URLSearchParams(searchParams)
    if (next === 'requests') params.set('tab', 'requests')
    else params.delete('tab')
    setSearchParams(params, { replace: true })
  }

  const tabs: { id: Tab; label: string; icon: typeof ScrollText }[] = [
    { id: 'console', label: t('logs.tab.console'), icon: ScrollText },
    { id: 'requests', label: t('logs.tab.requests'), icon: ListChecks },
  ]

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-1.5 p-1 rounded-md border w-fit" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
        {tabs.map(({ id, label, icon: Icon }) => {
          const active = tab === id
          return (
            <button
              key={id}
              onClick={() => setTab(id)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all"
              style={{
                background: active ? 'var(--accent)' : 'transparent',
                color: active ? '#fff' : 'var(--muted)',
              }}
            >
              <Icon size={13} />
              {label}
            </button>
          )
        })}
      </div>

      {tab === 'console' ? <LogConsole initialStage={initialStage} /> : <LogViewer />}
    </div>
  )
}
