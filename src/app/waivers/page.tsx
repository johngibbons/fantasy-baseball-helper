'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
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
  category_stat_delta: Record<string, number>
}

interface RosterPlayer {
  name: string
  position: string
  slot: string
  lineup_slot_id: number
  mlb_id: number | null
}

interface WaiverResults {
  baseline_expected_wins: number
  baseline_category_probs: Record<string, number>
  recommendations: Recommendation[]
  remaining_faab: number
  my_roster_count: number
  free_agent_count: number
  other_teams_count: number
  open_roster_slots: number
  my_roster_display: RosterPlayer[]
}

const CATS = ['R', 'TB', 'RBI', 'SB', 'OBP', 'K', 'QS', 'ERA', 'WHIP', 'SVHD']
const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH', 'SP', 'RP']

const posColors: Record<string, string> = {
  C: 'text-blue-400', '1B': 'text-amber-400', '2B': 'text-orange-400', '3B': 'text-purple-400',
  SS: 'text-red-400', OF: 'text-emerald-400', LF: 'text-emerald-400', CF: 'text-teal-400',
  RF: 'text-emerald-400', DH: 'text-gray-400', SP: 'text-sky-400', RP: 'text-pink-400',
  P: 'text-teal-400',
}

const slotOrder = ['C', '1B', '2B', '3B', 'SS', 'OF', 'UTIL', 'SP', 'RP', 'P', 'BE', 'IL']
const slotColors: Record<string, string> = {
  C: 'text-blue-500', '1B': 'text-amber-500', '2B': 'text-orange-500', '3B': 'text-purple-500',
  SS: 'text-red-500', OF: 'text-emerald-500', UTIL: 'text-gray-400',
  SP: 'text-sky-500', RP: 'text-pink-500', P: 'text-teal-500',
  BE: 'text-gray-600', IL: 'text-red-600',
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

const RATE_CATS = new Set(['OBP', 'ERA', 'WHIP'])

function fmtStatDelta(cat: string, v: number): string {
  if (RATE_CATS.has(cat)) {
    const s = v.toFixed(3)
    return v > 0 ? `+${s}` : s
  }
  const rounded = Math.round(v)
  if (rounded === 0 && Math.abs(v) > 0.05) {
    // Show fractional for small non-zero (bench-weighted)
    const s = v.toFixed(1)
    return v > 0 ? `+${s}` : s
  }
  return rounded > 0 ? `+${rounded}` : `${rounded}`
}

const STORAGE_KEY = 'waiver_settings'

function loadSettings(): { leagueId: string; teamId: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const s = JSON.parse(raw)
    if (s.leagueId && s.teamId) return { leagueId: s.leagueId, teamId: s.teamId }
    return null
  } catch { return null }
}

function saveSettings(leagueId: string, teamId: string) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ leagueId, teamId }))
}

export default function WaiversPage() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState<string>('')
  const [selectedTeam, setSelectedTeam] = useState<string>('')
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [credentialsOk, setCredentialsOk] = useState<boolean | null>(null)
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
      const resp = await fetch('/api/waivers/refresh-projections?season=2026', { method: 'POST' })
      if (!resp.ok) throw new Error(`Error ${resp.status}`)
      const data = await resp.json()
      const count = data.results?.batting_and_pitching ?? data.results?.batting ?? 0
      setRefreshStatus(`Updated: ${count} players`)
    } catch (err: any) {
      setRefreshStatus(`Failed: ${err.message}`)
    } finally {
      setRefreshing(false)
    }
  }

  // Load leagues and stored settings
  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        setLeagues(data)
        // Restore saved leagueId/teamId after leagues load
        const saved = loadSettings()
        if (saved) {
          setSelectedLeague(saved.leagueId)
          setSelectedTeam(saved.teamId)
          setSettingsLoaded(true)
        }
      })
      .catch(() => {})
  }, [])

  // Load teams when league changes
  useEffect(() => {
    if (!selectedLeague) return
    fetch(`/api/leagues/${selectedLeague}/teams`)
      .then((r) => r.ok ? r.json() : { teams: [] })
      .then((data) => setTeams(data.teams || []))
      .catch(() => {})
  }, [selectedLeague])

  // Check credentials when league changes
  useEffect(() => {
    if (!selectedLeague) { setCredentialsOk(null); return }
    fetch(`/api/leagues/${selectedLeague}/credentials`)
      .then((r) => r.ok ? r.json() : { has_credentials: false })
      .then((data) => setCredentialsOk(data.has_credentials === true))
      .catch(() => setCredentialsOk(false))
  }, [selectedLeague])

  // Auto-fetch recommendations when settings are restored from localStorage
  const autoFetched = useRef(false)
  useEffect(() => {
    if (settingsLoaded && !autoFetched.current && selectedLeague && selectedTeam && credentialsOk) {
      autoFetched.current = true
      handleFetchRecommendations()
    }
  }, [settingsLoaded, selectedLeague, selectedTeam, credentialsOk])

  const hasAllSettings = !!(selectedLeague && selectedTeam)

  const handleFetchRecommendations = async () => {
    if (!selectedLeague || !selectedTeam) {
      setError('Please select a league and team')
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
        }),
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || `Error ${response.status}`)
      }

      const data = await response.json()
      console.log('Waiver diagnostics:', data.diagnostics, 'roster_names_debug:', data.roster_names_debug)
      setResults(data)
    } catch (err: any) {
      setError(err.message || 'Failed to fetch recommendations')
    } finally {
      setLoading(false)
    }
  }

  const rosterBySlot = useMemo(() => {
    if (!results?.my_roster_display) return []
    const groups: { slot: string; players: RosterPlayer[] }[] = []
    const slotGroups = new Map<string, RosterPlayer[]>()
    for (const p of results.my_roster_display) {
      const list = slotGroups.get(p.slot) || []
      list.push(p)
      slotGroups.set(p.slot, list)
    }
    for (const slot of slotOrder) {
      const players = slotGroups.get(slot)
      if (players) groups.push({ slot, players })
    }
    return groups
  }, [results])

  const filteredRecs = useMemo(() => {
    if (!results) return []
    if (posFilter === 'All') return results.recommendations
    return results.recommendations.filter((r) => {
      const pos = r.add_player.position
      if (posFilter === 'OF') return ['OF', 'LF', 'CF', 'RF'].includes(pos)
      return pos === posFilter
    })
  }, [results, posFilter])

  return (
    <main className="min-h-screen bg-[#0d1117] text-gray-300">
      <div className="max-w-[90rem] mx-auto px-4 sm:px-6 py-6">
        <h1 className="text-xl font-bold text-white mb-4">Waiver Wire Recommendations</h1>

        {/* Config panel */}
        <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-4 mb-4">
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">League</label>
                <select
                  value={selectedLeague}
                  onChange={(e) => {
                    const id = e.target.value
                    setSelectedLeague(id)
                    setSelectedTeam('')
                    setResults(null)
                    if (id) saveSettings(id, '')
                  }}
                  className="bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
                >
                  <option value="">Select league...</option>
                  {leagues.map((l) => (
                    <option key={l.id} value={l.id}>{l.name} ({l.season})</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">My Team</label>
                <select
                  value={selectedTeam}
                  onChange={(e) => {
                    const id = e.target.value
                    setSelectedTeam(id)
                    if (selectedLeague && id) saveSettings(selectedLeague, id)
                  }}
                  className="bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
                >
                  <option value="">Select team...</option>
                  {teams.map((t) => (
                    <option key={t.externalId} value={t.externalId}>
                      {t.name}{t.ownerName ? ` (${t.ownerName})` : ''}
                    </option>
                  ))}
                </select>
              </div>
              {selectedLeague && credentialsOk === true && (
                <span className="text-xs text-emerald-400 pb-1.5">ESPN: Connected</span>
              )}
              <div className="flex items-center gap-3 pb-0.5">
                <button
                  onClick={handleFetchRecommendations}
                  disabled={loading || !hasAllSettings || credentialsOk !== true}
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
                {loading && <span className="text-xs text-gray-500">Fetching rosters & computing expected wins...</span>}
                {refreshStatus && (
                  <span className={`text-xs ${refreshStatus.startsWith('Failed') ? 'text-red-400' : 'text-emerald-400'}`}>{refreshStatus}</span>
                )}
              </div>
            </div>
            {selectedLeague && credentialsOk === false && (
              <div className="text-sm text-yellow-400">
                ESPN credentials not configured.{' '}
                <Link href="/settings" className="underline hover:text-yellow-300">Set them up in Settings</Link>
                {' '}to use waiver recommendations.
              </div>
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

            {/* My Roster */}
            <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3 mb-4">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs text-gray-500">My Roster</div>
                {results.open_roster_slots > 0 && (
                  <div className="text-xs text-emerald-400 font-medium">
                    {results.open_roster_slots} open slot{results.open_roster_slots > 1 ? 's' : ''} (IL)
                  </div>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-x-4 gap-y-0.5 text-xs">
                {rosterBySlot.map(({ slot, players }) => (
                  players.map((p, i) => (
                    <div key={`${slot}-${i}`} className="flex items-center gap-1.5 py-0.5">
                      <span className={`w-6 text-right font-mono font-bold ${slotColors[slot] || 'text-gray-500'}`}>{slot}</span>
                      {p.mlb_id ? (
                        <Link href={`/player/${p.mlb_id}`} className={`hover:underline ${slot === 'IL' ? 'text-gray-600 line-through' : 'text-gray-300 hover:text-white'}`}>{p.name}</Link>
                      ) : (
                        <span className={slot === 'IL' ? 'text-gray-600 line-through' : 'text-gray-300'}>{p.name}</span>
                      )}
                      <span className={`text-[10px] ${posColors[p.position] || 'text-gray-500'}`}>{p.position}</span>
                    </div>
                  ))
                ))}
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
                        <Link href={`/player/${rec.add_player.id}`} className="text-white font-medium hover:underline hover:text-blue-300">{rec.add_player.name}</Link>
                        <span className={`ml-1.5 text-xs ${posColors[rec.add_player.position] || 'text-gray-400'}`}>
                          {rec.add_player.position}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        {rec.drop_player?.name ? (
                          <>
                            <Link href={`/player/${rec.drop_player.id}`} className="text-gray-400 hover:underline hover:text-white">{rec.drop_player.name}</Link>
                            <span className={`ml-1.5 text-xs ${posColors[rec.drop_player.position] || 'text-gray-400'}`}>
                              {rec.drop_player.position}
                            </span>
                          </>
                        ) : (
                          <span className="text-emerald-600 text-xs italic">No drop needed</span>
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
                        const stat = rec.category_stat_delta?.[cat] ?? 0
                        const hasStatChange = Math.abs(stat) > 0.05
                        const hasImpact = Math.abs(impact) >= 0.001
                        return (
                          <td key={cat} className={`px-2 py-2 text-right font-mono text-xs ${impactColor(impact)}`}>
                            {hasStatChange ? (
                              <div>
                                <div>{fmtStatDelta(cat, stat)}</div>
                                {hasImpact && (
                                  <div className="text-[10px] text-gray-500">{fmtCatImpact(impact)}</div>
                                )}
                              </div>
                            ) : (
                              hasImpact ? fmtCatImpact(impact) : '-'
                            )}
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
            <p className="mb-2">Select your league and team above to get started. Recommendations load automatically.</p>
            <p className="text-xs">Uses ATC RoS DC projections to find free agents that improve your expected wins.</p>
          </div>
        )}
      </div>
    </main>
  )
}
