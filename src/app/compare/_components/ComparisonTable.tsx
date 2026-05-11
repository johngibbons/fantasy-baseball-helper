'use client'

import FormBadge from '@/components/FormBadge'

interface CompareSeason {
  games?: number | null
  plate_appearances?: number | null
  runs?: number | null
  home_runs?: number | null
  rbi?: number | null
  stolen_bases?: number | null
  obp?: number | null
  slg?: number | null
  ops?: number | null
}

interface CompareWindow {
  pa?: number | null
  r?: number | null
  hr?: number | null
  rbi?: number | null
  sb?: number | null
  obp?: number | null
  ops?: number | null
}

interface CompareSavant {
  xwoba?: number | null
  woba?: number | null
  luck_gap?: number | null
  xba?: number | null
  xslg?: number | null
  sprint_speed?: number | null
}

export interface PlayerCompare {
  mlb_id: number
  name?: string | null
  team?: string | null
  position?: string | null
  is_on_il?: boolean
  status_code?: string | null
  last_played?: string | null
  season?: CompareSeason
  last_14d?: CompareWindow
  last_30d?: CompareWindow
  savant?: CompareSavant
  form_level?: 'hot' | 'cool' | 'cold' | 'neutral' | null
}

function fmt(n?: number | null, digits = 3): string {
  if (n == null) return '-'
  return n.toFixed(digits)
}

function fmtInt(n?: number | null): string {
  if (n == null) return '-'
  return String(n)
}

const rows: { label: string; fn: (p: PlayerCompare) => string }[] = [
  { label: 'Team',           fn: (p) => p.team ?? '-' },
  { label: 'IL?',            fn: (p) => p.is_on_il ? `Yes (${p.status_code ?? ''})` : 'No' },
  { label: 'Season G',       fn: (p) => fmtInt(p.season?.games) },
  { label: 'Season PA',      fn: (p) => fmtInt(p.season?.plate_appearances) },
  { label: 'Season OBP',     fn: (p) => fmt(p.season?.obp) },
  { label: 'Season OPS',     fn: (p) => fmt(p.season?.ops) },
  { label: 'Season HR/RBI/SB', fn: (p) => `${p.season?.home_runs ?? 0}/${p.season?.rbi ?? 0}/${p.season?.stolen_bases ?? 0}` },
  { label: '14d OBP/OPS',    fn: (p) => `${fmt(p.last_14d?.obp)} / ${fmt(p.last_14d?.ops)}` },
  { label: '30d OBP/OPS',    fn: (p) => `${fmt(p.last_30d?.obp)} / ${fmt(p.last_30d?.ops)}` },
  { label: 'Savant xwOBA',   fn: (p) => fmt(p.savant?.xwoba) },
  { label: 'Savant wOBA',    fn: (p) => fmt(p.savant?.woba) },
  { label: 'Luck gap',       fn: (p) => fmt(p.savant?.luck_gap) },
  { label: 'xBA / xSLG',     fn: (p) => `${fmt(p.savant?.xba)} / ${fmt(p.savant?.xslg)}` },
  { label: 'Sprint speed',   fn: (p) => fmt(p.savant?.sprint_speed, 1) },
]

export default function ComparisonTable({ players }: { players: PlayerCompare[] }) {
  if (!players.length) {
    return <div className="text-gray-500 text-sm">Add players above to compare.</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-gray-700">
            <th className="text-left p-2 text-gray-400"></th>
            {players.map((p) => (
              <th key={p.mlb_id} className="text-left p-2">
                <div className="text-white font-medium flex items-center gap-1.5">
                  {p.name ?? `Player ${p.mlb_id}`}
                  <FormBadge level={p.form_level ?? null} />
                </div>
                <div className="text-xs text-gray-400">{p.team ?? ''} {p.position ?? ''}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, fn }) => (
            <tr key={label} className="border-b border-gray-800">
              <td className="p-2 text-gray-400">{label}</td>
              {players.map((p) => (
                <td key={p.mlb_id} className="p-2 text-gray-200 font-mono">{fn(p)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
