import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Clapperboard, FolderOpen, Pencil, Save, Sparkles, Trash2, X } from 'lucide-react'
import {
  apiErrorMessage,
  deleteYoutubeAiView,
  fetchYoutubeAiView,
  fetchYoutubeAiViews,
  fetchYoutubeAnalysisPrefs,
  runYoutubeAnalysisAiView,
  runYoutubeAnalysisScan,
  saveYoutubeAiView,
  saveYoutubeAnalysisPrefs,
  updateYoutubeAiView,
  type SavedYoutubeAiViewSummary,
} from '../api/client'
import { AskAIPanel } from '../components/ai/AskAIPanel'
import { CollapsibleScrollSection } from '../components/command-center/CollapsibleScrollSection'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { Badge } from '../components/ui/Badge'

function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function parseVideoList(raw: string) {
  return raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

type VideoRow = {
  video_id: string
  title: string
  url: string
  published_at?: string
  transcript?: string | null
  transcript_error?: string | null
  transcript_chars?: number
}

type DayBucket = { date: string; videos: VideoRow[] }
type ChannelBucket = {
  channel_id: string
  channel_title: string
  video_count: number
  transcript_count: number
  days: DayBucket[]
}

export default function YoutubeAnalysis() {
  const qc = useQueryClient()
  const { data: prefs, isLoading: prefsLoading } = useQuery({
    queryKey: ['youtube-analysis-prefs'],
    queryFn: fetchYoutubeAnalysisPrefs,
  })

  const [videosRaw, setVideosRaw] = useState('')
  const [hydrated, setHydrated] = useState(false)
  const [error, setError] = useState('')
  const [prefsMsg, setPrefsMsg] = useState('')
  const [openChannels, setOpenChannels] = useState<Record<string, boolean>>({})
  const [openDays, setOpenDays] = useState<Record<string, boolean>>({})
  const [aiView, setAiView] = useState<{
    report: string
    verdict?: string | null
    provider: string
    model: string
  } | null>(null)

  const [showSaveViewForm, setShowSaveViewForm] = useState(false)
  const [saveViewName, setSaveViewName] = useState('')
  const [saveViewMsg, setSaveViewMsg] = useState('')
  const [viewedSavedId, setViewedSavedId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editText, setEditText] = useState('')

  useEffect(() => {
    if (!prefs || hydrated) return
    setVideosRaw(prefs.youtube_channel_ids || '')
    setHydrated(true)
  }, [prefs, hydrated])

  const videoList = parseVideoList(videosRaw)
  const hasYoutubeKey = Boolean(prefs?.youtube_api_key_set)
  const geminiReady = Boolean(prefs?.gemini_token_set)
  const keysReady = hasYoutubeKey && geminiReady

  const savePrefsMut = useMutation({
    mutationFn: () =>
      saveYoutubeAnalysisPrefs({
        youtube_channel_ids: videosRaw,
      }),
    onSuccess: (data) => {
      setVideosRaw(data.youtube_channel_ids || videosRaw)
      setPrefsMsg('Video list saved for your account.')
      setError('')
      qc.invalidateQueries({ queryKey: ['youtube-analysis-prefs'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const scanMut = useMutation({
    mutationFn: () => {
      if (!videoList.length) throw new Error('Enter at least one YouTube video URL or ID')
      if (!hasYoutubeKey) {
        throw new Error('Add a YouTube Data API key under Manage Settings')
      }
      if (!geminiReady) {
        throw new Error('Add a Gemini API key under Manage Settings')
      }
      return runYoutubeAnalysisScan({
        video_urls: videoList,
      })
    },
    onError: (e) => {
      setError(apiErrorMessage(e))
      setAiView(null)
    },
    onSuccess: (data) => {
      setError('')
      setPrefsMsg('Video list saved for your account.')
      setAiView(null)
      const saved = String(data.youtube_channel_ids || '')
      if (saved) setVideosRaw(saved)
      const channels = (data.channels as ChannelBucket[]) || []
      const nextCh: Record<string, boolean> = {}
      const nextDay: Record<string, boolean> = {}
      channels.forEach((ch, i) => {
        nextCh[ch.channel_id] = i === 0
        ;(ch.days || []).forEach((d, j) => {
          nextDay[`${ch.channel_id}:${d.date}`] = i === 0 && j === 0
        })
      })
      setOpenChannels(nextCh)
      setOpenDays(nextDay)
      qc.invalidateQueries({ queryKey: ['youtube-analysis-prefs'] })
    },
  })

  const aiViewMut = useMutation({
    mutationFn: () => {
      const data = scanMut.data
      if (!data) throw new Error('Fetch transcripts first')
      return runYoutubeAnalysisAiView({
        ai_context: String(data.ai_context || ''),
        scan: data,
      })
    },
    onSuccess: (data) => {
      setAiView(data)
      setViewedSavedId(null)
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const savedViewsQuery = useQuery({
    queryKey: ['youtube-ai-views'],
    queryFn: fetchYoutubeAiViews,
  })
  const savedViews = savedViewsQuery.data?.ai_views ?? []

  const viewedSavedQuery = useQuery({
    queryKey: ['youtube-ai-view', viewedSavedId],
    queryFn: () => fetchYoutubeAiView(viewedSavedId as number),
    enabled: viewedSavedId != null,
  })
  const viewedSaved = viewedSavedQuery.data

  const saveViewMut = useMutation({
    mutationFn: () => {
      const data = scanMut.data
      if (!aiView) throw new Error('Generate an AI View first')
      return saveYoutubeAiView({
        name: saveViewName.trim() || `YouTube AI View ${new Date().toLocaleString()}`,
        report: aiView.report,
        verdict: aiView.verdict,
        provider: aiView.provider,
        model: aiView.model,
        ai_context: aiContext,
        video_urls: videoList,
        from_date: String(data?.from_date || ''),
        to_date: String(data?.to_date || ''),
        snapshot_note: String(data?.snapshot_note || ''),
      })
    },
    onSuccess: () => {
      setSaveViewMsg('AI View saved.')
      setShowSaveViewForm(false)
      setSaveViewName('')
      qc.invalidateQueries({ queryKey: ['youtube-ai-views'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const updateViewMut = useMutation({
    mutationFn: (vars: { id: number; name?: string; report?: string }) =>
      updateYoutubeAiView(vars.id, { name: vars.name, report: vars.report }),
    onSuccess: (_data, vars) => {
      setEditingId(null)
      qc.invalidateQueries({ queryKey: ['youtube-ai-views'] })
      if (viewedSavedId === vars.id) qc.invalidateQueries({ queryKey: ['youtube-ai-view', vars.id] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const deleteViewMut = useMutation({
    mutationFn: deleteYoutubeAiView,
    onSuccess: (_data, id) => {
      if (viewedSavedId === id) setViewedSavedId(null)
      qc.invalidateQueries({ queryKey: ['youtube-ai-views'] })
    },
  })

  const [editLoading, setEditLoading] = useState(false)

  const startEdit = async (v: SavedYoutubeAiViewSummary) => {
    setEditName(v.name)
    setEditText('')
    setEditLoading(true)
    try {
      const full = await fetchYoutubeAiView(v.id)
      setEditText(full.payload?.report || '')
      setEditingId(v.id)
    } catch (e) {
      setError(apiErrorMessage(e))
    } finally {
      setEditLoading(false)
    }
  }

  const data = scanMut.data
  const channels = (data?.channels as ChannelBucket[]) || []
  const aiContext = String(data?.ai_context || '')
  const aiSystem = String(data?.ai_system_prompt || '')

  if (prefsLoading && !hydrated) {
    return <Loading message="Loading saved YouTube preferences…" />
  }

  return (
    <div>
      <PageHeader
        title="Youtube Analysis"
        description="Listed YouTube videos · transcripts via Gemini · Ask AI / AI View. API keys are configured under Manage."
      />

      <Card className="mb-4">
        <p className="mb-3 text-xs text-slate-500">
          Paste YouTube video URLs or IDs (comma-separated or one per line). YouTube Data API + Gemini
          keys: configure under Manage.
          {hasYoutubeKey ? ' YouTube key saved.' : ' YouTube key missing.'}
          {geminiReady
            ? ` Gemini saved · model ${prefs?.gemini_model || '—'}.`
            : ' Gemini key missing.'}
        </p>

        {!keysReady && (
          <div className="mb-3">
            <Alert type="error">
              {!hasYoutubeKey && !geminiReady
                ? 'Add YouTube Data API key and Gemini API key under Manage Settings.'
                : !hasYoutubeKey
                  ? 'Add a YouTube Data API key under Manage Settings.'
                  : 'Add a Gemini API key under Manage Settings.'}
            </Alert>
          </div>
        )}

        <FormField label="YouTube videos (URLs or IDs — comma-separated or one per line)">
          <Textarea
            rows={5}
            value={videosRaw}
            onChange={(e) => {
              setVideosRaw(e.target.value)
              setPrefsMsg('')
            }}
            placeholder={
              'https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://youtu.be/abcdefghijk\ndQw4w9WgXcQ'
            }
          />
        </FormField>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            onClick={() => scanMut.mutate()}
            disabled={scanMut.isPending || !videoList.length || !keysReady}
          >
            <span className="inline-flex items-center gap-2">
              <Clapperboard size={16} />
              {scanMut.isPending
                ? 'Resolving videos & Gemini transcripts…'
                : `Fetch transcripts (${videoList.length} video${videoList.length === 1 ? '' : 's'})`}
            </span>
          </Button>
          <Button
            variant="secondary"
            onClick={() => savePrefsMut.mutate()}
            disabled={savePrefsMut.isPending || !videosRaw.trim()}
          >
            <span className="inline-flex items-center gap-2">
              <Save size={16} />
              {savePrefsMut.isPending ? 'Saving…' : 'Save video list'}
            </span>
          </Button>
        </div>
        {prefsMsg && (
          <div className="mt-3">
            <Alert type="success">{prefsMsg}</Alert>
          </div>
        )}
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      {scanMut.isPending && (
        <Loading message="Resolving listed videos, then Gemini transcripts…" />
      )}

      {data && !scanMut.isPending && (
        <>
          <Card className="mb-4">
            <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
              <span>{String(data.snapshot_note || '')}</span>
              {(data.resolve_errors as string[] | undefined)?.length ? (
                <Alert type="error">
                  {(data.resolve_errors as string[]).join(' · ')}
                </Alert>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <Button
                onClick={() => aiViewMut.mutate()}
                disabled={aiViewMut.isPending || !Number(data.transcript_count || 0)}
              >
                <span className="inline-flex items-center gap-2">
                  <Sparkles size={16} />
                  {aiViewMut.isPending ? 'Building market view…' : 'AI View'}
                </span>
              </Button>
              <span className="self-center text-xs text-slate-500">
                Summarizes all transcripts → market impact for days & weeks
              </span>
            </div>
            {aiViewMut.isError && (
              <div className="mt-3">
                <Alert type="error">{apiErrorMessage(aiViewMut.error)}</Alert>
              </div>
            )}
            {aiViewMut.isPending && <Loading message="Calling AI for market view…" />}
            {aiView && !aiViewMut.isPending && (
              <div className="mt-4 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Bot className="text-violet-400" size={18} />
                  <h3 className="font-semibold text-white">AI View</h3>
                  <span className="text-xs text-slate-500">
                    {aiView.provider} · {aiView.model}
                  </span>
                  {aiView.verdict && <Badge action={aiView.verdict} />}
                  <Button
                    variant="secondary"
                    size="sm"
                    className="ml-auto"
                    onClick={() => setShowSaveViewForm(true)}
                  >
                    <span className="inline-flex items-center gap-1.5"><Save size={14} />Save for future reference</span>
                  </Button>
                </div>
                {showSaveViewForm && (
                  <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
                    <FormField label="Name">
                      <div className="flex gap-2">
                        <Input
                          value={saveViewName}
                          onChange={(e) => setSaveViewName(e.target.value)}
                          placeholder={`YouTube AI View — ${new Date().toLocaleDateString()}`}
                        />
                        <Button onClick={() => saveViewMut.mutate()} disabled={saveViewMut.isPending}>
                          {saveViewMut.isPending ? 'Saving…' : 'Save'}
                        </Button>
                        <Button variant="ghost" onClick={() => setShowSaveViewForm(false)}>
                          <X size={14} />
                        </Button>
                      </div>
                    </FormField>
                  </div>
                )}
                {saveViewMsg && !showSaveViewForm && (
                  <p className="text-xs text-emerald-400">{saveViewMsg}</p>
                )}
                <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-xl border border-slate-700/60 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300">
                  {aiView.report}
                </pre>
              </div>
            )}
          </Card>

          <Card className="mb-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h4 className="inline-flex items-center gap-2 font-medium text-white">
                <FolderOpen size={16} className="text-slate-400" />
                Saved AI Views
                <span className="text-sm font-normal text-slate-500">({savedViews.length})</span>
              </h4>
              <Button variant="ghost" size="sm" onClick={() => savedViewsQuery.refetch()} disabled={savedViewsQuery.isFetching}>
                Refresh
              </Button>
            </div>
            {savedViewsQuery.isLoading && <Loading message="Loading saved AI Views…" />}
            {!savedViewsQuery.isLoading && !savedViews.length && (
              <p className="text-sm text-slate-500">
                No saved AI Views yet. Generate one above and save it for future reference.
              </p>
            )}
            <div className="space-y-2">
              {savedViews.map((v) => (
                <div
                  key={v.id}
                  className={`rounded-lg border px-3 py-2.5 text-sm ${
                    viewedSavedId === v.id ? 'border-violet-500/50 bg-violet-500/5' : 'border-slate-800/60 bg-slate-900/40'
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <button
                        className="font-medium text-slate-200 hover:text-violet-400"
                        onClick={() => setViewedSavedId(viewedSavedId === v.id ? null : v.id)}
                      >
                        {v.name}
                      </button>
                      {v.summary?.verdict && <span className="ml-2"><Badge action={v.summary.verdict} /></span>}
                      <p className="mt-0.5 text-xs text-slate-500">
                        Saved {formatWhen(v.created_at)}
                        {v.updated_at ? ` · edited ${formatWhen(v.updated_at)}` : ''}
                        {v.summary?.video_count != null ? ` · ${v.summary.video_count} video(s)` : ''}
                      </p>
                      {v.summary?.report_preview && viewedSavedId !== v.id && (
                        <p className="mt-1 text-xs text-slate-400 line-clamp-2">{v.summary.report_preview}…</p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => startEdit(v)}
                        disabled={editLoading}
                        title="Edit"
                      >
                        <Pencil size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (window.confirm(`Delete saved AI View "${v.name}"? This cannot be undone.`)) {
                            deleteViewMut.mutate(v.id)
                          }
                        }}
                        title="Delete"
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>

                  {editingId === v.id && (
                    <div className="mt-3 space-y-2 border-t border-slate-800/60 pt-3">
                      <FormField label="Name">
                        <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
                      </FormField>
                      <FormField label="Report text">
                        <Textarea rows={10} value={editText} onChange={(e) => setEditText(e.target.value)} />
                      </FormField>
                      <div className="flex gap-2">
                        <Button
                          onClick={() => updateViewMut.mutate({ id: v.id, name: editName, report: editText })}
                          disabled={updateViewMut.isPending}
                        >
                          {updateViewMut.isPending ? 'Saving…' : 'Save changes'}
                        </Button>
                        <Button variant="ghost" onClick={() => setEditingId(null)}>Cancel</Button>
                      </div>
                    </div>
                  )}

                  {viewedSavedId === v.id && editingId !== v.id && (
                    <div className="mt-3 border-t border-slate-800/60 pt-3">
                      {viewedSavedQuery.isLoading ? (
                        <Loading message="Loading saved AI View…" />
                      ) : viewedSaved?.payload ? (
                        <>
                          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            {viewedSaved.payload.provider && <span>{viewedSaved.payload.provider} · {viewedSaved.payload.model}</span>}
                            {viewedSaved.payload.snapshot_note && <span>{viewedSaved.payload.snapshot_note}</span>}
                          </div>
                          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl border border-slate-700/60 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300">
                            {viewedSaved.payload.report}
                          </pre>
                        </>
                      ) : null}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>

          <div className="mb-2 text-sm font-medium text-slate-300">Transcripts by channel · date</div>
          <div className="space-y-3 mb-6">
            {channels.length === 0 && (
              <Card>
                <p className="text-slate-400 text-sm">
                  No videos matched (check URLs/IDs).
                </p>
              </Card>
            )}
            {channels.map((ch) => (
              <CollapsibleScrollSection
                key={ch.channel_id}
                title={ch.channel_title}
                subtitle={`${ch.video_count} video(s) · ${ch.transcript_count} transcript(s) · ${ch.channel_id}`}
                open={Boolean(openChannels[ch.channel_id])}
                onToggle={() =>
                  setOpenChannels((prev) => ({ ...prev, [ch.channel_id]: !prev[ch.channel_id] }))
                }
                scroll={false}
                maxHeightClass="max-h-[70vh]"
              >
                <div className="space-y-2">
                  {(ch.days || []).map((day) => {
                    const dayKey = `${ch.channel_id}:${day.date}`
                    return (
                      <CollapsibleScrollSection
                        key={dayKey}
                        title={day.date}
                        subtitle={`${day.videos.length} video(s)`}
                        open={Boolean(openDays[dayKey])}
                        onToggle={() =>
                          setOpenDays((prev) => ({ ...prev, [dayKey]: !prev[dayKey] }))
                        }
                        maxHeightClass="max-h-96"
                      >
                        <div className="space-y-4">
                          {day.videos.map((v) => (
                            <div key={v.video_id} className="rounded-lg border border-slate-800/80 p-3">
                              <a
                                href={v.url}
                                target="_blank"
                                rel="noreferrer"
                                className="font-medium text-blue-400 hover:underline"
                              >
                                {v.title}
                              </a>
                              <p className="mt-0.5 text-xs text-slate-500">
                                {v.published_at || day.date} · {v.video_id}
                              </p>
                              {v.transcript ? (
                                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-slate-300">
                                  {v.transcript}
                                </pre>
                              ) : (
                                <p className="mt-2 text-xs text-amber-400/90">
                                  No transcript{v.transcript_error ? `: ${v.transcript_error}` : ''}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      </CollapsibleScrollSection>
                    )
                  })}
                </div>
              </CollapsibleScrollSection>
            ))}
          </div>

          {aiContext && (
            <AskAIPanel
              context={aiContext}
              systemPrompt={aiSystem || undefined}
              section="youtube-analysis/ask"
            />
          )}
        </>
      )}
    </div>
  )
}
