import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Clapperboard, Save, Sparkles } from 'lucide-react'
import {
  apiErrorMessage,
  fetchYoutubeAnalysisPrefs,
  runYoutubeAnalysisAiView,
  runYoutubeAnalysisScan,
  saveYoutubeAnalysisPrefs,
} from '../api/client'
import { AskAIPanel } from '../components/ai/AskAIPanel'
import { CollapsibleScrollSection } from '../components/command-center/CollapsibleScrollSection'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { Badge } from '../components/ui/Badge'

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

  const [apiKey, setApiKey] = useState('')
  const [videosRaw, setVideosRaw] = useState('')
  const [keySaved, setKeySaved] = useState(false)
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

  useEffect(() => {
    if (!prefs || hydrated) return
    setVideosRaw(prefs.youtube_channel_ids || '')
    setKeySaved(Boolean(prefs.youtube_api_key_set))
    setHydrated(true)
  }, [prefs, hydrated])

  const videoList = parseVideoList(videosRaw)
  const hasSavedKey = keySaved || Boolean(prefs?.youtube_api_key_set)
  const geminiReady = Boolean(prefs?.gemini_token_set)

  const savePrefsMut = useMutation({
    mutationFn: () =>
      saveYoutubeAnalysisPrefs({
        youtube_api_key: apiKey.trim() || undefined,
        youtube_channel_ids: videosRaw,
      }),
    onSuccess: (data) => {
      setKeySaved(Boolean(data.youtube_api_key_set))
      if (apiKey.trim()) setApiKey('')
      setVideosRaw(data.youtube_channel_ids || videosRaw)
      setPrefsMsg('Saved for your account — will be reused until you change them.')
      setError('')
      qc.invalidateQueries({ queryKey: ['youtube-analysis-prefs'] })
      qc.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const scanMut = useMutation({
    mutationFn: () => {
      if (!videoList.length) throw new Error('Enter at least one YouTube video URL or ID')
      if (!apiKey.trim() && !hasSavedKey) {
        throw new Error('Enter a YouTube Data API key (it will be saved for your account)')
      }
      if (!geminiReady) {
        throw new Error('Add a Gemini API key under Manage Settings (transcripts use Gemini YouTube URL analysis)')
      }
      return runYoutubeAnalysisScan({
        youtube_api_key: apiKey.trim() || undefined,
        video_urls: videoList,
      })
    },
    onError: (e) => {
      setError(apiErrorMessage(e))
      setAiView(null)
    },
    onSuccess: (data) => {
      setError('')
      setPrefsMsg('API key & video list saved for your account.')
      setAiView(null)
      setKeySaved(true)
      if (apiKey.trim()) setApiKey('')
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
      qc.invalidateQueries({ queryKey: ['settings'] })
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
    onSuccess: (data) => setAiView(data),
    onError: (e) => setError(apiErrorMessage(e)),
  })

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
        description="Listed YouTube videos · transcripts via Gemini · Ask AI / AI View"
      />

      <Card className="mb-4">
        <FormField
          label={`YouTube Data API key ${hasSavedKey ? '(saved for your account)' : ''}`}
        >
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value)
              setPrefsMsg('')
            }}
            placeholder={hasSavedKey ? 'Leave blank to keep using saved key' : 'AIza…'}
          />
        </FormField>
        <p className="mt-1 text-xs text-slate-500">
          Paste YouTube video URLs or IDs (comma-separated or one per line), then extract each
          transcript with Gemini. Gemini key:{' '}
          {geminiReady ? `saved · model ${prefs?.gemini_model || '—'}` : 'not set — add under Manage Settings'}.
        </p>

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
            disabled={scanMut.isPending || !videoList.length || !geminiReady}
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
            disabled={savePrefsMut.isPending || (!apiKey.trim() && !videosRaw.trim() && !hasSavedKey)}
          >
            <span className="inline-flex items-center gap-2">
              <Save size={16} />
              {savePrefsMut.isPending ? 'Saving…' : 'Save prefs'}
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
                <div className="flex items-center gap-2">
                  <Bot className="text-violet-400" size={18} />
                  <h3 className="font-semibold text-white">AI View</h3>
                  <span className="text-xs text-slate-500">
                    {aiView.provider} · {aiView.model}
                  </span>
                  {aiView.verdict && <Badge action={aiView.verdict} />}
                </div>
                <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-xl border border-slate-700/60 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300">
                  {aiView.report}
                </pre>
              </div>
            )}
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
