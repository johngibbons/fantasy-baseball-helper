'use client'

import { useState, useEffect } from 'react'
import InfoTip from '@/components/InfoTip'
import { tipForDelta, type DeltaColor } from '@/lib/waiver-symbol-copy'

interface Props {
  selectedLeague: string
  selectedTeam: string
  credentialsOk: boolean | null
}

interface PlayerRef { id: number; name: string; team?: string; position: string; roster_status?: string }

interface MetricDelta { value: number; badge: 'green' | 'yellow' | 'red' | 'gray' }

interface StealthRecommendation {
  rank: number
  player: PlayerRef
  skill_change_zscore: number
  headline_delta: { metric: string; label: string } | null
  metric_deltas: Record<string, MetricDelta>
  current_vs_projection: Record<string, { current: number | null; projected: number | null }>
  baseline_source: string | null
}

interface StealthResults {
  view: 'stealth'
  recommendations: StealthRecommendation[]
}

const badgeColor: Record<string, string> = {
  green: 'bg-emerald-500/20 text-emerald-300',
  yellow: 'bg-amber-500/20 text-amber-300',
  red: 'bg-red-500/20 text-red-300',
  gray: 'bg-gray-500/20 text-gray-400',
}

const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH', 'SP', 'RP']

export default function StealthTab({ selectedLeague, selectedTeam, credentialsOk }: Props) {
  const [scope, setScope] = useState<'FA' | 'rostered' | 'all'>('FA')
  const [posFilter, setPosFilter] = useState<string>('All')
  const [playerType, setPlayerType] = useState<'' | 'hitter' | 'pitcher'>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<StealthResults | null>(null)

  async function fetchRecommendations() {
    if (!selectedLeague || !selectedTeam) return
    setLoading(true); setError(null)
    try {
      const resp = await fetch('/api/breakouts/recommendations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: selectedLeague,
          teamId: selectedTeam,
          view: 'stealth',
          scope,
          position: posFilter === 'All' ? undefined : posFilter,
          playerType: playerType || undefined,
        }),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.error || `Error ${resp.status}`)
      }
      setResults(await resp.json())
    } catch (e: any) {
      setError(e.message || 'Failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (selectedLeague && selectedTeam && credentialsOk) {
      fetchRecommendations()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLeague, selectedTeam, credentialsOk, scope, posFilter, playerType])

  if (!selectedLeague || !selectedTeam) {
    return <div className="text-gray-400 text-sm">Select a league and team above.</div>
  }
  if (credentialsOk === false) {
    return <div className="text-amber-400 text-sm">No ESPN credentials saved for this league.</div>
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3 items-center mb-4">
        <label className="text-sm text-gray-400">
          Scope:
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as any)}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            <option value="FA">Free Agents</option>
            <option value="rostered">Rostered</option>
            <option value="all">All</option>
          </select>
        </label>
        <label className="text-sm text-gray-400">
          Position:
          <select
            value={posFilter}
            onChange={(e) => setPosFilter(e.target.value)}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            {POSITIONS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label className="text-sm text-gray-400">
          Type:
          <select
            value={playerType}
            onChange={(e) => setPlayerType(e.target.value as any)}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            <option value="">All</option>
            <option value="hitter">Hitters</option>
            <option value="pitcher">Pitchers</option>
          </select>
        </label>
      </div>

      {loading && <div className="text-gray-400 text-sm">Loading...</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {results && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-gray-400 border-b border-gray-800">
              <tr>
                <th className="text-left p-2">#</th>
                <th className="text-left p-2">Player</th>
                <th className="text-right p-2">Z</th>
                <th className="text-left p-2">Headline</th>
                <th className="text-left p-2">Metric Deltas</th>
                <th className="text-left p-2">Baseline</th>
              </tr>
            </thead>
            <tbody>
              {results.recommendations.map((r) => (
                <tr key={r.rank} className="border-b border-gray-900 hover:bg-gray-900/50">
                  <td className="p-2 text-gray-500">{r.rank}</td>
                  <td className="p-2">
                    <div className="font-medium">{r.player.name}</div>
                    <div className="text-xs text-gray-500">
                      {r.player.team} · {r.player.position} · {r.player.roster_status}
                    </div>
                  </td>
                  <td className="p-2 text-right text-emerald-300">
                    {r.skill_change_zscore.toFixed(2)}
                  </td>
                  <td className="p-2 text-emerald-400">{r.headline_delta?.label}</td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(r.metric_deltas).map(([k, m]) => {
                        const metricKey = k.replace('delta_', '')
                        return (
                          <InfoTip key={k} content={tipForDelta(metricKey, m.badge as DeltaColor)}>
                            <span className={`px-1.5 py-0.5 rounded text-xs ${badgeColor[m.badge]}`}>
                              {metricKey}: {m.value > 0 ? '+' : ''}{m.value}
                            </span>
                          </InfoTip>
                        )
                      })}
                    </div>
                  </td>
                  <td className="p-2 text-xs text-gray-500">{r.baseline_source}</td>
                </tr>
              ))}
              {results.recommendations.length === 0 && (
                <tr><td colSpan={6} className="p-4 text-center text-gray-500">No qualifying stealth breakouts.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
