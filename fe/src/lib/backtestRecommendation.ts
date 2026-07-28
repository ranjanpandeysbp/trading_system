/** Turns raw backtest stats into a plain-English "what should I do with
 * this" line — the numbers alone (win rate, return, drawdown) don't tell a
 * user what action to take; this does. */
export function backtestRecommendation(stats: {
  num_trades: number | null | undefined
  win_rate_pct: number | null | undefined
  total_return_pct: number | null | undefined
  max_drawdown_pct: number | null | undefined
}): string {
  const trades = stats.num_trades ?? 0
  const winRate = stats.win_rate_pct ?? null
  const totalReturn = stats.total_return_pct ?? 0
  const maxDD = stats.max_drawdown_pct ?? 0

  if (trades === 0) {
    return 'No completed trades in this window — nothing to act on yet. Try a longer period or a different timeframe.'
  }
  if (trades < 10) {
    return `Only ${trades} trade${trades === 1 ? '' : 's'} — too thin a sample to trust. Treat this as a hint, not a signal, until it's backed by more history.`
  }
  if (totalReturn <= 0) {
    return 'Lost money over this period — do not run this strategy on this ticker/timeframe as-is. Try a different strategy or a different market regime.'
  }
  if (winRate !== null && winRate >= 55 && maxDD > -20) {
    return 'Solid track record — a reasonable candidate to paper-trade forward before risking real capital. Still verify it holds up on more recent data.'
  }
  if (maxDD <= -30) {
    return `Profitable overall, but drawdowns as deep as ${maxDD.toFixed(1)}% mean real money would have hurt to hold through. Size any live position small.`
  }
  return 'Mixed but positive — usable with tight risk sizing while you build more confidence in it, not something to bet heavily on yet.'
}
