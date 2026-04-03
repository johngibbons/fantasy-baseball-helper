'use client'

import { useState, useEffect, useRef } from 'react'
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

interface CategoryStatus {
  yours: number
  theirs: number
  status: 'winning_big' | 'winning_close' | 'tied' | 'losing_close' | 'losing_big'
}

interface MatchupSummary {
  opponent: string
  categories: Record<string, CategoryStatus>
  days_remaining: number
  overall: string
  starts_today: number
  starts_remaining_after_today: number
  ratio_exposure: number
}

interface Recommendation {
  pitcher_name: string
  matchup: string
  pitcherlist_tier: string
  pitcherlist_score: number
  pitcherlist_raw: string
  our_recommendation: 'strong_start' | 'start' | 'risky_start' | 'sit' | 'safe_sit'
  rationale: string
}

interface UpcomingStart {
  date: string
  pitcher_name: string
  opponent: string
  pitcherlist_raw: string
}

interface OffDayPitcher {
  pitcher_name: string
}

interface Streamer {
  pitcher_name: string
  opponent: string
  date: string
  tier: string
  score: number
  raw: string
}

interface StartSitResults {
  matchup_summary: MatchupSummary
  recommendations: Recommendation[]
  upcoming_starts: UpcomingStart[]
  off_day_pitchers: OffDayPitcher[]
  streamers?: Streamer[]
}

const PITCHING_CATS = ['K', 'QS', 'ERA', 'WHIP']
const HITTING_CATS = ['R', 'TB', 'RBI', 'SB', 'OBP']
const CONTEXT_CATS = ['SVHD']

function formatCatValue(cat: string, val: number): string {
  if (cat === 'ERA' || cat === 'WHIP') return val.toFixed(2)
  if (cat === 'OBP') return val.toFixed(3)
  return String(Math.round(val))
}

function statusTextColor(status: CategoryStatus['status']): string {
  switch (status) {
    case 'winning_big': return 'text-emerald-900'
    case 'winning_close': return 'text-emerald-400'
    case 'losing_close': return 'text-red-400'
    case 'losing_big': return 'text-red-900'
    default: return 'text-gray-400'
  }
}

function statusBgColor(status: CategoryStatus['status']): string {
  switch (status) {
    case 'winning_big': return 'bg-emerald-500'
    case 'winning_close': return 'bg-emerald-500/20 border border-emerald-500/30'
    case 'losing_close': return 'bg-red-500/20 border border-red-500/30'
    case 'losing_big': return 'bg-red-500'
    default: return 'bg-white/5'
  }
}

function statusLabel(status: CategoryStatus['status']): string {
  switch (status) {
    case 'winning_big': return 'Win'
    case 'winning_close': return 'Edge'
    case 'tied': return 'Tied'
    case 'losing_close': return 'Behind'
    case 'losing_big': return 'Losing'
  }
}

function recBadgeStyle(rec: Recommendation['our_recommendation']): string {
  switch (rec) {
    case 'strong_start': return 'bg-emerald-500 text-white'
    case 'start': return 'bg-emerald-500/30 text-emerald-300 border border-emerald-500/40'
    case 'risky_start': return 'bg-yellow-500/30 text-yellow-300 border border-yellow-500/40'
    case 'sit': return 'bg-red-500/30 text-red-300 border border-red-500/40'
    case 'safe_sit': return 'bg-blue-500/30 text-blue-300 border border-blue-500/40'
  }
}

function recLabel(rec: Recommendation['our_recommendation']): string {
  switch (rec) {
    case 'strong_start': return 'Strong Start'
    case 'start': return 'Start'
    case 'risky_start': return 'Risky Start'
    case 'sit': return 'Sit'
    case 'safe_sit': return 'Safe Sit'
  }
}

const STORAGE_KEY = 'start_sit_settings'

function loadSettings(): { leagueId: string; teamId: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const s = JSON.parse(raw)
    if (s.leagueId && s.teamId) return s
    return null
  } catch { return null }
}

function saveSettings(leagueId: string, teamId: string) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ leagueId, teamId }))
}

export default function StartSitPage() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState<string>('')
  const [selectedTeam, setSelectedTeam] = useState<string>('')
  const [credentialsOk, setCredentialsOk] = useState<boolean | null>(null)
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<StartSitResults | null>(null)
  const [showHitting, setShowHitting] = useState(false)

  const today = new Date()
  const dateStr = today.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric' })

  // Load leagues and stored settings
  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        setLeagues(data)
        const saved = loadSettings()
        if (saved) {
          setSelectedLeague(saved.leagueId)
          setSelectedTeam(saved.teamId)
          setSettingsLoaded(true)
        } else {
          setEditing(true)
        }
      })
      .catch(() => { setEditing(true) })
  }, [])

  // Load teams when league changes
  useEffect(() => {
    if (!selectedLeague) return
    fetch(`/api/leagues/${selectedLeague}/teams`)
      .then((r) => r.ok ? r.json() : { teams: [] })
      .then((data) => setTeams(data.teams || []))
      .catch(() => {})
  }, [selectedLeague])

  // Check credentials when league is selected
  useEffect(() => {
    if (!selectedLeague) return
    fetch(`/api/leagues/${selectedLeague}/credentials`)
      .then((r) => {
        setCredentialsOk(r.ok)
      })
      .catch(() => setCredentialsOk(false))
  }, [selectedLeague])

  // Auto-fetch when settings are restored
  const autoFetched = useRef(false)
  useEffect(() => {
    if (settingsLoaded && !autoFetched.current && selectedLeague && selectedTeam) {
      autoFetched.current = true
      handleFetch()
    }
  }, [settingsLoaded, selectedLeague, selectedTeam])

  const leagueName = leagues.find((l) => l.id === selectedLeague)?.name
  const teamName = teams.find((t) => t.externalId === selectedTeam)?.name

  const handleFetch = async () => {
    if (!selectedLeague || !selectedTeam) {
      setError('Please select a league and team')
      return
    }

    setLoading(true)
    setError(null)
    setResults(null)

    try {
      const response = await fetch('/api/start-sit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ leagueId: selectedLeague, teamId: selectedTeam }),
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || `Error ${response.status}`)
      }

      const data = await response.json()
      setResults(data)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to fetch recommendations'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const handleSaveAndFetch = () => {
    if (selectedLeague && selectedTeam) {
      saveSettings(selectedLeague, selectedTeam)
      setEditing(false)
      setSettingsLoaded(true)
      handleFetch()
    }
  }

  const displayCats = showHitting ? HITTING_CATS : PITCHING_CATS

  return (
    <main className="min-h-screen bg-[#0d1117] text-gray-300">
      <div className="max-w-[90rem] mx-auto px-4 sm:px-6 py-6">

        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-bold text-white">
            Start/Sit
            <span className="text-gray-500 font-normal text-base ml-2">— {dateStr}</span>
          </h1>
        </div>

        {/* Config panel */}
        <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-4 mb-4">
          {settingsLoaded && !editing ? (
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-4 text-sm">
                <span className="text-gray-500">League:</span>
                <span className="text-white">{leagueName || selectedLeague}</span>
                <span className="text-gray-500">Team:</span>
                <span className="text-white">{teamName || `#${selectedTeam}`}</span>
                {credentialsOk === false && (
                  <span className="text-red-400 text-xs">
                    No credentials —{' '}
                    <Link href="/settings" className="underline hover:text-red-300">add in Settings</Link>
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setEditing(true)}
                  className="px-3 py-1 text-xs text-gray-400 hover:text-white border border-white/10 rounded hover:border-white/20"
                >
                  Edit
                </button>
                <button
                  onClick={handleFetch}
                  disabled={loading}
                  className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {loading ? 'Loading...' : 'Refresh'}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
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
              </div>
              {credentialsOk === false && selectedLeague && (
                <div className="mt-2 text-xs text-red-400">
                  No ESPN credentials stored for this league.{' '}
                  <Link href="/settings" className="underline hover:text-red-300">Add credentials in Settings</Link>
                </div>
              )}
              <div className="mt-3 flex items-center gap-3">
                <button
                  onClick={handleSaveAndFetch}
                  disabled={loading || !selectedLeague || !selectedTeam}
                  className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {loading ? 'Loading...' : 'Save & Get Recommendations'}
                </button>
                {settingsLoaded && (
                  <button
                    onClick={() => setEditing(false)}
                    className="px-3 py-1.5 text-sm text-gray-400 hover:text-white"
                  >
                    Cancel
                  </button>
                )}
              </div>
            </>
          )}
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-500/30 rounded-lg p-3 mb-4 text-sm text-red-400">
            {error}
          </div>
        )}

        {loading && (
          <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-8 text-center text-gray-500">
            Loading start/sit recommendations...
          </div>
        )}

        {/* Results */}
        {results && !loading && (
          <>
            {/* Matchup header */}
            <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-4 mb-4">
              <div className="flex items-start justify-between flex-wrap gap-3">
                <div>
                  <div className="text-xs text-gray-500 mb-1">vs. Opponent</div>
                  <div className="text-lg font-bold text-white">{results.matchup_summary.opponent}</div>
                  <div className="text-sm text-gray-400 mt-0.5">{results.matchup_summary.overall}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-gray-500 mb-1">Days Remaining</div>
                  <div className="text-2xl font-bold text-white">{results.matchup_summary.days_remaining}</div>
                </div>
              </div>

              {/* Category strip */}
              <div className="mt-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-xs text-gray-500">Category Standings</div>
                  <button
                    onClick={() => setShowHitting(!showHitting)}
                    className="text-xs text-gray-500 hover:text-gray-300 border border-white/10 rounded px-2 py-0.5 hover:border-white/20"
                  >
                    {showHitting ? 'Show Pitching' : 'Show Hitting'}
                  </button>
                </div>
                <div className="flex gap-2 flex-wrap">
                  {displayCats.map((cat) => {
                    const catData = results.matchup_summary.categories[cat]
                    if (!catData) return (
                      <div key={cat} className="flex-1 min-w-[4rem] max-w-[6rem] rounded-lg p-2 bg-white/5 text-center">
                        <div className="text-[10px] text-gray-500 mb-1">{cat}</div>
                        <div className="text-xs text-gray-600">—</div>
                      </div>
                    )
                    return (
                      <div key={cat} className={`flex-1 min-w-[4rem] max-w-[7rem] rounded-lg p-2 text-center ${statusBgColor(catData.status)}`}>
                        <div className={`text-[10px] font-medium mb-1 ${catData.status === 'winning_big' || catData.status === 'losing_big' ? 'text-white/70' : 'text-gray-500'}`}>{cat}</div>
                        <div className={`text-sm font-bold font-mono ${catData.status === 'winning_big' ? 'text-white' : catData.status === 'losing_big' ? 'text-white' : catData.status === 'winning_close' ? 'text-emerald-300' : catData.status === 'losing_close' ? 'text-red-300' : 'text-gray-300'}`}>
                          {formatCatValue(cat, catData.yours)}
                        </div>
                        <div className={`text-[10px] font-mono ${catData.status === 'winning_big' ? 'text-white/60' : catData.status === 'losing_big' ? 'text-white/60' : 'text-gray-500'}`}>
                          vs {formatCatValue(cat, catData.theirs)}
                        </div>
                        <div className={`text-[9px] mt-0.5 font-medium ${catData.status === 'winning_big' || catData.status === 'losing_big' ? 'text-white/80' : statusTextColor(catData.status)}`}>
                          {statusLabel(catData.status)}
                        </div>
                      </div>
                    )
                  })}
                  {/* SVHD as context */}
                  {CONTEXT_CATS.map((cat) => {
                    const catData = results.matchup_summary.categories[cat]
                    if (!catData) return null
                    return (
                      <div key={cat} className="flex-1 min-w-[4rem] max-w-[7rem] rounded-lg p-2 text-center bg-white/[0.03] border border-white/[0.04]">
                        <div className="text-[10px] text-gray-600 mb-1">{cat} <span className="text-[8px]">(ctx)</span></div>
                        <div className="text-sm font-bold font-mono text-gray-500">{formatCatValue(cat, catData.yours)}</div>
                        <div className="text-[10px] font-mono text-gray-600">vs {formatCatValue(cat, catData.theirs)}</div>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Exposure info */}
              <div className="mt-3 flex items-center gap-4 text-sm text-gray-400">
                <span>
                  <span className="text-white font-medium">{results.matchup_summary.starts_today}</span>
                  {' '}start{results.matchup_summary.starts_today !== 1 ? 's' : ''} today
                </span>
                <span className="text-gray-600">·</span>
                <span>
                  <span className="text-white font-medium">{results.matchup_summary.starts_remaining_after_today}</span>
                  {' '}more this matchup
                </span>
                {results.matchup_summary.ratio_exposure < 1 && (
                  <>
                    <span className="text-gray-600">·</span>
                    <span className="text-yellow-400 text-xs">
                      Ratio exposure: {(results.matchup_summary.ratio_exposure * 100).toFixed(0)}%
                    </span>
                  </>
                )}
              </div>
            </div>

            {/* Recommendations */}
            <div className="mb-4">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">Today&apos;s Starts</h2>
              {results.recommendations.length === 0 ? (
                <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-6 text-center text-gray-500">
                  No SP starts today
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {results.recommendations.map((rec, i) => (
                    <div key={i} className="bg-[#161b22] border border-white/[0.06] rounded-lg p-4">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-1">
                            <span className="text-white font-semibold">{rec.pitcher_name}</span>
                            <span className="text-gray-500 text-sm">{rec.matchup}</span>
                            {rec.pitcherlist_raw && (
                              <span className="text-xs text-gray-500 bg-white/5 rounded px-1.5 py-0.5">
                                PL: {rec.pitcherlist_raw}
                              </span>
                            )}
                          </div>
                          <p className="text-sm text-gray-400 leading-relaxed">{rec.rationale}</p>
                        </div>
                        <div className="shrink-0">
                          <span className={`inline-block px-3 py-1 rounded-full text-xs font-semibold ${recBadgeStyle(rec.our_recommendation)}`}>
                            {recLabel(rec.our_recommendation)}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Upcoming starts */}
            {results.upcoming_starts && results.upcoming_starts.length > 0 && (
              <div className="mb-4">
                <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">Upcoming Starts This Matchup</h2>
                <div className="bg-[#161b22] border border-white/[0.06] rounded-lg divide-y divide-white/[0.04]">
                  {results.upcoming_starts.map((s, i) => (
                    <div key={i} className="flex items-center gap-4 px-4 py-2.5 text-sm">
                      <span className="text-gray-500 w-24 shrink-0 font-mono text-xs">{s.date}</span>
                      <span className="text-white font-medium flex-1">{s.pitcher_name}</span>
                      <span className="text-gray-400">{s.opponent}</span>
                      {s.pitcherlist_raw && (
                        <span className="text-xs text-gray-500 bg-white/5 rounded px-1.5 py-0.5 shrink-0">
                          {s.pitcherlist_raw}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Streaming options */}
            {results.streamers && results.streamers.length > 0 && (() => {
              // Group streamers by date
              const grouped: { date: string; pitchers: typeof results.streamers }[] = []
              for (const s of results.streamers!) {
                const last = grouped[grouped.length - 1]
                if (last && last.date === s.date) {
                  last.pitchers!.push(s)
                } else {
                  grouped.push({ date: s.date, pitchers: [s] })
                }
              }
              return (
                <div className="mb-4">
                  <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                    Streaming Options
                    <span className="text-gray-600 font-normal normal-case ml-2">— PitcherList SP Streamer Ranks</span>
                  </h2>
                  <div className="flex flex-col gap-3">
                    {grouped.map((group) => (
                      <div key={group.date}>
                        <div className="text-xs text-gray-500 mb-1 px-1">{group.date}</div>
                        <div className="bg-[#161b22] border border-white/[0.06] rounded-lg divide-y divide-white/[0.04]">
                          {group.pitchers!.map((s, i) => (
                            <div key={i} className="flex items-center gap-4 px-4 py-2.5 text-sm">
                              <span className="text-white font-medium flex-1">{s.pitcher_name}</span>
                              <span className="text-gray-400">{s.opponent}</span>
                              <span className={`text-xs rounded px-1.5 py-0.5 shrink-0 ${
                                s.tier === 'auto_start' || s.tier === 'strong_start' ? 'bg-emerald-500/20 text-emerald-300' :
                                s.tier === 'probably_start' || s.tier === 'start' ? 'bg-emerald-500/10 text-emerald-400/70' :
                                'bg-yellow-500/10 text-yellow-400/70'
                              }`}>
                                {s.raw}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}

            {/* Off-day pitchers */}
            {results.off_day_pitchers && results.off_day_pitchers.length > 0 && (
              <div className="mb-4">
                <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">Off Today</h2>
                <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3">
                  <div className="flex flex-wrap gap-2">
                    {results.off_day_pitchers.map((p, i) => (
                      <span key={i} className="text-xs text-gray-600 bg-white/[0.03] rounded px-2 py-1">
                        {p.pitcher_name}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Refresh button */}
            <div className="flex justify-end mt-2">
              <button
                onClick={handleFetch}
                disabled={loading}
                className="px-4 py-1.5 bg-[#161b22] border border-white/10 text-gray-400 text-sm rounded hover:border-white/20 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Refresh
              </button>
            </div>
          </>
        )}

        {!results && !loading && !error && (
          <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-8 text-center text-gray-500">
            <p className="mb-2">Select your league and team above to get started.</p>
            <p className="text-xs">Shows today&apos;s starting pitcher recommendations based on your matchup context.</p>
          </div>
        )}
      </div>
    </main>
  )
}
