'use client'

import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { getDraftBoard, type RankedPlayer } from '@/lib/valuations-api'
import { fetchLeagueTeams } from '@/lib/league-teams'
import {
  analyzeCategoryStandings,
  detectStrategy,
  expectedWeeklyWins,
  type CategoryAnalysis,
} from '@/lib/draft-optimizer'
import {
  ROSTER_SLOTS, SLOT_ORDER, STARTER_SLOT_COUNT, BENCH_CONTRIBUTION,
  getPositions, optimizeRoster, type RosterResult,
} from '@/lib/roster-optimizer'
import {
  type CatDef, HITTING_CATS, PITCHING_CATS, ALL_CATS,
  posColor, getHeatColor, formatStat,
  computeTeamCategories, type TeamCategoriesResult,
} from '@/lib/draft-categories'
import { CategoryBar } from '@/components/CategoryBar'
import {
  computeDraftGrade, analyzeMyPicks, computeWaiverRecommendations,
  type PickAnalysis, type DraftGrade,
} from '@/lib/draft-results-engine'

// ── Types (matching draft page) ──
interface DraftTeam { id: number; name: string }

interface DraftState {
  picks: [number, number][]
  myTeamId: number | null
  draftOrder: number[]
  currentPickIndex: number
  keeperMlbIds?: number[]
  pickSchedule?: number[]
  pickLog?: { pickIndex: number; mlbId: number; teamId: number }[]
}

const DEFAULT_NUM_TEAMS = 10

export default function DraftResultsPage() {
  const [allPlayers, setAllPlayers] = useState<RankedPlayer[]>([])
  const [leagueTeams, setLeagueTeams] = useState<DraftTeam[]>([])
  const [draftState, setDraftState] = useState<DraftState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // ── Load data ──
  useEffect(() => {
    const loadAll = async () => {
      try {
        const [boardData, teams] = await Promise.all([
          getDraftBoard(),
          fetchLeagueTeams(),
        ])
        setAllPlayers(boardData.players)
        setLeagueTeams(teams)

        // Load draft state — server first, localStorage fallback
        let state: DraftState | null = null
        try {
          const res = await fetch('/api/v2/draft/state?season=2026')
          if (res.ok) {
            const data = await res.json()
            if (data.state) state = data.state as DraftState
          }
        } catch { /* fall through */ }

        if (!state) {
          try {
            const saved = localStorage.getItem('draftState')
            if (saved) state = JSON.parse(saved) as DraftState
          } catch { /* ignore */ }
        }

        setDraftState(state)
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setLoading(false)
      }
    }
    loadAll()
  }, [])

  // ── Derived data ──
  const draftPicks = useMemo(() => new Map(draftState?.picks ?? []), [draftState])
  const myTeamId = draftState?.myTeamId ?? null
  const draftOrder = draftState?.draftOrder ?? []
  const pickSchedule = draftState?.pickSchedule ?? []
  const pickLog = draftState?.pickLog ?? []
  const numTeams = draftOrder.length || DEFAULT_NUM_TEAMS

  const isDraftComplete = pickSchedule.length > 0 && (draftState?.currentPickIndex ?? 0) >= pickSchedule.length

  const teamNameMap = useMemo(() => {
    const m = new Map<number, string>()
    for (const t of leagueTeams) m.set(t.id, t.name)
    m.set(-1, 'Unknown')
    return m
  }, [leagueTeams])

  const getTeamAbbrev = (teamId: number) => {
    const name = teamNameMap.get(teamId) ?? `T${teamId}`
    if (name.startsWith('Team ')) return name.slice(5)
    return name.slice(0, 4).toUpperCase()
  }

  // ── Per-team rosters ──
  const teamRosters = useMemo(() => {
    const playerMap = new Map(allPlayers.map(p => [p.mlb_id, p]))
    const grouped = new Map<number, RankedPlayer[]>()
    for (const [mlbId, teamId] of draftPicks) {
      const p = playerMap.get(mlbId)
      if (!p) continue
      if (!grouped.has(teamId)) grouped.set(teamId, [])
      grouped.get(teamId)!.push(p)
    }
    const result = new Map<number, RosterResult>()
    for (const [teamId, players] of grouped) {
      result.set(teamId, optimizeRoster(players))
    }
    return result
  }, [allPlayers, draftPicks])

  const rosterState = useMemo(
    () => teamRosters.get(myTeamId!) ?? optimizeRoster([]),
    [teamRosters, myTeamId],
  )

  // ── Team categories ──
  const teamCategories = useMemo(
    () => computeTeamCategories(teamRosters, teamNameMap),
    [teamRosters, teamNameMap],
  )

  // ── My team category balance ──
  const categoryBalance = useMemo(() => {
    const totals: Record<string, number> = {}
    for (const cat of ALL_CATS) totals[cat.key] = 0
    for (const p of rosterState.starters) {
      for (const cat of ALL_CATS) {
        totals[cat.key] += ((p as unknown as Record<string, number>)[cat.key] ?? 0)
      }
    }
    for (const p of rosterState.bench) {
      for (const cat of ALL_CATS) {
        totals[cat.key] += ((p as unknown as Record<string, number>)[cat.key] ?? 0) * BENCH_CONTRIBUTION
      }
    }
    return totals
  }, [rosterState])

  // ── Category standings analysis ──
  const categoryStandings = useMemo((): CategoryAnalysis[] => {
    if (!myTeamId || teamCategories.rows.length < 2) return []
    const analysis = analyzeCategoryStandings(
      myTeamId,
      categoryBalance,
      teamCategories.rows,
      ALL_CATS,
      numTeams,
    )
    return detectStrategy(analysis, rosterState.starters.length + rosterState.bench.length, numTeams)
  }, [myTeamId, teamCategories, categoryBalance, numTeams, rosterState])

  const expectedWins = useMemo(
    () => categoryStandings.length > 0 ? expectedWeeklyWins(categoryStandings) : null,
    [categoryStandings],
  )

  // ── My team rank ──
  const myTeamRank = useMemo(() => {
    if (!myTeamId) return numTeams
    const idx = teamCategories.rows.findIndex(r => r.teamId === myTeamId)
    return idx >= 0 ? idx + 1 : numTeams
  }, [myTeamId, teamCategories, numTeams])

  // ── Draft grade ──
  const grade = useMemo(
    () => computeDraftGrade(myTeamRank, teamCategories.teamCount || numTeams),
    [myTeamRank, teamCategories.teamCount, numTeams],
  )

  // ── Pick analysis ──
  const pickAnalysis = useMemo(
    () => myTeamId ? analyzeMyPicks(pickLog, myTeamId, allPlayers, numTeams) : [],
    [pickLog, myTeamId, allPlayers, numTeams],
  )

  // ── Undrafted players ──
  const undraftedPlayers = useMemo(
    () => allPlayers.filter(p => !draftPicks.has(p.mlb_id)).sort((a, b) => a.overall_rank - b.overall_rank),
    [allPlayers, draftPicks],
  )

  // ── Waiver recommendations ──
  const waiverRecs = useMemo(
    () => computeWaiverRecommendations(undraftedPlayers, categoryStandings, rosterState),
    [undraftedPlayers, categoryStandings, rosterState],
  )

  // ── My team z-score total ──
  const myTeamZScore = useMemo(() => {
    const myRow = teamCategories.rows.find(r => r.teamId === myTeamId)
    return myRow?.total ?? 0
  }, [teamCategories, myTeamId])

  // ── Loading & error states ──
  if (loading) {
    return (
      <main className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-gray-700 border-t-blue-400 rounded-full animate-spin mx-auto mb-3" />
          <p className="text-gray-400 text-sm">Loading draft results...</p>
        </div>
      </main>
    )
  }

  if (error) {
    return (
      <main className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 text-sm mb-3">Error: {error}</p>
          <Link href="/draft" className="text-blue-400 hover:underline text-sm">Back to Draft</Link>
        </div>
      </main>
    )
  }

  if (!draftState || !myTeamId) {
    return (
      <main className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-400 text-sm mb-3">No draft data found or no team selected.</p>
          <Link href="/draft" className="text-blue-400 hover:underline text-sm">Back to Draft</Link>
        </div>
      </main>
    )
  }

  if (!isDraftComplete) {
    return (
      <main className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-yellow-400 text-sm mb-1">Draft is not yet complete.</p>
          <p className="text-gray-500 text-xs mb-4">
            {draftState.currentPickIndex} of {pickSchedule.length} picks made
          </p>
          <Link href="/draft" className="text-blue-400 hover:underline text-sm">Back to Draft</Link>
        </div>
      </main>
    )
  }

  const bestValues = [...pickAnalysis].sort((a, b) => b.valueDiff - a.valueDiff).slice(0, 3)
  const biggestReaches = [...pickAnalysis].sort((a, b) => a.valueDiff - b.valueDiff).slice(0, 3)

  return (
    <main className="min-h-screen bg-gray-950">
      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Header */}
        <div className="flex items-end justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Draft Results</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {teamNameMap.get(myTeamId) ?? `Team ${myTeamId}`} &middot; {pickSchedule.length} picks &middot; {leagueTeams.length} teams
            </p>
          </div>
          <Link
            href="/draft"
            className="px-4 py-2 text-xs font-semibold bg-gray-800 text-gray-300 border border-gray-700 rounded-lg hover:bg-gray-700 transition-colors"
          >
            &larr; Back to Draft
          </Link>
        </div>

        {/* Section 1: Draft Grade */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-4">
          <div className="flex items-center gap-6">
            <div className={`w-20 h-20 rounded-2xl flex items-center justify-center text-3xl font-black ${
              grade.letter.startsWith('A') ? 'bg-emerald-900/50 text-emerald-300 border-2 border-emerald-700' :
              grade.letter.startsWith('B') ? 'bg-blue-900/50 text-blue-300 border-2 border-blue-700' :
              grade.letter.startsWith('C') ? 'bg-yellow-900/50 text-yellow-300 border-2 border-yellow-700' :
              'bg-red-900/50 text-red-300 border-2 border-red-700'
            }`}>
              {grade.letter}
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-bold text-white">{grade.description}</h2>
              <div className="flex gap-6 mt-2 text-sm">
                <div>
                  <span className="text-gray-500">Rank: </span>
                  <span className="font-bold text-white">{myTeamRank}/{teamCategories.teamCount}</span>
                </div>
                <div>
                  <span className="text-gray-500">E(W): </span>
                  <span className={`font-bold ${(expectedWins ?? 0) >= 5.5 ? 'text-emerald-400' : (expectedWins ?? 0) >= 4.5 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {expectedWins?.toFixed(1) ?? '—'} wins/week
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Total Z: </span>
                  <span className={`font-bold ${myTeamZScore >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {myTeamZScore > 0 ? '+' : ''}{myTeamZScore.toFixed(1)}
                  </span>
                </div>
              </div>
              <p className="text-gray-400 text-xs mt-2">
                Your team projects to finish <span className="font-bold text-white">#{myTeamRank}</span> with{' '}
                <span className="font-bold text-white">{expectedWins?.toFixed(1) ?? '—'}</span> expected weekly wins.
              </p>
            </div>
          </div>
        </div>

        {/* Section 2: Predicted Standings */}
        {teamCategories.rows.length > 0 && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="font-bold text-white text-sm">Predicted Standings</h2>
              <div className="text-[11px] text-gray-500 mt-0.5">{teamCategories.rows.length} teams</div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-gray-800">
                    <th className="px-2 py-1.5 text-left text-gray-500 font-semibold w-8">#</th>
                    <th className="px-2 py-1.5 text-left text-gray-500 font-semibold">Team</th>
                    {ALL_CATS.map((cat) => (
                      <th key={cat.key} className="px-1 py-1.5 text-center text-gray-500 font-semibold">{cat.label}</th>
                    ))}
                    <th className="px-2 py-1.5 text-right text-gray-500 font-semibold" title="Expected weekly wins">E(W)</th>
                  </tr>
                </thead>
                <tbody>
                  {teamCategories.rows.map((row, idx) => {
                    const isMyRow = row.teamId === myTeamId
                    return (
                      <tr
                        key={row.teamId}
                        className={`border-b border-gray-800/50 ${isMyRow ? 'bg-blue-950/30' : ''}`}
                      >
                        <td className="px-2 py-1 text-gray-500 font-bold tabular-nums">{idx + 1}</td>
                        <td className={`px-2 py-1 font-semibold truncate max-w-[100px] ${isMyRow ? 'text-blue-400 border-l-2 border-l-blue-500' : 'text-gray-300'}`}>
                          {row.teamName.length > 12 ? getTeamAbbrev(row.teamId) : row.teamName}
                        </td>
                        {ALL_CATS.map((cat) => {
                          const val = row.statTotals[cat.projKey] ?? 0
                          const rank = teamCategories.catRanks.get(cat.key)?.get(row.teamId) ?? teamCategories.teamCount
                          const heatColor = getHeatColor(rank, teamCategories.teamCount)
                          return (
                            <td
                              key={cat.key}
                              className="px-1 py-1 text-center font-bold tabular-nums"
                              style={{ color: heatColor }}
                            >
                              {formatStat(cat, val)}
                            </td>
                          )
                        })}
                        <td className="px-2 py-1 text-right font-bold tabular-nums text-gray-200">
                          {row.expectedWins.toFixed(1)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Section 3: My Roster */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4">
          <div className="px-4 py-3 border-b border-gray-800">
            <h2 className="font-bold text-white text-sm">My Roster</h2>
            <div className="text-[11px] text-gray-500 mt-0.5">
              {rosterState.starters.length} starters &middot; {rosterState.bench.length} bench
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="px-2 py-1.5 text-left text-gray-500 font-semibold w-12">Slot</th>
                  <th className="px-2 py-1.5 text-left text-gray-500 font-semibold w-8">Pos</th>
                  <th className="px-2 py-1.5 text-left text-gray-500 font-semibold">Player</th>
                  <th className="px-2 py-1.5 text-right text-gray-500 font-semibold w-10">Rank</th>
                  <th className="px-2 py-1.5 text-right text-gray-500 font-semibold w-12">Z-Score</th>
                  {ALL_CATS.map(cat => (
                    <th key={cat.key} className="px-1 py-1.5 text-center text-gray-500 font-semibold w-8">{cat.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {/* Starters */}
                {rosterState.assignments
                  .filter(a => a.slot !== 'BE')
                  .sort((a, b) => SLOT_ORDER.indexOf(a.slot) - SLOT_ORDER.indexOf(b.slot))
                  .map((a, i) => {
                    const pos = getPositions(a.player)[0]
                    return (
                      <tr key={`s-${i}`} className="border-b border-gray-800/50">
                        <td className="px-2 py-1 text-gray-500 font-mono text-[10px]">{a.slot}</td>
                        <td className="px-2 py-1">
                          <span className={`px-1 py-0.5 rounded text-[8px] font-bold text-white ${posColor[pos] ?? 'bg-gray-600'}`}>
                            {pos}
                          </span>
                        </td>
                        <td className="px-2 py-1 text-white font-medium truncate max-w-[140px]">{a.player.full_name}</td>
                        <td className="px-2 py-1 text-right text-gray-400 tabular-nums">#{a.player.overall_rank}</td>
                        <td className={`px-2 py-1 text-right font-bold tabular-nums ${a.player.total_zscore >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {a.player.total_zscore > 0 ? '+' : ''}{a.player.total_zscore.toFixed(1)}
                        </td>
                        {ALL_CATS.map(cat => {
                          const val = (a.player as unknown as Record<string, number>)[cat.key] ?? 0
                          return (
                            <td key={cat.key} className={`px-1 py-1 text-center text-[10px] tabular-nums ${val > 0.5 ? 'text-emerald-400' : val < -0.5 ? 'text-red-400' : 'text-gray-600'}`}>
                              {val !== 0 ? (val > 0 ? '+' : '') + val.toFixed(1) : '—'}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                {/* Bench divider */}
                <tr>
                  <td colSpan={5 + ALL_CATS.length} className="px-2 py-1.5 text-[10px] font-bold text-gray-500 bg-gray-800/50 uppercase tracking-wider">
                    Bench
                  </td>
                </tr>
                {/* Bench */}
                {rosterState.assignments
                  .filter(a => a.slot === 'BE')
                  .map((a, i) => {
                    const pos = getPositions(a.player)[0]
                    return (
                      <tr key={`b-${i}`} className="border-b border-gray-800/50 opacity-70">
                        <td className="px-2 py-1 text-gray-600 font-mono text-[10px]">BE</td>
                        <td className="px-2 py-1">
                          <span className={`px-1 py-0.5 rounded text-[8px] font-bold text-white ${posColor[pos] ?? 'bg-gray-600'}`}>
                            {pos}
                          </span>
                        </td>
                        <td className="px-2 py-1 text-gray-300 font-medium truncate max-w-[140px]">{a.player.full_name}</td>
                        <td className="px-2 py-1 text-right text-gray-500 tabular-nums">#{a.player.overall_rank}</td>
                        <td className={`px-2 py-1 text-right font-bold tabular-nums ${a.player.total_zscore >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {a.player.total_zscore > 0 ? '+' : ''}{a.player.total_zscore.toFixed(1)}
                        </td>
                        {ALL_CATS.map(cat => {
                          const val = (a.player as unknown as Record<string, number>)[cat.key] ?? 0
                          return (
                            <td key={cat.key} className={`px-1 py-1 text-center text-[10px] tabular-nums ${val > 0.5 ? 'text-emerald-400' : val < -0.5 ? 'text-red-400' : 'text-gray-600'}`}>
                              {val !== 0 ? (val > 0 ? '+' : '') + val.toFixed(1) : '—'}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Section 4: Pick Analysis */}
        {pickAnalysis.length > 0 && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="font-bold text-white text-sm">Pick Analysis</h2>
              <div className="text-[11px] text-gray-500 mt-0.5">Value vs. reach on {pickAnalysis.length} picks</div>
            </div>

            {/* Highlight cards */}
            <div className="grid grid-cols-2 gap-3 px-4 py-3">
              <div className="bg-emerald-950/30 border border-emerald-800/50 rounded-lg p-3">
                <h3 className="text-[11px] font-bold text-emerald-400 mb-2">Best Value Picks</h3>
                {bestValues.map((pa, i) => (
                  <div key={i} className="flex items-center gap-2 py-0.5 text-[11px]">
                    <span className="text-emerald-400 font-bold tabular-nums w-8">+{pa.valueDiff}</span>
                    <span className={`px-1 py-0.5 rounded text-[8px] font-bold text-white ${posColor[getPositions(pa.player)[0]] ?? 'bg-gray-600'}`}>
                      {getPositions(pa.player)[0]}
                    </span>
                    <span className="text-gray-200 truncate">{pa.player.full_name}</span>
                    <span className="text-gray-500 ml-auto text-[10px]">Rd {pa.round}</span>
                  </div>
                ))}
              </div>
              <div className="bg-red-950/30 border border-red-800/50 rounded-lg p-3">
                <h3 className="text-[11px] font-bold text-red-400 mb-2">Biggest Reaches</h3>
                {biggestReaches.map((pa, i) => (
                  <div key={i} className="flex items-center gap-2 py-0.5 text-[11px]">
                    <span className="text-red-400 font-bold tabular-nums w-8">{pa.valueDiff}</span>
                    <span className={`px-1 py-0.5 rounded text-[8px] font-bold text-white ${posColor[getPositions(pa.player)[0]] ?? 'bg-gray-600'}`}>
                      {getPositions(pa.player)[0]}
                    </span>
                    <span className="text-gray-200 truncate">{pa.player.full_name}</span>
                    <span className="text-gray-500 ml-auto text-[10px]">Rd {pa.round}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Full pick table */}
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-gray-800">
                    <th className="px-2 py-1.5 text-left text-gray-500 font-semibold">Pick</th>
                    <th className="px-2 py-1.5 text-left text-gray-500 font-semibold">Player</th>
                    <th className="px-2 py-1.5 text-center text-gray-500 font-semibold">Pos</th>
                    <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">Rank</th>
                    <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">ADP</th>
                    <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">Value</th>
                    <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">Z-Score</th>
                  </tr>
                </thead>
                <tbody>
                  {pickAnalysis.map((pa, i) => {
                    const pos = getPositions(pa.player)[0]
                    return (
                      <tr key={i} className="border-b border-gray-800/50">
                        <td className="px-2 py-1 text-gray-400 font-mono tabular-nums">
                          {pa.round}.{String(pa.pickInRound).padStart(2, '0')}
                        </td>
                        <td className="px-2 py-1 text-white font-medium truncate max-w-[160px]">{pa.player.full_name}</td>
                        <td className="px-2 py-1 text-center">
                          <span className={`px-1 py-0.5 rounded text-[8px] font-bold text-white ${posColor[pos] ?? 'bg-gray-600'}`}>
                            {pos}
                          </span>
                        </td>
                        <td className="px-2 py-1 text-right text-gray-400 tabular-nums">#{pa.playerRank}</td>
                        <td className="px-2 py-1 text-right text-gray-500 tabular-nums">
                          {pa.adp ? `#${Math.round(pa.adp)}` : '—'}
                        </td>
                        <td className={`px-2 py-1 text-right font-bold tabular-nums ${pa.valueDiff > 0 ? 'text-emerald-400' : pa.valueDiff < -5 ? 'text-red-400' : 'text-yellow-400'}`}>
                          {pa.valueDiff > 0 ? '+' : ''}{pa.valueDiff}
                        </td>
                        <td className={`px-2 py-1 text-right font-bold tabular-nums ${pa.zScore >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {pa.zScore > 0 ? '+' : ''}{pa.zScore.toFixed(1)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Section 5: Category Strengths & Weaknesses */}
        {categoryStandings.length > 0 && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="font-bold text-white text-sm">Category Analysis</h2>
              <div className="text-[11px] text-gray-500 mt-0.5">
                Expected: <span className={`font-bold ${(expectedWins ?? 0) >= 5.5 ? 'text-emerald-400' : (expectedWins ?? 0) >= 4.5 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {expectedWins?.toFixed(1) ?? '—'}
                </span> wins/week
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 p-4">
              {/* Hitting */}
              <div>
                <h3 className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Hitting</h3>
                <div className="space-y-1">
                  {categoryStandings.filter(c => HITTING_CATS.some(h => h.key === c.catKey)).map(cat => {
                    const pct = Math.round(cat.winProb * 100)
                    const strategyBadge = {
                      target: { label: 'TARGET', cls: 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50' },
                      lock: { label: 'LOCK', cls: 'bg-blue-900/60 text-blue-300 border-blue-700/50' },
                      punt: { label: 'PUNT', cls: 'bg-red-900/60 text-red-300 border-red-700/50' },
                      neutral: null,
                    }[cat.strategy]
                    return (
                      <div key={cat.catKey} className="space-y-0.5">
                        <div className="flex items-center gap-1.5">
                          <CategoryBar label={cat.label} value={cat.myTotal} isWeakest={cat.strategy === 'punt'} />
                        </div>
                        <div className="flex items-center gap-2 pl-10 text-[9px]">
                          <span className="text-gray-500">Rank: <span className="font-bold text-gray-300">{cat.myRank}/{numTeams}</span></span>
                          <span className={`font-bold ${pct >= 60 ? 'text-emerald-400' : pct >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>{pct}% win</span>
                          {cat.gapAbove > 0 && <span className="text-gray-600">gap above: {cat.gapAbove.toFixed(1)}</span>}
                          {strategyBadge && (
                            <span className={`px-1 py-0.5 rounded text-[7px] font-bold border leading-none ${strategyBadge.cls}`}>
                              {strategyBadge.label}
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
              {/* Pitching */}
              <div>
                <h3 className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Pitching</h3>
                <div className="space-y-1">
                  {categoryStandings.filter(c => PITCHING_CATS.some(h => h.key === c.catKey)).map(cat => {
                    const pct = Math.round(cat.winProb * 100)
                    const strategyBadge = {
                      target: { label: 'TARGET', cls: 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50' },
                      lock: { label: 'LOCK', cls: 'bg-blue-900/60 text-blue-300 border-blue-700/50' },
                      punt: { label: 'PUNT', cls: 'bg-red-900/60 text-red-300 border-red-700/50' },
                      neutral: null,
                    }[cat.strategy]
                    return (
                      <div key={cat.catKey} className="space-y-0.5">
                        <div className="flex items-center gap-1.5">
                          <CategoryBar label={cat.label} value={cat.myTotal} isWeakest={cat.strategy === 'punt'} />
                        </div>
                        <div className="flex items-center gap-2 pl-10 text-[9px]">
                          <span className="text-gray-500">Rank: <span className="font-bold text-gray-300">{cat.myRank}/{numTeams}</span></span>
                          <span className={`font-bold ${pct >= 60 ? 'text-emerald-400' : pct >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>{pct}% win</span>
                          {cat.gapAbove > 0 && <span className="text-gray-600">gap above: {cat.gapAbove.toFixed(1)}</span>}
                          {strategyBadge && (
                            <span className={`px-1 py-0.5 rounded text-[7px] font-bold border leading-none ${strategyBadge.cls}`}>
                              {strategyBadge.label}
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Section 6: Waiver Wire Recommendations */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4">
          <div className="px-4 py-3 border-b border-gray-800">
            <h2 className="font-bold text-white text-sm">Waiver Wire Recommendations</h2>
            <div className="text-[11px] text-gray-500 mt-0.5">{undraftedPlayers.length} undrafted players</div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-4">
            {/* Best Available */}
            <div>
              <h3 className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Best Available Overall</h3>
              <div className="space-y-0.5">
                {waiverRecs.bestAvailable.map((rec, i) => {
                  const pos = getPositions(rec.player)[0]
                  return (
                    <div key={i} className="flex items-center gap-1.5 py-0.5 text-[11px]">
                      <span className="text-gray-500 w-4 text-right tabular-nums">{i + 1}.</span>
                      <span className={`px-1 py-0.5 rounded text-[8px] font-bold text-white ${posColor[pos] ?? 'bg-gray-600'}`}>
                        {pos}
                      </span>
                      <span className="text-gray-200 truncate flex-1">{rec.player.full_name}</span>
                      <span className="text-gray-500 text-[10px]">#{rec.player.overall_rank}</span>
                      <span className={`text-[10px] font-bold tabular-nums ${rec.player.total_zscore >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {rec.player.total_zscore > 0 ? '+' : ''}{rec.player.total_zscore.toFixed(1)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Category Targets */}
            <div>
              <h3 className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Target Category Upgrades</h3>
              {waiverRecs.categoryTargets.size > 0 ? (
                <div className="space-y-2">
                  {[...waiverRecs.categoryTargets.entries()].map(([catLabel, recs]) => (
                    <div key={catLabel}>
                      <span className="text-[10px] font-bold text-emerald-400">{catLabel}</span>
                      <div className="space-y-0.5 mt-0.5">
                        {recs.map((rec, i) => {
                          const pos = getPositions(rec.player)[0]
                          return (
                            <div key={i} className="flex items-center gap-1.5 py-0.5 text-[11px]">
                              <span className={`px-1 py-0.5 rounded text-[8px] font-bold text-white ${posColor[pos] ?? 'bg-gray-600'}`}>
                                {pos}
                              </span>
                              <span className="text-gray-200 truncate flex-1">{rec.player.full_name}</span>
                              <span className="text-gray-500 text-[10px] truncate">{rec.reason}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-600 text-[11px]">No target categories identified</p>
              )}
            </div>

            {/* Position Needs */}
            <div>
              <h3 className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Position Needs</h3>
              {waiverRecs.positionNeeds.length > 0 ? (
                <div className="space-y-0.5">
                  {waiverRecs.positionNeeds.map((rec, i) => {
                    const pos = getPositions(rec.player)[0]
                    return (
                      <div key={i} className="flex items-center gap-1.5 py-0.5 text-[11px]">
                        <span className="text-yellow-400 text-[10px] font-bold w-6">{rec.positionNeed}</span>
                        <span className={`px-1 py-0.5 rounded text-[8px] font-bold text-white ${posColor[pos] ?? 'bg-gray-600'}`}>
                          {pos}
                        </span>
                        <span className="text-gray-200 truncate flex-1">{rec.player.full_name}</span>
                        <span className="text-gray-500 text-[10px]">#{rec.player.overall_rank}</span>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="text-emerald-400 text-[11px]">All starter slots filled</p>
              )}
            </div>
          </div>
        </div>

        {/* Section 7: Round-by-Round Draft Recap */}
        {pickLog.length > 0 && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="font-bold text-white text-sm">Draft Recap</h2>
              <div className="text-[11px] text-gray-500 mt-0.5">{pickLog.length} picks &middot; {numTeams} teams &middot; {Math.ceil(pickLog.length / numTeams)} rounds</div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[9px]">
                <thead>
                  <tr className="border-b border-gray-800">
                    <th className="px-1.5 py-1 text-left text-gray-500 font-semibold w-10">Rd</th>
                    {Array.from({ length: numTeams }, (_, i) => (
                      <th key={i} className="px-1 py-1 text-center text-gray-500 font-semibold">
                        Pick {i + 1}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const totalRounds = Math.ceil(pickLog.length / numTeams)
                    const playerMap = new Map(allPlayers.map(p => [p.mlb_id, p]))
                    // Build pick grid from pickLog
                    const pickGrid: (typeof pickLog[0] | null)[][] = []
                    for (let r = 0; r < totalRounds; r++) {
                      const row: (typeof pickLog[0] | null)[] = []
                      for (let c = 0; c < numTeams; c++) {
                        const pickIdx = r * numTeams + c
                        row.push(pickLog.find(e => e.pickIndex === pickIdx) ?? null)
                      }
                      pickGrid.push(row)
                    }
                    return pickGrid.map((row, r) => (
                      <tr key={r} className="border-b border-gray-800/30">
                        <td className="px-1.5 py-1 text-gray-500 font-bold tabular-nums">{r + 1}</td>
                        {row.map((pick, c) => {
                          if (!pick) return <td key={c} className="px-1 py-1 text-gray-700 text-center">—</td>
                          const player = playerMap.get(pick.mlbId)
                          if (!player) return <td key={c} className="px-1 py-1 text-gray-700 text-center">?</td>
                          const pos = getPositions(player)[0]
                          const isMyPick = pick.teamId === myTeamId
                          return (
                            <td
                              key={c}
                              className={`px-1 py-1 text-center ${isMyPick ? 'bg-blue-950/40' : ''}`}
                            >
                              <div className="flex items-center justify-center gap-0.5">
                                <span className={`px-0.5 py-0 rounded text-[7px] font-bold text-white ${posColor[pos] ?? 'bg-gray-600'}`}>
                                  {pos}
                                </span>
                                <span className={`truncate max-w-[60px] ${isMyPick ? 'text-blue-300 font-bold' : 'text-gray-400'}`}>
                                  {player.full_name.split(' ').pop()}
                                </span>
                              </div>
                            </td>
                          )
                        })}
                      </tr>
                    ))
                  })()}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
