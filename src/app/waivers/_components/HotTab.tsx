'use client'

import { useState, useEffect, useMemo } from 'react'
import InfoTip from '@/components/InfoTip'
import { tipForSustain, type SustainColor } from '@/lib/waiver-symbol-copy'
import { SortableTh, compareValues, type SortDir } from './_sortable'

interface Props {
  selectedLeague: string
  selectedTeam: string
  credentialsOk: boolean | null
}

interface PlayerRef { id: number; name: string; position: string; team?: string; roster_status?: string }

interface HotRecommendation {
  rank: number
  add_player: PlayerRef
  drop_player: PlayerRef | null
  wins_added_if_rate_continues: number
  suggested_faab_bid: number
  window_stats: Record<string, number>
  sustainability_badges: Record<string, 'green' | 'yellow' | 'red' | 'gray'>
  sustainability_score: number
}

interface HotResults {
  as_of_date: string | null
  view: 'hot'
  window: number
  baseline_expected_wins: number
  recommendations: HotRecommendation[]
  remaining_faab: number
}

const badgeColor: Record<string, string> = {
  green: 'bg-emerald-500/20 text-emerald-300',
  yellow: 'bg-amber-500/20 text-amber-300',
  red: 'bg-red-500/20 text-red-300',
  gray: 'bg-gray-500/20 text-gray-400',
}

const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH', 'SP', 'RP']

export default function HotTab({ selectedLeague, selectedTeam, credentialsOk }: Props) {
  const [windowDays, setWindowDays] = useState<number>(14)
  const [scope, setScope] = useState<'FA' | 'rostered' | 'all'>('FA')
  const [posFilter, setPosFilter] = useState<string>('All')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<HotResults | null>(null)
  const [sortCol, setSortCol] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const onSort = (col: string) => {
    if (sortCol === col) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortCol(col)
      setSortDir(col === 'rank' || col === 'add' || col === 'drop' ? 'asc' : 'desc')
    }
  }

  const sortedRecs = useMemo(() => {
    const recs = results?.recommendations ?? []
    if (!sortCol) return recs
    const value = (r: HotRecommendation): number | string | null => {
      switch (sortCol) {
        case 'rank': return r.rank
        case 'add': return r.add_player.name
        case 'drop': return r.drop_player?.name ?? null
        case 'wins': return r.wins_added_if_rate_continues
        case 'badges': return r.sustainability_score
        case 'bid': return r.suggested_faab_bid
        default: return null
      }
    }
    return [...recs].sort((a, b) => compareValues(value(a), value(b), sortDir))
  }, [results, sortCol, sortDir])

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
          view: 'hot',
          window: windowDays,
          scope,
          position: posFilter === 'All' ? undefined : posFilter,
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
  }, [selectedLeague, selectedTeam, credentialsOk, windowDays, scope, posFilter])

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
          Window:
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(parseInt(e.target.value, 10))}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
        </label>
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
        {results?.as_of_date && (
          <span className="text-xs text-gray-500 ml-auto">Data as of {results.as_of_date}</span>
        )}
      </div>

      {loading && <div className="text-gray-400 text-sm">Loading...</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {results && (
        <div className="overflow-x-auto overflow-y-clip">
          <table className="min-w-full text-sm">
            <thead className="text-gray-400 border-b border-gray-800">
              <tr>
                <SortableTh col="rank" label="#" sortCol={sortCol} sortDir={sortDir} onSort={onSort} className="p-2" />
                <SortableTh col="add" label="Add" sortCol={sortCol} sortDir={sortDir} onSort={onSort} className="p-2" />
                <SortableTh col="drop" label="Drop" sortCol={sortCol} sortDir={sortDir} onSort={onSort} className="p-2" />
                <SortableTh col="wins" label="Wins+" sortCol={sortCol} sortDir={sortDir} onSort={onSort} align="right" className="p-2" />
                <th className="text-left p-2">Window</th>
                <SortableTh col="badges" label="Badges" sortCol={sortCol} sortDir={sortDir} onSort={onSort} className="p-2" />
                <SortableTh col="bid" label="Bid" sortCol={sortCol} sortDir={sortDir} onSort={onSort} align="right" className="p-2" />
              </tr>
            </thead>
            <tbody>
              {sortedRecs.map((r) => (
                <tr key={r.rank} className="border-b border-gray-900 hover:bg-gray-900/50">
                  <td className="p-2 text-gray-500">{r.rank}</td>
                  <td className="p-2">
                    <div className="font-medium">{r.add_player.name}</div>
                    <div className="text-xs text-gray-500">{r.add_player.position}</div>
                  </td>
                  <td className="p-2 text-gray-400">
                    {r.drop_player ? r.drop_player.name : '—'}
                  </td>
                  <td className="p-2 text-right text-emerald-400">
                    +{r.wins_added_if_rate_continues.toFixed(2)}
                  </td>
                  <td className="p-2 text-xs text-gray-400">
                    {r.window_stats?.pa
                      ? `${r.window_stats.pa} PA, .${(r.window_stats.obp * 1000 | 0).toString().padStart(3, '0')} OBP`
                      : r.window_stats?.ip
                        ? `${r.window_stats.ip} IP, ${r.window_stats.era?.toFixed(2)} ERA`
                        : ''}
                  </td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(r.sustainability_badges).map(([metric, color]) => (
                        <InfoTip key={metric} content={tipForSustain(metric, color as SustainColor)}>
                          <span className={`px-1.5 py-0.5 rounded text-xs ${badgeColor[color]}`}>
                            {metric.replace('_', ' ')}
                          </span>
                        </InfoTip>
                      ))}
                    </div>
                  </td>
                  <td className="p-2 text-right text-amber-300">
                    ${r.suggested_faab_bid}
                  </td>
                </tr>
              ))}
              {sortedRecs.length === 0 && (
                <tr><td colSpan={7} className="p-4 text-center text-gray-500">No qualifying breakouts in this window.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
