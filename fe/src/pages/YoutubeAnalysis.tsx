import { useEffect, useMemo, useState } from 'react'
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

function isoDate(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function defaultRange() {
  const to = new Date()
  const from = new Date()
  from.setDate(from.getDate() - 4) // inclusive 5-day window
  return { from: isoDate(from), to: isoDate(to) }
}

function parseChannels(raw: string) {
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
  const range0 = useMemo(() => defaultRange(), [])
  const qc = useQueryClient()
  const { data: prefs, isLoading: prefsLoading } = useQuery({
    queryKey: ['youtube-analysis-prefs'],
    queryFn: fetchYoutubeAnalysisPrefs,
  })

  const [apiKey, setApiKey] = useState('')
  const [channelsRaw, setChannelsRaw] = useState('')
  const [keySaved, setKeySaved] = useState(false)
  const [hydrated, setHydrated] = useState(false)
  const [showProxy, setShowProxy] = useState(false)
  const [webshareUser, setWebshareUser] = useState('')
  const [websharePass, setWebsharePass] = useState('')
  const [websharePassSaved, setWebsharePassSaved] = useState(false)
  const [httpProxy, setHttpProxy] = useState('')
  const [httpsProxy, setHttpsProxy] = useState('')
  const [fromDate, setFromDate] = useState(range0.from)
  const [toDate, setToDate] = useState(range0.to)
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
    setChannelsRaw(prefs.youtube_channel_ids || '')
    setKeySaved(Boolean(prefs.youtube_api_key_set))
    setWebshareUser(prefs.webshare_username || '')
    setWebsharePassSaved(Boolean(prefs.webshare_password_set))
    setHttpProxy(prefs.http_proxy || '')
    setHttpsProxy(prefs.https_proxy || '')
    if (prefs.proxy_configured) setShowProxy(true)
    setHydrated(true)
  }, [prefs, hydrated])

  const channelList = parseChannels(channelsRaw)
  const hasSavedKey = keySaved || Boolean(prefs?.youtube_api_key_set)

  const savePrefsMut = useMutation({
    mutationFn: () =>
      saveYoutubeAnalysisPrefs({
        youtube_api_key: apiKey.trim() || undefined,
        youtube_channel_ids: channelsRaw,
        youtube_webshare_username: webshareUser,
        youtube_webshare_password: websharePass.trim() || undefined,
        youtube_http_proxy: httpProxy,
        youtube_https_proxy: httpsProxy,
      }),
    onSuccess: (data) => {
      setKeySaved(Boolean(data.youtube_api_key_set))
      if (apiKey.trim()) setApiKey('')
      if (websharePass.trim()) {
        setWebsharePass('')
        setWebsharePassSaved(true)
      }
      setChannelsRaw(data.youtube_channel_ids || channelsRaw)
      setWebshareUser(data.webshare_username || webshareUser)
      setHttpProxy(data.http_proxy || httpProxy)
      setHttpsProxy(data.https_proxy || httpsProxy)
      setWebsharePassSaved(Boolean(data.webshare_password_set))
      setPrefsMsg('Saved for your account — will be reused until you change them.')
      setError('')
      qc.invalidateQueries({ queryKey: ['youtube-analysis-prefs'] })
      qc.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const scanMut = useMutation({
    mutationFn: () => {
      if (!channelList.length) throw new Error('Enter at least one channel ID or @handle')
      if (!apiKey.trim() && !hasSavedKey) {
        throw new Error('Enter a YouTube Data API key (it will be saved for your account)')
      }
      return runYoutubeAnalysisScan({
        youtube_api_key: apiKey.trim() || undefined,
        channel_ids: channelList,
        from_date: fromDate,
        to_date: toDate,
        webshare_username: webshareUser.trim() || undefined,
        webshare_password: websharePass.trim() || undefined,
        http_proxy: httpProxy.trim() || undefined,
        https_proxy: httpsProxy.trim() || undefined,
      })
    },
    onError: (e) => {
      setError(apiErrorMessage(e))
      setAiView(null)
    },
    onSuccess: (data) => {
      setError('')
      setPrefsMsg('API key, channels & proxy prefs saved for your account.')
      setAiView(null)
      setKeySaved(true)
      if (apiKey.trim()) setApiKey('')
      if (websharePass.trim()) {
        setWebsharePass('')
        setWebsharePassSaved(true)
      }
      const savedChannels = String(data.youtube_channel_ids || '')
      if (savedChannels) setChannelsRaw(savedChannels)
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
        description="Pull recent channel videos → transcripts → Ask AI / AI View for market impact"
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
          Key and channel IDs are saved to your account on Fetch or Save, and reused until you change them.
        </p>

        <FormField label="Channel IDs / @handles (one per line, or comma-separated)">
          <Textarea
            rows={4}
            value={channelsRaw}
            onChange={(e) => {
              setChannelsRaw(e.target.value)
              setPrefsMsg('')
            }}
            placeholder={'UC_x5XG1OV2P6uZZ5FSM9Ttw\n@CNBCTV18Live'}
          />
        </FormField>

        <div className="mt-4">
          <button
            type="button"
            className="text-sm text-blue-400 hover:underline"
            onClick={() => setShowProxy((v) => !v)}
          >
            {showProxy ? 'Hide' : 'Show'} proxy settings (fix IP bans)
            {(prefs?.proxy_configured || websharePassSaved || httpProxy || httpsProxy) ? ' · configured' : ''}
          </button>
          {showProxy && (
            <div className="mt-3 space-y-3 rounded-xl border border-slate-800/80 bg-slate-900/40 p-3">
              <p className="text-xs text-slate-500">
                YouTube often blocks transcript scrapers. We retry slowly and fall back to yt-dlp.
                If still blocked, use rotating residential proxies (e.g. Webshare) or any HTTP(S) proxy.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField label="Webshare proxy username">
                  <Input
                    value={webshareUser}
                    onChange={(e) => setWebshareUser(e.target.value)}
                    placeholder="from Webshare dashboard"
                    autoComplete="off"
                  />
                </FormField>
                <FormField label={`Webshare proxy password ${websharePassSaved ? '(saved)' : ''}`}>
                  <Input
                    type="password"
                    value={websharePass}
                    onChange={(e) => setWebsharePass(e.target.value)}
                    placeholder={websharePassSaved ? 'Leave blank to keep saved' : 'proxy password'}
                    autoComplete="new-password"
                  />
                </FormField>
                <FormField label="HTTP proxy URL">
                  <Input
                    value={httpProxy}
                    onChange={(e) => setHttpProxy(e.target.value)}
                    placeholder="http://user:pass@host:port"
                    autoComplete="off"
                  />
                </FormField>
                <FormField label="HTTPS proxy URL">
                  <Input
                    value={httpsProxy}
                    onChange={(e) => setHttpsProxy(e.target.value)}
                    placeholder="http://user:pass@host:port"
                    autoComplete="off"
                  />
                </FormField>
              </div>
            </div>
          )}
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-2 max-w-xl">
          <FormField label="From date">
            <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
          </FormField>
          <FormField label="To date">
            <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
          </FormField>
        </div>
        <p className="mt-1 text-xs text-slate-500">Default range is 5 calendar days (today − 4 → today).</p>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            onClick={() => scanMut.mutate()}
            disabled={scanMut.isPending || !channelList.length}
          >
            <span className="inline-flex items-center gap-2">
              <Clapperboard size={16} />
              {scanMut.isPending
                ? 'Fetching videos & transcripts…'
                : `Fetch transcripts (${channelList.length} channel${channelList.length === 1 ? '' : 's'})`}
            </span>
          </Button>
          <Button
            variant="secondary"
            onClick={() => savePrefsMut.mutate()}
            disabled={savePrefsMut.isPending || (!apiKey.trim() && !channelsRaw.trim() && !hasSavedKey)}
          >
            <span className="inline-flex items-center gap-2">
              <Save size={16} />
              {savePrefsMut.isPending ? 'Saving…' : 'Save prefs'}
            </span>
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              const r = defaultRange()
              setFromDate(r.from)
              setToDate(r.to)
            }}
            disabled={scanMut.isPending}
          >
            Reset to 5 days
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
        <Loading message="Fetching videos & transcripts…" />
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
                <p className="text-slate-400 text-sm">No videos found in this date range for the selected channels.</p>
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
