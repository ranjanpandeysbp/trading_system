import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchStrategyLabPresets } from '../../api/client'
import { Card } from '../ui/Card'
import { Loading } from '../ui/Feedback'
import { CopyAllButton, CopyableDetails } from '../ui/CopyAllButton'

type HubSection = {
  id: string
  title: string
  guide?: string | null
  extra?: string | null
}

type Encyclopedia = {
  hubs?: Array<{ hub: string; count: number; sections: HubSection[] }>
  section_count?: number
  hub_count?: number
  overview?: string
  workflows?: string
  when_to_use?: string
  strategy_lab_detail?: string
}

/** Full hub strategy guide — same encyclopedia as Strategy Lab, opened from Command Center. */
export function AllStrategiesExplainedPanel() {
  const q = useQuery({
    queryKey: ['cc-all-strategies-encyclopedia'],
    queryFn: () => fetchStrategyLabPresets(undefined, 'india'),
  })

  const encyclopedia = (q.data as { encyclopedia?: Encyclopedia } | undefined)?.encyclopedia

  const copyAll = useMemo(() => {
    if (!encyclopedia) return ''
    const parts: string[] = [
      '# TrueBacktester — All Strategies Explained',
      '',
      'Research / education only — not financial advice.',
      '',
    ]
    if (encyclopedia.overview) parts.push(`# App overview\n\n${encyclopedia.overview}`)
    if (encyclopedia.workflows) parts.push(`# Workflows\n\n${encyclopedia.workflows}`)
    if (encyclopedia.when_to_use) parts.push(`# When to use what\n\n${encyclopedia.when_to_use}`)
    for (const hub of encyclopedia.hubs ?? []) {
      parts.push(`# ${hub.hub}`)
      for (const section of hub.sections) {
        const body = [section.guide, section.extra].filter(Boolean).join('\n\n')
        parts.push(`## ${section.title}\n(${section.id})\n\n${body || 'No guide available yet.'}`)
      }
    }
    if (encyclopedia.strategy_lab_detail) {
      parts.push(`# Strategy Lab & tools detail\n\n${encyclopedia.strategy_lab_detail}`)
    }
    return parts.join('\n\n---\n\n')
  }, [encyclopedia])

  if (q.isLoading) return <Loading message="Loading all strategies encyclopedia…" />
  if (q.isError) {
    return (
      <Card>
        <p className="text-sm text-rose-300">Could not load strategy encyclopedia. Try Strategy Lab → Encyclopedia.</p>
      </Card>
    )
  }
  if (!encyclopedia?.hubs?.length) {
    return (
      <Card>
        <p className="text-sm text-slate-500">No encyclopedia data returned.</p>
      </Card>
    )
  }

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-white">All Strategies Explained</h3>
          <p className="mt-1 text-sm text-slate-400">
            {encyclopedia.section_count ?? 0} hub sections across {encyclopedia.hub_count ?? 0} hubs —
            copy everything below into notes, docs, or Ask AI.
          </p>
        </div>
        {copyAll.trim() ? <CopyAllButton text={copyAll} label="Copy all strategies" size="md" /> : null}
      </div>

      <div className="space-y-4">
        {encyclopedia.overview && <CopyableDetails summary="App overview" text={encyclopedia.overview} />}
        {encyclopedia.workflows && <CopyableDetails summary="Workflows" text={encyclopedia.workflows} />}
        {encyclopedia.when_to_use && (
          <CopyableDetails summary="When to use what" text={encyclopedia.when_to_use} />
        )}

        {encyclopedia.hubs.map((hub) => (
          <div key={hub.hub}>
            <h5 className="mb-2 text-sm font-semibold text-slate-100">
              {hub.hub} <span className="font-normal text-slate-500">({hub.count})</span>
            </h5>
            <div className="space-y-2">
              {hub.sections.map((section) => {
                const text = [section.guide, section.extra].filter(Boolean).join('\n\n')
                return (
                  <CopyableDetails
                    key={section.id}
                    summary={section.title}
                    text={text || `No guide available yet.\n(${section.id})`}
                  >
                    <p className="mt-1 text-[11px] text-slate-600">{section.id}</p>
                    {section.guide ? (
                      <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
                        {section.guide}
                      </pre>
                    ) : (
                      <p className="mt-2 text-xs text-slate-500">No guide available yet.</p>
                    )}
                    {section.extra && (
                      <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-500">
                        {section.extra}
                      </pre>
                    )}
                  </CopyableDetails>
                )
              })}
            </div>
          </div>
        ))}

        {encyclopedia.strategy_lab_detail && (
          <CopyableDetails summary="Strategy Lab & tools detail" text={encyclopedia.strategy_lab_detail} />
        )}
      </div>
    </Card>
  )
}
