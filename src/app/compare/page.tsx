'use client'
import { useState } from 'react'
import PlayerPicker, { PlayerResult } from './_components/PlayerPicker'
import ComparisonTable, { PlayerCompare } from './_components/ComparisonTable'

export default function ComparePage() {
  const [selected, setSelected] = useState<PlayerResult[]>([])
  const [stats, setStats] = useState<PlayerCompare[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh(players: PlayerResult[]) {
    if (!players.length) { setStats([]); return }
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mlb_ids: players.map((p) => p.id), season: 2026 }),
      })
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}))
        throw new Error(d.error || `Error ${resp.status}`)
      }
      const d = await resp.json()
      setStats(d.players || [])
    } catch (e: any) {
      setError(e.message || 'Failed to load comparison')
    } finally {
      setLoading(false)
    }
  }

  function add(p: PlayerResult) {
    if (selected.some((s) => s.id === p.id)) return
    const next = [...selected, p]
    setSelected(next)
    refresh(next)
  }

  function remove(id: number) {
    const next = selected.filter((p) => p.id !== id)
    setSelected(next)
    refresh(next)
  }

  return (
    <div className="p-6">
      <h1 className="text-xl text-white mb-4">Player Comparison</h1>
      <div className="flex gap-2 mb-4 items-center flex-wrap">
        <PlayerPicker onAdd={add} />
        {selected.map((p) => (
          <span key={p.id} className="bg-gray-800 px-2 py-1 rounded text-sm text-white flex items-center gap-1.5">
            {p.fullName}
            <button
              onClick={() => remove(p.id)}
              className="text-red-400 hover:text-red-300 font-bold"
              aria-label={`Remove ${p.fullName}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      {loading && <div className="text-sm text-gray-400 mb-2">Loading...</div>}
      {error && <div className="text-sm text-red-400 mb-2">{error}</div>}
      <ComparisonTable players={stats} />
    </div>
  )
}
