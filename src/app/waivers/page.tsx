'use client'

import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'

interface League {
  id: string
  name: string
  platform: string
  season: string
  externalId?: string
}

interface Team {
  id: string
  externalId: string
  name: string
  ownerName?: string
}

interface PlayerRef {
  id: number
  name: string
  position: string
}

interface Recommendation {
  rank: number
  add_player: PlayerRef
  drop_player: PlayerRef | null
  delta_expected_wins: number
  suggested_faab_bid: number
  category_impact: Record<string, number>
}

interface WaiverResults {
  baseline_expected_wins: number
  baseline_category_probs: Record<string, number>
  recommendations: Recommendation[]
  remaining_faab: number
  my_roster_count: number
  free_agent_count: number
  other_teams_count: number
}

const CATS = ['R', 'TB', 'RBI', 'SB', 'OBP', 'K', 'QS', 'ERA', 'WHIP', 'SVHD']
const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'LF', 'CF', 'RF', 'DH', 'SP', 'RP']

const posColors: Record<string, string> = {
  C: 'text-blue-400', '1B': 'text-amber-400', '2B': 'text-orange-400', '3B': 'text-purple-400',
  SS: 'text-red-400', OF: 'text-emerald-400', LF: 'text-emerald-400', CF: 'text-teal-400',
  RF: 'text-emerald-400', DH: 'text-gray-400', SP: 'text-sky-400', RP: 'text-pink-400',
}

function impactColor(v: number): string {
  if (v > 0.05) return 'text-emerald-300 bg-emerald-500/20'
  if (v > 0.01) return 'text-emerald-400'
  if (v > -0.01) return 'text-gray-500'
  if (v > -0.05) return 'text-red-400'
  return 'text-red-300 bg-red-500/20'
}

function fmtDelta(v: number): string {
  const s = v.toFixed(3)
  return v > 0 ? `+${s}` : s
}

function fmtCatImpact(v: number): string {
  const pct = (v * 100).toFixed(1)
  return v > 0 ? `+${pct}` : pct
}

export default function WaiversPage() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState<string>('')
  const [selectedTeam, setSelectedTeam] = useState<string>('')
  const [swid, setSwid] = useState('')
  const [espnS2, setEspnS2] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<WaiverResults | null>(null)
  const [posFilter, setPosFilter] = useState('All')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null)

  const handleRefreshProjections = async () => {
    setRefreshing(true)
    setRefreshStatus(null)
    try {
      const resp = await fetch('/api/v2/waivers/refresh-projections?season=2026', { method: 'POST' })
      if (!resp.ok) throw new Error(`Error ${resp.status}`)
      const data = await resp.json()
      setRefreshStatus(`Updated: ${data.results?.batting ?? 0} hitters, ${data.results?.pitching ?? 0} pitchers`)
    } catch (err: any) {
      setRefreshStatus(`Failed: ${err.message}`)
    } finally {
      setRefreshing(false)
    }
  }

  // Load leagues and stored credentials
  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => r.ok ? r.json() : [])
      .then(setLeagues)
      .catch(() => {})

    const stored = localStorage.getItem('espn_credentials')
    if (stored) {
      try {
        const { swid: s, espn_s2: e } = JSON.parse(stored)
        if (s) setSwid(s)
        if (e) setEspnS2(e)
      } catch {}
    }
  }, [])

  // Load teams when league changes
  useEffect(() => {
    if (!selectedLeague) return
    fetch(`/api/leagues/${selectedLeague}/teams`)
      .then((r) => r.ok ? r.json() : { teams: [] })
      .then((data) => setTeams(data.teams || []))
      .catch(() => {})
  }, [selectedLeague])

  // Save credentials to localStorage when they change
  useEffect(() => {
    if (swid && espnS2) {
      localStorage.setItem('espn_credentials', JSON.stringify({ swid, espn_s2: espnS2 }))
    }
  }, [swid, espnS2])

  const handleFetchRecommendations = async () => {
    if (!selectedLeague || !selectedTeam || !swid || !espnS2) {
      setError('Please select a league, team, and provide ESPN credentials')
      return
    }

    setLoading(true)
    setError(null)
    setResults(null)

    try {
      const response = await fetch('/api/waivers/recommendations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: selectedLeague,
          teamId: selectedTeam,
          swid,
          espn_s2: espnS2,
        }),
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || `Error ${response.status}`)
      }

      const data = await response.json()
      setResults(data)
    } catch (err: any) {
      setError(err.message || 'Failed to fetch recommendations')
    } finally {
      setLoading(false)
    }
  }

  const filteredRecs = useMemo(() => {
    if (!results) return []
    if (posFilter === 'All') return results.recommendations
    return results.recommendations.filter(
      (r) => r.add_player.position === posFilter ||
             r.add_player.position === 'OF' && ['LF', 'CF', 'RF'].includes(posFilter)
    )
  }, [results, posFilter])

  return (
    <main className="min-h-screen bg-[#0d1117] text-gray-300">
      <div className="max-w-[90rem] mx-auto px-4 sm:px-6 py-6">
        <h1 className="text-xl font-bold text-white mb-4">Waiver Wire Recommendations</h1>

        {/* Config panel */}
        <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-4 mb-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {/* League selector */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">League</label>
              <select
                value={selectedLeague}
                onChange={(e) => { setSelectedLeague(e.target.value); setSelectedTeam('') }}
                className="w-full bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
              >
                <option value="">Select league...</option>
                {leagues.map((l) => (
                  <option key={l.id} value={l.id}>{l.name} ({l.season})</option>
                ))}
              </select>
            </div>

            {/* Team selector */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">My Team</label>
              <select
                value={selectedTeam}
                onChange={(e) => setSelectedTeam(e.target.value)}
                className="w-full bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
              >
                <option value="">Select team...</option>
                {teams.map((t) => (
                  <option key={t.externalId} value={t.externalId}>
                    {t.name}{t.ownerName ? ` (${t.ownerName})` : ''}
                  </option>
                ))}
              </select>
            </div>

            {/* ESPN SWID */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">ESPN SWID</label>
              <input
                type="password"
                value={swid}
                onChange={(e) => setSwid(e.target.value)}
                placeholder="Paste SWID cookie..."
                className="w-full bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
              />
            </div>

            {/* ESPN S2 */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">ESPN S2</label>
              <input
                type="password"
                value={espnS2}
                onChange={(e) => setEspnS2(e.target.value)}
                placeholder="Paste espn_s2 cookie..."
                className="w-full bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
              />
            </div>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={handleFetchRecommendations}
              disabled={loading || !selectedLeague || !selectedTeam || !swid || !espnS2}
              className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading ? 'Analyzing...' : 'Get Recommendations'}
            </button>
            <button
              onClick={handleRefreshProjections}
              disabled={refreshing}
              className="px-4 py-1.5 bg-[#0d1117] border border-white/10 text-gray-300 text-sm font-medium rounded hover:border-white/20 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {refreshing ? 'Refreshing...' : 'Refresh RoS Projections'}
            </button>
            {loading && (
              <span className="text-xs text-gray-500">
                Fetching rosters & computing expected wins...
              </span>
            )}
            {refreshStatus && (
              <span className={`text-xs ${refreshStatus.startsWith('Failed') ? 'text-red-400' : 'text-emerald-400'}`}>
                {refreshStatus}
              </span>
            )}
          </div>
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-500/30 rounded-lg p-3 mb-4 text-sm text-red-400">
            {error}
          </div>
        )}

        {/* Results */}
        {results && (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3">
                <div className="text-xs text-gray-500">Baseline Expected Wins</div>
                <div className="text-lg font-bold text-white">
                  {results.baseline_expected_wins.toFixed(2)}
                  <span className="text-xs text-gray-500 font-normal"> / 10</span>
                </div>
              </div>
              <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3">
                <div className="text-xs text-gray-500">FAAB Remaining</div>
                <div className="text-lg font-bold text-white">${results.remaining_faab}</div>
              </div>
              <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3">
                <div className="text-xs text-gray-500">Free Agents Analyzed</div>
                <div className="text-lg font-bold text-white">{results.free_agent_count}</div>
              </div>
              <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3">
                <div className="text-xs text-gray-500">Positive Pickups</div>
                <div className="text-lg font-bold text-emerald-400">
                  {results.recommendations.filter((r) => r.delta_expected_wins > 0).length}
                </div>
              </div>
            </div>

            {/* Category baseline */}
            <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3 mb-4">
              <div className="text-xs text-gray-500 mb-2">Category Win Probabilities (Baseline)</div>
              <div className="flex gap-2 flex-wrap">
                {CATS.map((cat) => {
                  const prob = results.baseline_category_probs[cat] ?? 0
                  const pct = (prob * 100).toFixed(0)
                  const color = prob >= 0.65 ? 'text-emerald-400' : prob >= 0.45 ? 'text-yellow-400' : 'text-red-400'
                  return (
                    <div key={cat} className="text-center min-w-[3rem]">
                      <div className="text-[10px] text-gray-500">{cat}</div>
                      <div className={`text-sm font-mono font-bold ${color}`}>{pct}%</div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Position filter */}
            <div className="flex gap-1 mb-3 flex-wrap">
              {POSITIONS.map((pos) => (
                <button
                  key={pos}
                  onClick={() => setPosFilter(pos)}
                  className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                    posFilter === pos
                      ? 'bg-white/10 text-white'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {pos}
                </button>
              ))}
            </div>

            {/* Recommendations table */}
            <div className="bg-[#161b22] border border-white/[0.06] rounded-lg overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/[0.06] text-xs text-gray-500">
                    <th className="text-left px-3 py-2 w-8">#</th>
                    <th className="text-left px-3 py-2">Add</th>
                    <th className="text-left px-3 py-2">Drop</th>
                    <th className="text-right px-3 py-2">+Wins</th>
                    <th className="text-right px-3 py-2">FAAB</th>
                    {CATS.map((cat) => (
                      <th key={cat} className="text-right px-2 py-2 w-12">{cat}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredRecs.length === 0 ? (
                    <tr>
                      <td colSpan={5 + CATS.length} className="px-3 py-8 text-center text-gray-500">
                        No recommendations{posFilter !== 'All' ? ` for ${posFilter}` : ''}
                      </td>
                    </tr>
                  ) : filteredRecs.map((rec) => (
                    <tr key={rec.rank} className="border-b border-white/[0.04] hover:bg-white/[0.02]">
                      <td className="px-3 py-2 text-gray-500 font-mono">{rec.rank}</td>
                      <td className="px-3 py-2">
                        <span className="text-white font-medium">{rec.add_player.name}</span>
                        <span className={`ml-1.5 text-xs ${posColors[rec.add_player.position] || 'text-gray-400'}`}>
                          {rec.add_player.position}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        {rec.drop_player ? (
                          <>
                            <span className="text-gray-400">{rec.drop_player.name}</span>
                            <span className={`ml-1.5 text-xs ${posColors[rec.drop_player.position] || 'text-gray-400'}`}>
                              {rec.drop_player.position}
                            </span>
                          </>
                        ) : (
                          <span className="text-gray-600">-</span>
                        )}
                      </td>
                      <td className={`px-3 py-2 text-right font-mono font-bold ${
                        rec.delta_expected_wins > 0 ? 'text-emerald-400' : rec.delta_expected_wins < 0 ? 'text-red-400' : 'text-gray-500'
                      }`}>
                        {fmtDelta(rec.delta_expected_wins)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-yellow-400">
                        {rec.suggested_faab_bid > 0 ? `$${rec.suggested_faab_bid}` : '-'}
                      </td>
                      {CATS.map((cat) => {
                        const impact = rec.category_impact[cat] ?? 0
                        return (
                          <td key={cat} className={`px-2 py-2 text-right font-mono text-xs ${impactColor(impact)}`}>
                            {Math.abs(impact) < 0.001 ? '-' : fmtCatImpact(impact)}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {!results && !loading && !error && (
          <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-8 text-center text-gray-500">
            <p className="mb-2">Select your league and team above, then click &quot;Get Recommendations&quot;.</p>
            <p className="text-xs">Uses ATC DC (RoS) projections to find free agents that improve your expected wins.</p>
          </div>
        )}
      </div>
    </main>
  )
}
