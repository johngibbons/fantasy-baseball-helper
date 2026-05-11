'use client'
import { useEffect, useState } from 'react'
import FormBadge from '@/components/FormBadge'

interface RosterValue {
  mlb_id: number
  name: string
  value_z: number
  form_level?: 'hot' | 'cool' | 'cold' | 'neutral' | null
}

interface Props {
  leagueId: string
  teamId: string
}

export default function RosterHealthSidebar({ leagueId, teamId }: Props) {
  const [data, setData] = useState<RosterValue[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!leagueId || !teamId) return
    setLoading(true)
    setError(null)
    fetch('/api/waivers/roster-health', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ leagueId, teamId, season: '2026' }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          throw new Error(d.error || `Error ${r.status}`)
        }
        return r.json()
      })
      .then((d) => setData(d.roster_value || []))
      .catch((e) => setError(e.message || 'Failed'))
      .finally(() => setLoading(false))
  }, [leagueId, teamId])

  if (!leagueId || !teamId) return null
  if (loading) return <div className="text-sm text-gray-500">Loading roster health...</div>
  if (error) return <div className="text-sm text-red-400">{error}</div>
  if (!data.length) return null

  const worst = data.slice(0, 5)
  const best = data.slice(-5).reverse()

  return (
    <div className="bg-gray-900 rounded p-4 text-sm">
      <h3 className="text-amber-300 font-medium mb-2">⚠️ Worst Rostered (drop candidates)</h3>
      <ul className="space-y-1 mb-4">
        {worst.map((p) => (
          <li key={p.mlb_id} className="flex justify-between items-center">
            <span className="text-gray-300 flex items-center gap-1.5">
              {p.name} <FormBadge level={p.form_level ?? null} />
            </span>
            <span className="text-red-400 font-mono">{p.value_z.toFixed(2)}</span>
          </li>
        ))}
      </ul>
      <h3 className="text-emerald-300 font-medium mb-2">🌟 Top Rostered (do not drop)</h3>
      <ul className="space-y-1">
        {best.map((p) => (
          <li key={p.mlb_id} className="flex justify-between items-center">
            <span className="text-gray-300 flex items-center gap-1.5">
              {p.name} <FormBadge level={p.form_level ?? null} />
            </span>
            <span className="text-emerald-400 font-mono">+{p.value_z.toFixed(2)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
