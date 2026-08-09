import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { ExternalLink, Flame } from 'lucide-react'
import { apiErrorMessage, runMfFirePlan } from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { Alert, Loading } from '../components/ui/Feedback'
import { FormField, Input } from '../components/ui/Form'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'

type Row = Record<string, unknown>

const YOUTUBE = 'https://www.youtube.com/watch?v=HmW6T6i2Okc&t=6s'

const HOW_TO_COPY = `MF FIRE — How to use this planner

Source: ${YOUTUBE}
("He Became Financially Free at 38 With Mutual Funds. Here's How")

1. Enter annual expenses → the planner sizes your 25× FI number (and 35× long runway).
2. Enter monthly salary → see the 1% rule portfolio (1% of corpus ≈ one month's pay).
3. Enter current MF corpus + monthly SIP + expected equity return → ETA to first crore, 2 Cr, and FIRE.
4. Optional: age, dual income, home-loan extra EMI vs SIP comparison.
5. Read the principles checklist; shortlist schemes on Best MF.
6. Research / education only — not financial advice.`

const PRINCIPLES_GUIDE = `Eight principles from the video

1. 25× Framework — FI ≈ 25 × annual expenses; ~35× for a longer inflation-aware runway.
2. 1% Rule — grow until a 1% market day ≈ monthly salary (wealth does the heavy lifting).
3. Mutual Funds over direct stocks / trading — outsource picking; avoid "quick money" trading.
4. 100% equity while accumulating — allocation preserves wealth; equity creates it until ~₹2–5 Cr.
5. First ₹1 Cr is hardest — patience + rising SIPs; second crore came much faster for the speaker.
6. Don't blindly pre-close low-interest home loans — starving SIPs can delay compounding.
7. Retirement first — you can loan education; nobody loans you a retirement.
8. Peak earning years (~35–40) — raise income hard; dual income into SIPs.`

function fmtInr(v: unknown) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function fmtCr(v: unknown) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `₹${(n / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`
}

function etaLabel(eta: Row | undefined | null) {
  if (!eta) return '—'
  if (eta.reachable === false && eta.months == null) return String(eta.note ?? 'Not reachable')
  if (eta.months === 0) return 'Already there'
  if (eta.years != null) return `~${eta.years} yrs${eta.note ? ` · ${eta.note}` : ''}`
  return String(eta.note ?? '—')
}

function ProgressBar({ pct, color = 'bg-emerald-500' }: { pct: number; color?: string }) {
  const w = Math.max(0, Math.min(100, pct))
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${w}%` }} />
    </div>
  )
}

export default function MfFire() {
  const [annualExpenses, setAnnualExpenses] = useState(600_000)
  const [monthlySalary, setMonthlySalary] = useState(100_000)
  const [currentCorpus, setCurrentCorpus] = useState(500_000)
  const [monthlySip, setMonthlySip] = useState(25_000)
  const [returnPct, setReturnPct] = useState(12)
  const [inflationPct, setInflationPct] = useState(6.5)
  const [age, setAge] = useState(35)
  const [dualIncome, setDualIncome] = useState(false)
  const [equityUntilCr, setEquityUntilCr] = useState(3)
  const [loanBalance, setLoanBalance] = useState(0)
  const [loanRate, setLoanRate] = useState(8.5)
  const [extraEmi, setExtraEmi] = useState(0)
  const [checklist, setChecklist] = useState<string[]>([])
  const [error, setError] = useState('')

  const buildPayload = () => ({
    annual_expenses: annualExpenses,
    monthly_salary: monthlySalary,
    current_corpus: currentCorpus,
    monthly_sip: monthlySip,
    expected_equity_return_pct: returnPct,
    inflation_pct: inflationPct,
    equity_only_until_cr: equityUntilCr,
    age,
    home_loan_balance: loanBalance,
    home_loan_rate_pct: loanRate,
    extra_emi_toward_loan: extraEmi,
    dual_income: dualIncome,
    principles_checklist: checklist,
  })

  const runMut = useMutation({
    mutationFn: () => runMfFirePlan(buildPayload()),
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Row | undefined
  const fire = (data?.fire as Row | undefined) ?? undefined
  const onePct = (data?.one_percent_rule as Row | undefined) ?? undefined
  const allocation = (data?.allocation as Row | undefined) ?? undefined
  const peak = (data?.peak_earning_years as Row | undefined) ?? undefined
  const loanCmp = (data?.home_loan_vs_sip as Row | null | undefined) ?? null
  const scorecard = (data?.scorecard as Row[] | undefined) ?? []
  const projection = ((data?.projection as Row | undefined)?.series as Row[] | undefined) ?? []
  const nextSteps = (data?.next_steps as Row[] | undefined) ?? []
  const principles = (data?.principles as Row[] | undefined) ?? []
  const askContext = data ? buildAskContext('MF FIRE', data) : ''

  const statusTone = useMemo(() => {
    const s = String(data?.status ?? '')
    if (s === 'LONG_RUNWAY_FI' || s === 'FI_25X') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
    if (s === 'PAST_FIRST_CRORE') return 'border-sky-500/40 bg-sky-500/10 text-sky-300'
    return 'border-amber-500/40 bg-amber-500/10 text-amber-200'
  }, [data?.status])

  const toggleCheck = (id: string) =>
    setChecklist((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  return (
    <div>
      <PageHeader
        title="MF FIRE"
        description="Mutual Funds path to Financial Independence — 25× corpus, 1% rule, crore milestones & SIP runway"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this planner" defaultOpen copyText={HOW_TO_COPY}>
          <ol className="list-decimal space-y-1.5 pl-4 text-sm text-slate-300">
            <li>Enter <strong className="text-slate-100">annual expenses</strong> — we size your <strong className="text-slate-100">25× FI number</strong> (and 35× long runway).</li>
            <li>Enter <strong className="text-slate-100">monthly salary</strong> — see the <strong className="text-slate-100">1% rule</strong> portfolio target.</li>
            <li>Add <strong className="text-slate-100">current corpus + monthly SIP</strong> — ETA to first crore, ₹2 Cr, and FIRE.</li>
            <li>Optional: age, dual income, home-loan extra EMI vs equity SIP comparison.</li>
            <li>Shortlist schemes on <Link className="text-sky-400 hover:underline" to="/best-mf">Best MF</Link>. Research only — not advice.</li>
          </ol>
          <a
            href={YOUTUBE}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex items-center gap-1.5 text-sm text-sky-400 hover:text-sky-300"
          >
            Watch strategy video <ExternalLink size={14} />
          </a>
        </CollapsibleSection>

        <CollapsibleSection title="How it works — eight principles" defaultOpen copyText={PRINCIPLES_GUIDE}>
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              ['25× Framework', 'FI corpus ≈ 25 × annual expenses; ~35× for longevity under inflation.'],
              ['1% Rule', 'Portfolio where a 1% up-day ≈ monthly salary — capital does the heavy lifting.'],
              ['Mutual Funds over stocks/trading', '~98–99% MFs; outsource stress; trading is wealth-injurious.'],
              ['100% equity while accumulating', 'Allocation preserves wealth; equity creates it until ~₹2–5 Cr.'],
              ['First ₹1 Cr is hardest', 'Speaker: ~8 years to first crore, ~2 years to the second.'],
              ['Don’t blindly prepay cheap loans', 'Starving SIPs to close a home loan can delay compounding.'],
              ['Retirement first', 'Loan education if needed — nobody loans you a retirement.'],
              ['Peak earning years (~35–40)', 'Raise income hard; dual income into SIPs.'],
            ].map(([t, b]) => (
              <div key={t} className="rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2">
                <p className="text-sm font-medium text-slate-200">{t}</p>
                <p className="mt-0.5 text-xs text-slate-500">{b}</p>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex items-center gap-2 text-sm text-slate-400">
          <Flame size={16} className="text-amber-400" />
          Your numbers
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Annual expenses (₹)">
            <Input type="number" min={0} value={annualExpenses} onChange={(e) => setAnnualExpenses(Number(e.target.value) || 0)} />
          </FormField>
          <FormField label="Monthly salary (₹)">
            <Input type="number" min={0} value={monthlySalary} onChange={(e) => setMonthlySalary(Number(e.target.value) || 0)} />
          </FormField>
          <FormField label="Current MF corpus (₹)">
            <Input type="number" min={0} value={currentCorpus} onChange={(e) => setCurrentCorpus(Number(e.target.value) || 0)} />
          </FormField>
          <FormField label="Monthly SIP (₹)">
            <Input type="number" min={0} value={monthlySip} onChange={(e) => setMonthlySip(Number(e.target.value) || 0)} />
          </FormField>
          <FormField label="Expected equity return % p.a.">
            <Input type="number" step="0.1" min={0} max={30} value={returnPct} onChange={(e) => setReturnPct(Number(e.target.value) || 0)} />
          </FormField>
          <FormField label="Inflation % (context)">
            <Input type="number" step="0.1" min={0} max={20} value={inflationPct} onChange={(e) => setInflationPct(Number(e.target.value) || 0)} />
          </FormField>
          <FormField label="Age">
            <Input type="number" min={18} max={80} value={age} onChange={(e) => setAge(Number(e.target.value) || 35)} />
          </FormField>
          <FormField label="100% equity until (₹ Cr)">
            <Input type="number" step="0.5" min={0.5} max={20} value={equityUntilCr} onChange={(e) => setEquityUntilCr(Number(e.target.value) || 3)} />
          </FormField>
          <FormField label="Home loan balance (₹, optional)">
            <Input type="number" min={0} value={loanBalance} onChange={(e) => setLoanBalance(Number(e.target.value) || 0)} />
          </FormField>
          <FormField label="Home loan rate %">
            <Input type="number" step="0.1" min={0} max={25} value={loanRate} onChange={(e) => setLoanRate(Number(e.target.value) || 0)} />
          </FormField>
          <FormField label="Extra EMI you’d put to loan vs SIP (₹/mo)">
            <Input type="number" min={0} value={extraEmi} onChange={(e) => setExtraEmi(Number(e.target.value) || 0)} />
          </FormField>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Chip selected={dualIncome} onClick={() => setDualIncome((v) => !v)}>
            Dual-income household
          </Chip>
        </div>

        <div className="mt-4">
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-slate-500">Principles checklist (optional)</p>
          <div className="flex flex-wrap gap-2">
            {(principles.length
              ? principles
              : [
                  { id: '25x', title: '25× Framework' },
                  { id: 'one_pct', title: '1% Rule' },
                  { id: 'mf_not_stocks', title: 'MF over stocks' },
                  { id: 'full_equity', title: '100% equity accumulate' },
                  { id: 'first_crore', title: 'First ₹1 Cr focus' },
                  { id: 'home_loan', title: 'Loan vs SIP mindful' },
                  { id: 'retirement_first', title: 'Retirement first' },
                  { id: 'peak_years', title: 'Peak earning years' },
                ]
            ).map((p) => {
              const id = String(p.id)
              return (
                <Chip key={id} selected={checklist.includes(id)} onClick={() => toggleCheck(id)}>
                  {String(p.title ?? id)}
                </Chip>
              )
            })}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending}>
            {runMut.isPending ? 'Planning…' : 'Build MF FIRE plan'}
          </Button>
          <Link to="/best-mf" className="inline-flex items-center self-center text-sm text-sky-400 hover:text-sky-300">
            Rank mutual funds → Best MF
          </Link>
        </div>
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Sizing 25× / 1% rule / SIP runway…" />}

      {data && !runMut.isPending && (
        <>
          <Card className="mb-4 space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${statusTone}`}>
                {String(data.status ?? '').replace(/_/g, ' ')}
              </span>
              <span className="text-sm text-slate-400">Corpus {fmtCr(currentCorpus)}</span>
              {data.youtube != null && (
                <a href={String(data.youtube)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-sky-400">
                  Video <ExternalLink size={12} />
                </a>
              )}
            </div>
            {data.plain_english != null && (
              <p className="rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2.5 text-sm leading-relaxed text-slate-300">
                {String(data.plain_english)}
              </p>
            )}

            {fire && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
                  <p className="text-xs uppercase tracking-wide text-emerald-400/80">25× FIRE number</p>
                  <p className="mt-1 text-2xl font-semibold text-white">{fmtInr(fire.corpus_25x)}</p>
                  <p className="text-xs text-slate-500">{fmtCr(fire.corpus_25x)} · gap {fmtInr(fire.gap_25x)}</p>
                  <div className="mt-2">
                    <ProgressBar pct={Number(fire.progress_25x_pct ?? 0)} />
                    <p className="mt-1 text-xs text-slate-500">{Number(fire.progress_25x_pct ?? 0)}% there</p>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    4% withdraw capacity at 25× ≈ {fmtInr(fire.annual_withdraw_4pct_at_25x)} / year
                  </p>
                </div>
                <div className="rounded-xl border border-sky-500/20 bg-sky-500/5 p-4">
                  <p className="text-xs uppercase tracking-wide text-sky-400/80">35× long runway</p>
                  <p className="mt-1 text-2xl font-semibold text-white">{fmtInr(fire.corpus_35x)}</p>
                  <p className="text-xs text-slate-500">{fmtCr(fire.corpus_35x)} · gap {fmtInr(fire.gap_35x)}</p>
                  <div className="mt-2">
                    <ProgressBar pct={Number(fire.progress_35x_pct ?? 0)} color="bg-sky-500" />
                    <p className="mt-1 text-xs text-slate-500">{Number(fire.progress_35x_pct ?? 0)}% there</p>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{String(fire.inflation_note ?? '')}</p>
                </div>
              </div>
            )}

            {onePct && (
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
                <p className="text-xs uppercase tracking-wide text-amber-300/80">1% rule — psychological confidence</p>
                <p className="mt-1 text-xl font-semibold text-white">Target portfolio {fmtInr(onePct.target_portfolio)}</p>
                <p className="mt-1 text-sm text-slate-400">{String(onePct.plain_english ?? '')}</p>
                <div className="mt-2">
                  <ProgressBar pct={Number(onePct.progress_pct ?? 0)} color="bg-amber-500" />
                </div>
              </div>
            )}

            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Scorecard & ETA</p>
              <div className="space-y-2">
                {scorecard.map((row) => (
                  <div key={String(row.id)} className="rounded-lg border border-slate-800/70 bg-slate-950/30 px-3 py-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium text-slate-200">{String(row.label)}</span>
                      <span className="text-xs text-slate-500">ETA: {etaLabel(row.eta as Row)}</span>
                    </div>
                    <p className="text-xs text-slate-500">
                      Target {String(row.target_label ?? fmtInr(row.target))} · gap {fmtInr(row.gap)}
                    </p>
                    <div className="mt-1.5">
                      <ProgressBar pct={Number(row.progress_pct ?? 0)} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {allocation && (
              <div className="rounded-lg border border-slate-800/70 px-3 py-2.5 text-sm text-slate-300">
                <span className="font-medium text-slate-100">Allocation: </span>
                {String(allocation.mode)} — suggested equity {String(allocation.equity_pct_suggested)}%
                <p className="mt-1 text-xs text-slate-500">{String(allocation.plain_english ?? '')}</p>
              </div>
            )}

            {peak && (
              <div className="rounded-lg border border-slate-800/70 px-3 py-2.5">
                <p className="text-sm font-medium text-slate-200">Peak earning years</p>
                <p className="mt-1 text-xs text-slate-500">{String(peak.plain_english ?? '')}</p>
                <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-500">
                  {((peak.actions as string[]) ?? []).map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </div>
            )}

            {loanCmp && (
              <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2.5 text-sm text-slate-300">
                <p className="font-medium text-rose-200">Home loan vs SIP (10-year sketch)</p>
                <p className="mt-1 text-xs text-slate-400">{String(loanCmp.plain_english ?? '')}</p>
              </div>
            )}

            {projection.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
                  Corpus projection ({returnPct}% p.a., SIP {fmtInr(monthlySip)}/mo)
                </p>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-left text-xs text-slate-400">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-500">
                        <th className="px-2 py-1.5 font-medium">Year</th>
                        <th className="px-2 py-1.5 font-medium">Corpus</th>
                        <th className="px-2 py-1.5 font-medium">₹ Cr</th>
                      </tr>
                    </thead>
                    <tbody>
                      {projection.filter((_, i) => i % 1 === 0).map((row) => (
                        <tr key={String(row.year)} className="border-b border-slate-900/80">
                          <td className="px-2 py-1.5">{String(row.year)}</td>
                          <td className="px-2 py-1.5 text-slate-200">{fmtInr(row.corpus)}</td>
                          <td className="px-2 py-1.5">{Number(row.corpus_cr).toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {nextSteps.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Next steps</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {nextSteps.map((s) => (
                    <div key={String(s.title)} className="rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2">
                      <p className="text-sm font-medium text-slate-200">{String(s.title)}</p>
                      <p className="mt-0.5 text-xs text-slate-500">{String(s.detail)}</p>
                      {s.link != null && (
                        <Link to={String(s.link)} className="mt-1 inline-block text-xs text-sky-400 hover:underline">
                          Open →
                        </Link>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.disclaimer != null && (
              <p className="text-[11px] text-slate-600">{String(data.disclaimer)}</p>
            )}
          </Card>

          {askContext && (
            <AskAIPanel
              context={askContext}
              section="mf-fire"
              systemPrompt="You are helping with an MF FIRE (mutual fund financial independence) planner based on the 25× expenses framework, 1% salary rule, and equity MF accumulation. Be practical, India-aware, and remind the user this is education not advice."
            />
          )}
        </>
      )}
    </div>
  )
}
