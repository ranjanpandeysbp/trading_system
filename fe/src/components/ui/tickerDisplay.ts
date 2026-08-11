/** Prefer API display_label / name for commodities (Gold · GC=F). */
export function tickerDisplayLabel(
  row: { ticker?: unknown; symbol?: unknown; name?: unknown; display_name?: unknown; display_label?: unknown } | null | undefined,
  fallback = '—',
): string {
  if (!row) return fallback
  if (row.display_label != null && String(row.display_label).trim()) return String(row.display_label)
  const sym = String(row.ticker ?? row.symbol ?? '').trim()
  const name = String(row.name ?? row.display_name ?? '').trim()
  if (name && sym && name.toUpperCase() !== sym.toUpperCase()) return `${name} (${sym})`
  if (name) return name
  return sym || fallback
}

export function tickerNameOnly(row: { name?: unknown; display_name?: unknown } | null | undefined): string | null {
  const name = String(row?.name ?? row?.display_name ?? '').trim()
  return name || null
}
