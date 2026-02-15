'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import Link from 'next/link'
import {
  getDraftBoard,
  resolveKeepers,
  RankedPlayer,
  ResolvedKeeper,
  UnmatchedPlayer,
} from '@/lib/valuations-api'

// ── Constants ──
const NUM_TEAMS = 10
const MAX_ROUNDS = 25
const MAX_KEEPERS = 4

// ── Position badge colors (matches draft page) ──
const posColor: Record<string, string> = {
  C: 'bg-blue-500', '1B': 'bg-amber-500', '2B': 'bg-orange-500', '3B': 'bg-purple-500',
  SS: 'bg-red-500', OF: 'bg-emerald-500', LF: 'bg-emerald-500', CF: 'bg-emerald-500',
  RF: 'bg-emerald-500', DH: 'bg-gray-500', SP: 'bg-sky-500', RP: 'bg-pink-500', P: 'bg-teal-500',
}

// ── Types ──
interface RosterEntry {
  name: string
  draftRound: number | null // null = FA pickup
  keeperSeason: number      // 1, 2, or 3
}

interface KeeperWithSurplus {
  resolved: ResolvedKeeper
  roundCost: number
  expectedValue: number
  surplus: number
}

// ── Default roster (pre-populated from 2025 end-of-season data) ──
const DEFAULT_ROSTER: RosterEntry[] = [
  // 2025 keepers (season 2 for 2026)
  { name: 'Jackson Chourio', draftRound: 12, keeperSeason: 2 },
  { name: 'Lawrence Butler', draftRound: 25, keeperSeason: 2 },
  { name: 'Jordan Westburg', draftRound: 24, keeperSeason: 2 },
  // 2025 draft picks still on roster
  { name: 'Juan Soto', draftRound: 1, keeperSeason: 1 },
  { name: 'Jazz Chisholm Jr.', draftRound: 2, keeperSeason: 1 },
  { name: 'Cole Ragans', draftRound: 3, keeperSeason: 1 },
  { name: 'Rafael Devers', draftRound: 3, keeperSeason: 1 },
  { name: 'Corey Seager', draftRound: 3, keeperSeason: 1 },
  { name: 'Framber Valdez', draftRound: 4, keeperSeason: 1 },
  { name: 'Ozzie Albies', draftRound: 5, keeperSeason: 1 },
  { name: 'Adley Rutschman', draftRound: 5, keeperSeason: 1 },
  { name: 'Max Fried', draftRound: 6, keeperSeason: 1 },
  { name: 'Roki Sasaki', draftRound: 8, keeperSeason: 1 },
  { name: 'Joe Ryan', draftRound: 9, keeperSeason: 1 },
  { name: 'Seiya Suzuki', draftRound: 11, keeperSeason: 1 },
  { name: 'Ryan Pepiot', draftRound: 15, keeperSeason: 1 },
  // FA pickups (cost round 25, season 1)
  { name: 'Nick Kurtz', draftRound: null, keeperSeason: 1 },
  { name: 'Marcus Semien', draftRound: 6, keeperSeason: 1 },
  { name: 'Jonathan Aranda', draftRound: null, keeperSeason: 1 },
  { name: 'Ivan Herrera', draftRound: null, keeperSeason: 1 },
  { name: 'Joe Boyle', draftRound: null, keeperSeason: 1 },
  { name: 'Adrian Morejon', draftRound: null, keeperSeason: 1 },
  { name: 'Randy Rodriguez', draftRound: null, keeperSeason: 1 },
  { name: 'Ronny Henriquez', draftRound: null, keeperSeason: 1 },
  { name: 'Emmet Sheehan', draftRound: null, keeperSeason: 1 },
  { name: 'Michael Wacha', draftRound: null, keeperSeason: 1 },
  { name: 'Bubba Chandler', draftRound: null, keeperSeason: 1 },
  { name: 'Kris Bubic', draftRound: null, keeperSeason: 1 },
]

// ── Helper functions ──

function keeperCost(entry: { draftRound: number | null; keeperSeason: number }): number {
  const baseRound = entry.draftRound ?? MAX_ROUNDS
  if (entry.keeperSeason === 1) return baseRound
  const cost = baseRound - 5 * (entry.keeperSeason - 1)
  return Math.max(1, cost)
}

function expectedValueAtRound(round: number, allPlayers: RankedPlayer[]): number {
  const pickNumber = round * NUM_TEAMS
  const player = allPlayers.find((p) => p.overall_rank === pickNumber)
  if (player) return player.total_zscore
  // If exact rank not found, find closest
  const closest = allPlayers.reduce((best, p) => {
    if (Math.abs(p.overall_rank - pickNumber) < Math.abs(best.overall_rank - pickNumber)) return p
    return best
  }, allPlayers[0])
  return closest?.total_zscore ?? 0
}

function futureCost(draftRound: number | null, keeperSeason: number, yearsAhead: number): number {
  const baseRound = draftRound ?? MAX_ROUNDS
  const futureSeason = keeperSeason + yearsAhead
  if (futureSeason > 3) return -1 // cannot keep beyond 3 seasons
  if (futureSeason === 1) return baseRound
  return Math.max(1, baseRound - 5 * (futureSeason - 1))
}

function findOptimalKeepers(candidates: KeeperWithSurplus[]): KeeperWithSurplus[] {
  if (candidates.length <= MAX_KEEPERS) return [...candidates]
  let bestCombo: KeeperWithSurplus[] = []
  let bestSurplus = -Infinity

  function combine(start: number, current: KeeperWithSurplus[]) {
    if (current.length === MAX_KEEPERS) {
      const totalSurplus = current.reduce((s, k) => s + k.surplus, 0)
      if (totalSurplus > bestSurplus) {
        bestSurplus = totalSurplus
        bestCombo = [...current]
      }
      return
    }
    if (candidates.length - start < MAX_KEEPERS - current.length) return
    for (let i = start; i < candidates.length; i++) {
      combine(i + 1, [...current, candidates[i]])
    }
  }

  combine(0, [])
  return bestCombo
}

function surplusBg(v: number): string {
  if (v >= 3) return 'text-emerald-300'
  if (v >= 1) return 'text-emerald-400'
  if (v >= 0) return 'text-gray-400'
  if (v >= -1) return 'text-red-400'
  return 'text-red-300'
}

// ── Component ──

export default function KeepersPage() {
  // Roster state (editable, persisted in localStorage)
  const [roster, setRoster] = useState<RosterEntry[]>(DEFAULT_ROSTER)
  // Resolved data from API
  const [resolvedPlayers, setResolvedPlayers] = useState<ResolvedKeeper[] | null>(null)
  const [unmatchedPlayers, setUnmatchedPlayers] = useState<UnmatchedPlayer[]>([])
  // Draft board for expected value lookup
  const [allPlayers, setAllPlayers] = useState<RankedPlayer[]>([])
  // UI state
  const [selectedKeepers, setSelectedKeepers] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const [resolving, setResolving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingRoster, setEditingRoster] = useState(false)

  // Load draft board + restore from localStorage
  useEffect(() => {
    getDraftBoard()
      .then((data) => setAllPlayers(data.players))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))

    try {
      const savedRoster = localStorage.getItem('keeperRoster')
      if (savedRoster) setRoster(JSON.parse(savedRoster))
      const savedResolved = localStorage.getItem('keeperResolved')
      if (savedResolved) {
        const parsed = JSON.parse(savedResolved)
        setResolvedPlayers(parsed.resolved)
        setUnmatchedPlayers(parsed.unmatched || [])
      }
      const savedSelected = localStorage.getItem('keeperSelected')
      if (savedSelected) setSelectedKeepers(new Set(JSON.parse(savedSelected)))
    } catch { /* ignore corrupt localStorage */ }
  }, [])

  // Persist roster to localStorage
  useEffect(() => {
    localStorage.setItem('keeperRoster', JSON.stringify(roster))
  }, [roster])

  // Persist selected keepers
  useEffect(() => {
    localStorage.setItem('keeperSelected', JSON.stringify([...selectedKeepers]))
  }, [selectedKeepers])

  // Resolve players against DB
  const handleResolve = useCallback(async () => {
    setResolving(true)
    setError(null)
    try {
      const result = await resolveKeepers(
        roster.map((r) => ({
          name: r.name,
          draft_round: r.draftRound,
          keeper_season: r.keeperSeason,
        }))
      )
      setResolvedPlayers(result.resolved)
      setUnmatchedPlayers(result.unmatched)
      localStorage.setItem('keeperResolved', JSON.stringify(result))
      setEditingRoster(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to resolve players')
    } finally {
      setResolving(false)
    }
  }, [roster])

  // Compute surplus for all resolved players
  const keeperAnalysis = useMemo<KeeperWithSurplus[]>(() => {
    if (!resolvedPlayers || allPlayers.length === 0) return []

    return resolvedPlayers
      .map((r) => {
        const cost = keeperCost({ draftRound: r.draft_round, keeperSeason: r.keeper_season })
        const expected = expectedValueAtRound(cost, allPlayers)
        const value = r.total_zscore ?? 0
        return {
          resolved: r,
          roundCost: cost,
          expectedValue: expected,
          surplus: value - expected,
        }
      })
      .sort((a, b) => b.surplus - a.surplus)
  }, [resolvedPlayers, allPlayers])

  // Optimal keepers
  const optimalKeepers = useMemo(
    () => findOptimalKeepers(keeperAnalysis),
    [keeperAnalysis]
  )
  const optimalIds = useMemo(
    () => new Set(optimalKeepers.map((k) => k.resolved.mlb_id)),
    [optimalKeepers]
  )

  // Selected keepers data
  const selectedKeeperData = useMemo(
    () => keeperAnalysis.filter((k) => selectedKeepers.has(k.resolved.mlb_id)),
    [keeperAnalysis, selectedKeepers]
  )

  // Toggle keeper selection
  function toggleKeeper(mlbId: number) {
    setSelectedKeepers((prev) => {
      const next = new Set(prev)
      if (next.has(mlbId)) {
        next.delete(mlbId)
      } else if (next.size < MAX_KEEPERS) {
        next.add(mlbId)
      }
      return next
    })
  }

  // Roster editing
  function updateRosterEntry(index: number, updates: Partial<RosterEntry>) {
    setRoster((prev) => prev.map((r, i) => (i === index ? { ...r, ...updates } : r)))
  }

  function removeRosterEntry(index: number) {
    setRoster((prev) => prev.filter((_, i) => i !== index))
  }

  function addRosterEntry() {
    setRoster((prev) => [...prev, { name: '', draftRound: null, keeperSeason: 1 }])
  }

  function resetRoster() {
    setRoster(DEFAULT_ROSTER)
    setResolvedPlayers(null)
    setUnmatchedPlayers([])
    setSelectedKeepers(new Set())
    localStorage.removeItem('keeperResolved')
    localStorage.removeItem('keeperSelected')
  }

  // ── Render ──

  if (loading) {
    return (
      <main className="min-h-screen bg-gray-950">
        <div className="max-w-[90rem] mx-auto px-6 py-6">
          <div className="text-center py-20 text-gray-500">Loading draft board...</div>
        </div>
      </main>
    )
  }

  const showAnalysis = resolvedPlayers && !editingRoster

  return (
    <main className="min-h-screen bg-gray-950">
      <div className="max-w-[90rem] mx-auto px-6 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Keeper Analysis</h1>
            <p className="text-sm text-gray-500 mt-1">
              Find the optimal 4 keepers by surplus value over replacement
            </p>
          </div>
          <div className="flex gap-2">
            {showAnalysis && (
              <button
                onClick={() => setEditingRoster(true)}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 transition-colors"
              >
                Edit Roster
              </button>
            )}
            <button
              onClick={resetRoster}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 text-gray-400 hover:bg-gray-700 transition-colors"
            >
              Reset
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Roster Editor */}
        {(!resolvedPlayers || editingRoster) && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                End-of-Season Roster ({roster.length} players)
              </h2>
              <div className="flex gap-2">
                <button
                  onClick={addRosterEntry}
                  className="px-3 py-1 text-xs font-medium rounded-md bg-blue-600 text-white hover:bg-blue-500 transition-colors"
                >
                  + Add Player
                </button>
                <button
                  onClick={handleResolve}
                  disabled={resolving || roster.length === 0}
                  className="px-4 py-1 text-xs font-medium rounded-md bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {resolving ? 'Resolving...' : 'Resolve Players'}
                </button>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-800">
                    <th className="text-left text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2">Player</th>
                    <th className="text-left text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-40">Acquisition</th>
                    <th className="text-center text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-24">Season</th>
                    <th className="text-center text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-24">2026 Cost</th>
                    <th className="w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {roster.map((entry, i) => {
                    const cost = keeperCost(entry)
                    return (
                      <tr key={i} className={i % 2 === 0 ? '' : 'bg-white/[0.015]'}>
                        <td className="py-1.5 px-2">
                          <input
                            type="text"
                            value={entry.name}
                            onChange={(e) => updateRosterEntry(i, { name: e.target.value })}
                            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-blue-500"
                            placeholder="Player name"
                          />
                        </td>
                        <td className="py-1.5 px-2">
                          <div className="flex items-center gap-1">
                            <select
                              value={entry.draftRound === null ? 'fa' : 'drafted'}
                              onChange={(e) => {
                                if (e.target.value === 'fa') {
                                  updateRosterEntry(i, { draftRound: null })
                                } else {
                                  updateRosterEntry(i, { draftRound: 10 })
                                }
                              }}
                              className="bg-gray-800 border border-gray-700 rounded px-1 py-1 text-xs text-gray-300 focus:outline-none"
                            >
                              <option value="drafted">Rd</option>
                              <option value="fa">FA</option>
                            </select>
                            {entry.draftRound !== null && (
                              <input
                                type="number"
                                min={1}
                                max={MAX_ROUNDS}
                                value={entry.draftRound}
                                onChange={(e) => updateRosterEntry(i, { draftRound: parseInt(e.target.value) || 1 })}
                                className="w-14 bg-gray-800 border border-gray-700 rounded px-1 py-1 text-xs text-white text-center focus:outline-none focus:border-blue-500"
                              />
                            )}
                          </div>
                        </td>
                        <td className="py-1.5 px-2 text-center">
                          <select
                            value={entry.keeperSeason}
                            onChange={(e) => updateRosterEntry(i, { keeperSeason: parseInt(e.target.value) })}
                            className="bg-gray-800 border border-gray-700 rounded px-1 py-1 text-xs text-gray-300 focus:outline-none"
                          >
                            <option value={1}>1</option>
                            <option value={2}>2</option>
                            <option value={3}>3</option>
                          </select>
                        </td>
                        <td className="py-1.5 px-2 text-center text-xs text-gray-400 font-mono">
                          Rd {cost}
                        </td>
                        <td className="py-1.5 px-2 text-center">
                          <button
                            onClick={() => removeRosterEntry(i)}
                            className="text-gray-600 hover:text-red-400 transition-colors text-xs"
                            title="Remove"
                          >
                            &times;
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Unmatched players warning */}
        {showAnalysis && unmatchedPlayers.length > 0 && (
          <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <p className="text-xs font-medium text-amber-400 mb-1">
              {unmatchedPlayers.length} player{unmatchedPlayers.length > 1 ? 's' : ''} could not be matched:
            </p>
            <p className="text-xs text-amber-400/70">
              {unmatchedPlayers.map((p) => p.name).join(', ')}
              {' '}&mdash; no 2026 projections available (likely not worth keeping)
            </p>
          </div>
        )}

        {/* Analysis */}
        {showAnalysis && (
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
            {/* Main table (3/4) */}
            <div className="lg:col-span-3">
              <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-800">
                  <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                    Keeper Candidates &mdash; Sorted by Surplus Value
                  </h2>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-[#111827]/80 sticky top-0 z-10">
                      <tr>
                        <th className="text-left text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-3">Player</th>
                        <th className="text-center text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-12">Pos</th>
                        <th className="text-left text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2">Team</th>
                        <th className="text-center text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-14">Rank</th>
                        <th className="text-right text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-16">Value</th>
                        <th className="text-center text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-14">Cost</th>
                        <th className="text-right text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-16">Expctd</th>
                        <th className="text-right text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-18">Surplus</th>
                        <th className="text-center text-[11px] font-medium text-gray-500 uppercase tracking-wider py-2 px-2 w-12">Keep</th>
                      </tr>
                    </thead>
                    <tbody>
                      {keeperAnalysis.map((k, i) => {
                        const r = k.resolved
                        const isSelected = selectedKeepers.has(r.mlb_id)
                        const isOptimal = optimalIds.has(r.mlb_id)
                        const atMax = selectedKeepers.size >= MAX_KEEPERS && !isSelected
                        return (
                          <tr
                            key={r.mlb_id}
                            className={`border-b border-gray-800/50 transition-colors ${
                              isSelected
                                ? 'bg-emerald-500/10'
                                : isOptimal
                                  ? 'bg-blue-500/5'
                                  : i % 2 === 0
                                    ? ''
                                    : 'bg-white/[0.015]'
                            }`}
                          >
                            <td className="py-1.5 px-3">
                              <div className="flex items-center gap-2">
                                <Link
                                  href={`/player/${r.mlb_id}`}
                                  className="text-xs font-medium text-blue-400 hover:text-blue-300 transition-colors"
                                >
                                  {r.matched_name}
                                </Link>
                                {r.match_confidence < 1 && (
                                  <span className="text-[10px] text-amber-400" title={`Input: "${r.name}"`}>
                                    ~
                                  </span>
                                )}
                                {isOptimal && !isSelected && (
                                  <span className="text-[9px] px-1 py-0.5 rounded bg-blue-500/20 text-blue-400 font-medium">
                                    OPT
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="py-1.5 px-2 text-center">
                              <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold text-white ${posColor[r.primary_position] || 'bg-gray-600'}`}>
                                {r.primary_position}
                              </span>
                            </td>
                            <td className="py-1.5 px-2 text-xs text-gray-500">{r.team}</td>
                            <td className="py-1.5 px-2 text-center text-xs text-gray-400 font-mono">
                              {r.overall_rank ?? '—'}
                            </td>
                            <td className="py-1.5 px-2 text-right text-xs font-mono tabular-nums text-gray-300">
                              {(r.total_zscore ?? 0).toFixed(1)}
                            </td>
                            <td className="py-1.5 px-2 text-center text-xs font-mono text-gray-400">
                              Rd {k.roundCost}
                            </td>
                            <td className="py-1.5 px-2 text-right text-xs font-mono tabular-nums text-gray-500">
                              {k.expectedValue.toFixed(1)}
                            </td>
                            <td className={`py-1.5 px-2 text-right text-xs font-mono tabular-nums font-semibold ${surplusBg(k.surplus)}`}>
                              {k.surplus >= 0 ? '+' : ''}{k.surplus.toFixed(1)}
                            </td>
                            <td className="py-1.5 px-2 text-center">
                              <input
                                type="checkbox"
                                checked={isSelected}
                                disabled={atMax}
                                onChange={() => toggleKeeper(r.mlb_id)}
                                className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-800 text-emerald-500 focus:ring-0 focus:ring-offset-0 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                              />
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* Sidebar (1/4) */}
            <div className="space-y-4">
              {/* Optimal Keepers */}
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Optimal 4 Keepers
                </h3>
                {optimalKeepers.map((k) => (
                  <div key={k.resolved.mlb_id} className="flex items-center justify-between py-1.5 border-b border-gray-800/50 last:border-0">
                    <div className="flex items-center gap-2">
                      <span className={`inline-block w-1.5 h-1.5 rounded-full ${posColor[k.resolved.primary_position] || 'bg-gray-600'}`} />
                      <span className="text-xs text-gray-300">{k.resolved.matched_name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-gray-500">Rd {k.roundCost}</span>
                      <span className={`text-xs font-mono font-semibold ${surplusBg(k.surplus)}`}>
                        +{k.surplus.toFixed(1)}
                      </span>
                    </div>
                  </div>
                ))}
                <div className="mt-3 pt-2 border-t border-gray-700 flex justify-between">
                  <span className="text-[11px] text-gray-500">Total Surplus</span>
                  <span className="text-xs font-mono font-bold text-emerald-400">
                    +{optimalKeepers.reduce((s, k) => s + k.surplus, 0).toFixed(1)}
                  </span>
                </div>
                {selectedKeepers.size === 0 && (
                  <button
                    onClick={() => setSelectedKeepers(new Set(optimalKeepers.map((k) => k.resolved.mlb_id)))}
                    className="mt-3 w-full px-2 py-1.5 text-[11px] font-medium rounded-md bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 transition-colors"
                  >
                    Select Optimal
                  </button>
                )}
              </div>

              {/* Your Selected Keepers */}
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Your Keepers ({selectedKeepers.size}/{MAX_KEEPERS})
                </h3>
                {selectedKeeperData.length === 0 ? (
                  <p className="text-[11px] text-gray-600">Check players in the table to select keepers</p>
                ) : (
                  <>
                    {selectedKeeperData.map((k) => (
                      <div key={k.resolved.mlb_id} className="flex items-center justify-between py-1.5 border-b border-gray-800/50 last:border-0">
                        <div className="flex items-center gap-2">
                          <span className={`inline-block w-1.5 h-1.5 rounded-full ${posColor[k.resolved.primary_position] || 'bg-gray-600'}`} />
                          <span className="text-xs text-gray-300">{k.resolved.matched_name}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-gray-500">Rd {k.roundCost}</span>
                          <span className={`text-xs font-mono font-semibold ${surplusBg(k.surplus)}`}>
                            {k.surplus >= 0 ? '+' : ''}{k.surplus.toFixed(1)}
                          </span>
                        </div>
                      </div>
                    ))}
                    <div className="mt-3 pt-2 border-t border-gray-700 flex justify-between">
                      <span className="text-[11px] text-gray-500">Total Surplus</span>
                      <span className={`text-xs font-mono font-bold ${
                        selectedKeeperData.reduce((s, k) => s + k.surplus, 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
                      }`}>
                        {selectedKeeperData.reduce((s, k) => s + k.surplus, 0) >= 0 ? '+' : ''}
                        {selectedKeeperData.reduce((s, k) => s + k.surplus, 0).toFixed(1)}
                      </span>
                    </div>
                    {/* Comparison vs optimal */}
                    {selectedKeepers.size === MAX_KEEPERS && (
                      <div className="mt-2 pt-2 border-t border-gray-700/50">
                        <div className="flex justify-between">
                          <span className="text-[11px] text-gray-500">vs Optimal</span>
                          {(() => {
                            const diff = selectedKeeperData.reduce((s, k) => s + k.surplus, 0)
                              - optimalKeepers.reduce((s, k) => s + k.surplus, 0)
                            return (
                              <span className={`text-xs font-mono font-bold ${diff >= 0 ? 'text-emerald-400' : 'text-amber-400'}`}>
                                {diff >= 0 ? '+' : ''}{diff.toFixed(1)}
                              </span>
                            )
                          })()}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Multi-Year View */}
              {selectedKeeperData.length > 0 && (
                <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                  <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                    Multi-Year Cost
                  </h3>
                  {selectedKeeperData.map((k) => {
                    const r = k.resolved
                    const cost2027 = futureCost(r.draft_round, r.keeper_season, 1)
                    const cost2028 = futureCost(r.draft_round, r.keeper_season, 2)
                    return (
                      <div key={r.mlb_id} className="mb-3 last:mb-0">
                        <div className="text-xs font-medium text-gray-300 mb-1">{r.matched_name}</div>
                        <div className="flex items-center gap-1 text-[11px] text-gray-500">
                          <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-mono">
                            Rd {k.roundCost}
                          </span>
                          <span className="text-gray-600">&rarr;</span>
                          {cost2027 > 0 ? (
                            <>
                              <span className="px-1.5 py-0.5 rounded bg-gray-800 font-mono">
                                Rd {cost2027}
                              </span>
                              <span className="text-gray-600">&rarr;</span>
                            </>
                          ) : null}
                          {cost2028 > 0 ? (
                            <span className="px-1.5 py-0.5 rounded bg-gray-800 font-mono">
                              Rd {cost2028}
                            </span>
                          ) : cost2027 > 0 ? (
                            <span className="text-gray-600 italic">final</span>
                          ) : (
                            <span className="text-gray-600 italic">final yr</span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
