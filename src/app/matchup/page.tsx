// src/app/matchup/page.tsx
'use client'

import { useState, useEffect } from 'react'
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

interface CategoryResult {
  my_actual: number
  opponent_actual: number
  my_projected_final: number
  opponent_projected_final: number
  win_probability: number
  status: 'winning' | 'losing' | 'tossup'
}

interface PlayerProjection {
  mlb_id: number
  name: string
  position: string
  games_remaining: number
  projected_stats: Record<string, number>
  is_active: boolean
}

interface MatchupResult {
  projected_score: { wins: number; losses: number; ties: number }
  overall_win_probability: number
  categories: Record<string, CategoryResult>
  my_roster_projections: PlayerProjection[]
  matchup_period: {
    week: number
    start_date: string
    end_date: string
    days_remaining: number
  }
  opponent_name: string
}

const HITTING_CATS = ['R', 'TB', 'RBI', 'SB', 'OBP']
const PITCHING_CATS = ['K', 'QS', 'ERA', 'WHIP', 'SVHD']

function formatCatValue(cat: string, val: number): string {
  if (cat === 'OBP') return val.toFixed(3)
  if (cat === 'ERA' || cat === 'WHIP') return val.toFixed(2)
  return Math.round(val).toString()
}

function statusColor(status: string): string {
  if (status === 'winning') return '#34d399'
  if (status === 'losing') return '#ef4444'
  return '#fbbf24'
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

export default function MatchupPage() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState('')
  const [selectedTeam, setSelectedTeam] = useState('')
  const [mounted, setMounted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState<MatchupResult | null>(null)

  // Prevent hydration mismatch — don't render dynamic content until mounted
  useEffect(() => setMounted(true), [])

  // Load leagues
  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => r.json())
      .then((data) => {
        const leagueList = Array.isArray(data) ? data : (data.leagues || [])
        setLeagues(leagueList)
        const saved = localStorage.getItem('matchup_league')
        if (saved && leagueList.some((l: League) => l.id === saved)) {
          setSelectedLeague(saved)
        } else if (leagueList.length > 0) {
          setSelectedLeague(leagueList[0].id)
        }
      })
      .catch(() => setError('Failed to load leagues'))
  }, [])

  // Load teams when league changes
  useEffect(() => {
    if (!selectedLeague) return
    localStorage.setItem('matchup_league', selectedLeague)
    fetch(`/api/leagues/${selectedLeague}/teams`)
      .then((r) => r.json())
      .then((data) => {
        const teamList = data.teams || []
        setTeams(teamList)
        const saved = localStorage.getItem('matchup_team')
        if (saved && teamList.some((t: Team) => t.externalId === saved)) {
          setSelectedTeam(saved)
        } else if (teamList.length > 0) {
          setSelectedTeam(teamList[0].externalId)
        }
      })
      .catch(() => setError('Failed to load teams'))
  }, [selectedLeague])

  // Save team selection
  useEffect(() => {
    if (selectedTeam) localStorage.setItem('matchup_team', selectedTeam)
  }, [selectedTeam])

  const fetchProjections = async () => {
    if (!selectedLeague || !selectedTeam) return
    setLoading(true)
    setError('')
    setResults(null)

    try {
      const response = await fetch('/api/matchup/projections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: selectedLeague,
          teamId: selectedTeam,
        }),
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || `Error: ${response.status}`)
      }

      setResults(await response.json())
    } catch (err: any) {
      setError(err.message || 'Failed to load matchup projections')
    } finally {
      setLoading(false)
    }
  }

  const renderCategoryCard = (cat: string, data: CategoryResult) => {
    const color = statusColor(data.status)
    const probPct = Math.round(data.win_probability * 100)

    return (
      <div
        key={cat}
        className="bg-[#1e293b] rounded-lg px-3 py-2.5 flex items-center gap-3"
        style={{ borderLeft: `3px solid ${color}` }}
      >
        {/* Category name + win % */}
        <div className="w-12">
          <div className="text-white font-bold text-sm">{cat}</div>
          <div className="text-xs font-semibold" style={{ color }}>{probPct}%</div>
        </div>

        {/* Projected finals head-to-head */}
        <div className="flex-1 flex items-center justify-center gap-3">
          <div className="text-right min-w-[80px]">
            <span className="text-purple-400 font-bold text-base">
              {formatCatValue(cat, data.my_projected_final)}
            </span>
            <span className="text-gray-500 text-[10px] ml-1.5">
              now: {formatCatValue(cat, data.my_actual)}
            </span>
          </div>
          <span className="text-gray-600 text-xs">vs</span>
          <div className="text-left min-w-[80px]">
            <span className="text-gray-400 font-semibold text-base">
              {formatCatValue(cat, data.opponent_projected_final)}
            </span>
            <span className="text-gray-500 text-[10px] ml-1.5">
              now: {formatCatValue(cat, data.opponent_actual)}
            </span>
          </div>
        </div>

        {/* Win probability bar */}
        <div className="w-20">
          <div className="bg-[#0f172a] rounded h-1.5 overflow-hidden">
            <div
              className="h-full rounded"
              style={{ width: `${probPct}%`, backgroundColor: color }}
            />
          </div>
        </div>
      </div>
    )
  }

  const posColors: Record<string, string> = {
    C: 'bg-blue-500/20 text-blue-400', '1B': 'bg-amber-500/20 text-amber-400',
    '2B': 'bg-orange-500/20 text-orange-400', '3B': 'bg-purple-500/20 text-purple-400',
    SS: 'bg-red-500/20 text-red-400', OF: 'bg-emerald-500/20 text-emerald-400',
    LF: 'bg-emerald-500/20 text-emerald-400', CF: 'bg-emerald-500/20 text-emerald-400',
    RF: 'bg-emerald-500/20 text-emerald-400', DH: 'bg-gray-500/20 text-gray-400',
    SP: 'bg-sky-500/20 text-sky-400', RP: 'bg-pink-500/20 text-pink-400',
  }

  const hitters = results?.my_roster_projections.filter((p) =>
    !['SP', 'RP', 'P'].includes(p.position)
  ) || []
  const pitchers = results?.my_roster_projections.filter((p) =>
    ['SP', 'RP', 'P'].includes(p.position)
  ) || []

  if (!mounted) {
    return (
      <main className="min-h-screen bg-[#0d1117] text-gray-300">
        <div className="max-w-4xl mx-auto px-4 py-6">
          <h1 className="text-xl font-bold text-white mb-4">Weekly Matchup Projections</h1>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-[#0d1117] text-gray-300">
    <div className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-white mb-4">Weekly Matchup Projections</h1>

      {/* League/Team selector */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <select
          value={selectedLeague}
          onChange={(e) => setSelectedLeague(e.target.value)}
          className="bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
        >
          {leagues.map((l) => (
            <option key={l.id} value={l.id}>{l.name}</option>
          ))}
        </select>
        <select
          value={selectedTeam}
          onChange={(e) => setSelectedTeam(e.target.value)}
          className="bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
        >
          {teams.map((t) => (
            <option key={t.externalId} value={t.externalId}>
              {t.name}{t.ownerName ? ` — ${t.ownerName}` : ''}
            </option>
          ))}
        </select>
        <button
          onClick={fetchProjections}
          disabled={loading || !selectedLeague || !selectedTeam}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-4 py-1.5 rounded-md text-sm font-medium transition-colors"
        >
          {loading ? 'Loading...' : 'Get Projections'}
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mb-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {results && (
        <>
          {/* Matchup period info */}
          <div className="text-right text-sm text-gray-400 mb-2">
            Week {results.matchup_period.week} · {formatDate(results.matchup_period.start_date)} – {formatDate(results.matchup_period.end_date)}
            <span className="text-gray-500 ml-2">{results.matchup_period.days_remaining} days remaining</span>
          </div>

          {/* Projected score banner */}
          <div className="bg-[#1e293b] rounded-xl p-4 mb-5 border border-gray-700/50 text-center">
            <div className="flex items-center justify-center gap-4">
              <div>
                <div className="text-purple-400 text-xs font-semibold">MY TEAM</div>
              </div>
              <div className="text-3xl font-extrabold text-emerald-400">
                {results.projected_score.wins}
              </div>
              <div className="text-gray-600">-</div>
              <div className="text-3xl font-extrabold text-red-400">
                {results.projected_score.losses}
              </div>
              {results.projected_score.ties > 0 && (
                <>
                  <div className="text-gray-600">-</div>
                  <div className="text-3xl font-extrabold text-yellow-400">
                    {results.projected_score.ties}
                  </div>
                </>
              )}
              <div>
                <div className="text-red-400 text-xs font-semibold">OPPONENT</div>
                <div className="text-gray-300 text-xs">{results.opponent_name}</div>
              </div>
            </div>
            <div className="text-gray-500 text-xs mt-2">
              Projected Final · Win probability: {Math.round(results.overall_win_probability * 100)}%
            </div>
          </div>

          {/* Category cards — Hitting */}
          <div className="text-xs text-gray-400 font-semibold uppercase tracking-wider mb-1.5">Hitting</div>
          <div className="flex flex-col gap-1 mb-4">
            {HITTING_CATS.map((cat) =>
              results.categories[cat] && renderCategoryCard(cat, results.categories[cat])
            )}
          </div>

          {/* Category cards — Pitching */}
          <div className="text-xs text-gray-400 font-semibold uppercase tracking-wider mb-1.5">Pitching</div>
          <div className="flex flex-col gap-1 mb-6">
            {PITCHING_CATS.map((cat) =>
              results.categories[cat] && renderCategoryCard(cat, results.categories[cat])
            )}
          </div>

          {/* Roster projections — Hitters */}
          <div className="text-xs text-gray-400 font-semibold uppercase tracking-wider mb-2">
            My Roster — Remaining Week Projections
          </div>

          <div className="bg-[#1e293b] rounded-lg overflow-hidden text-xs mb-4">
            <div className="flex px-3 py-2 bg-[#0f172a] text-gray-500 font-semibold border-b border-gray-700/50">
              <div className="w-[140px]">Player</div>
              <div className="w-[40px] text-center">Pos</div>
              <div className="w-[35px] text-center">Gm</div>
              <div className="w-[40px] text-center">R</div>
              <div className="w-[40px] text-center">TB</div>
              <div className="w-[40px] text-center">RBI</div>
              <div className="w-[35px] text-center">SB</div>
              <div className="w-[45px] text-center">OBP</div>
            </div>
            {hitters.map((p, i) => (
              <div
                key={p.mlb_id || i}
                className={`flex px-3 py-1.5 ${!p.is_active ? 'opacity-40' : ''} ${i % 2 === 1 ? 'bg-[#0f172a]/40' : ''}`}
              >
                <div className="w-[140px] text-gray-200 font-medium truncate">
                  {p.mlb_id ? (
                    <Link href={`/players/${p.mlb_id}`} className="hover:text-blue-400">{p.name}</Link>
                  ) : p.name}
                </div>
                <div className="w-[40px] text-center">
                  <span className={`px-1 py-0.5 rounded text-[9px] ${posColors[p.position] || 'bg-gray-500/20 text-gray-400'}`}>
                    {p.position}
                  </span>
                </div>
                <div className="w-[35px] text-center text-gray-400">
                  {p.is_active ? p.games_remaining : <span className="line-through">0</span>}
                </div>
                {['r', 'tb', 'rbi', 'sb'].map((stat) => (
                  <div key={stat} className="w-[40px] text-center text-gray-200">
                    {p.is_active ? (p.projected_stats[stat]?.toFixed(1) || '—') : '—'}
                  </div>
                ))}
                <div className="w-[45px] text-center text-gray-200">
                  {p.is_active ? (p.projected_stats.obp?.toFixed(3) || '—') : '—'}
                </div>
              </div>
            ))}
          </div>

          {/* Roster projections — Pitchers */}
          <div className="bg-[#1e293b] rounded-lg overflow-hidden text-xs mb-4">
            <div className="flex px-3 py-2 bg-[#0f172a] text-gray-500 font-semibold border-b border-gray-700/50">
              <div className="w-[140px]">Pitcher</div>
              <div className="w-[40px] text-center">Pos</div>
              <div className="w-[35px] text-center">GS</div>
              <div className="w-[40px] text-center">K</div>
              <div className="w-[35px] text-center">QS</div>
              <div className="w-[40px] text-center">ERA</div>
              <div className="w-[45px] text-center">WHIP</div>
              <div className="w-[40px] text-center">SVH</div>
            </div>
            {pitchers.map((p, i) => (
              <div
                key={p.mlb_id || i}
                className={`flex px-3 py-1.5 ${!p.is_active ? 'opacity-40' : ''} ${i % 2 === 1 ? 'bg-[#0f172a]/40' : ''}`}
              >
                <div className="w-[140px] text-gray-200 font-medium truncate">
                  {p.mlb_id ? (
                    <Link href={`/players/${p.mlb_id}`} className="hover:text-blue-400">{p.name}</Link>
                  ) : p.name}
                </div>
                <div className="w-[40px] text-center">
                  <span className={`px-1 py-0.5 rounded text-[9px] ${posColors[p.position] || 'bg-gray-500/20 text-gray-400'}`}>
                    {p.position}
                  </span>
                </div>
                <div className="w-[35px] text-center text-gray-400">
                  {p.is_active ? p.games_remaining : <span className="line-through">0</span>}
                </div>
                <div className="w-[40px] text-center text-gray-200">
                  {p.is_active ? (p.projected_stats.k?.toFixed(1) || '—') : '—'}
                </div>
                <div className="w-[35px] text-center text-gray-200">
                  {p.is_active ? (p.projected_stats.qs?.toFixed(1) || '—') : '—'}
                </div>
                <div className="w-[40px] text-center text-gray-200">
                  {p.is_active ? (p.projected_stats.era?.toFixed(2) || '—') : '—'}
                </div>
                <div className="w-[45px] text-center text-gray-200">
                  {p.is_active ? (p.projected_stats.whip?.toFixed(2) || '—') : '—'}
                </div>
                <div className="w-[40px] text-center text-gray-200">
                  {p.is_active ? (p.projected_stats.svhd?.toFixed(1) || '—') : '—'}
                </div>
              </div>
            ))}
          </div>

          {/* Footer note */}
          <div className="bg-[#1e293b]/50 rounded-md px-3 py-2 text-gray-500 text-[11px]">
            <span className="text-gray-400 font-semibold">Note:</span> Projections assume optimal daily lineup.
            SPs without a probable start this week are excluded. RoS projections from ATC DC.
          </div>
        </>
      )}

      {!results && !loading && !error && (
        <div className="text-center text-gray-500 py-12 text-sm">
          Select your league and team, then click <strong>Get Projections</strong> to see your weekly matchup forecast.
        </div>
      )}
    </div>
    </main>
  )
}
