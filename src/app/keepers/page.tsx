'use client'

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import Link from 'next/link'
import {
  getDraftBoard,
  resolveKeepers,
  RankedPlayer,
  ResolvedKeeper,
  UnmatchedPlayer,
} from '@/lib/valuations-api'
import {
  fetchLeagueTeams,
  saveTeamsToStorage,
  teamDisplayName,
  type DraftTeam,
  type LeagueKeeperEntry,
} from '@/lib/league-teams'
import { getKeeperHistory, type KeeperHistory } from '@/lib/draft-history'

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

interface OtherTeamKeeperEntry {
  name: string
  roundCost: number
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

// ── Category definitions (matching draft page) ──
const HITTING_CATS = [
  { key: 'zscore_r', label: 'R' },
  { key: 'zscore_tb', label: 'TB' },
  { key: 'zscore_rbi', label: 'RBI' },
  { key: 'zscore_sb', label: 'SB' },
  { key: 'zscore_obp', label: 'OBP' },
] as const

const PITCHING_CATS = [
  { key: 'zscore_k', label: 'K' },
  { key: 'zscore_qs', label: 'QS' },
  { key: 'zscore_era', label: 'ERA' },
  { key: 'zscore_whip', label: 'WHIP' },
  { key: 'zscore_svhd', label: 'SVHD' },
] as const

const ALL_CATS = [...HITTING_CATS, ...PITCHING_CATS]

/**
 * Category diversity bonus for a keeper combination.
 *
 * Uses a continuous scale rather than a binary threshold so that strong
 * coverage in more categories is progressively rewarded.  Each category
 * contributes min(catTotal, 2.0) / 2.0 — capping at 2.0 avoids one
 * monster category dominating the bonus.  The sum is then scaled so
 * the bonus is meaningful relative to surplus values (typically 3-10).
 */
function categoryDiversityBonus(keepers: KeeperWithSurplus[]): number {
  const catTotals: Record<string, number> = {}
  for (const cat of ALL_CATS) catTotals[cat.key] = 0
  for (const k of keepers) {
    for (const cat of ALL_CATS) {
      catTotals[cat.key] += ((k.resolved as unknown as Record<string, number>)[cat.key] ?? 0)
    }
  }
  // Continuous coverage score: each category contributes 0-1.0
  let coverageScore = 0
  for (const cat of ALL_CATS) {
    const v = catTotals[cat.key]
    coverageScore += Math.min(Math.max(v, 0), 2.0) / 2.0
  }
  // Scale: 10 categories × 1.0 max each = 10.0 possible.
  // Normalize to a bonus in the range 0-3.0 (meaningful vs surplus values of 3-10)
  return (coverageScore / ALL_CATS.length) * 3.0
}

/**
 * Resolve round collisions within a keeper combination.
 *
 * If two+ keepers share the same round cost, bump duplicates to the next
 * earlier round (lower number = more expensive pick lost).  Returns the
 * adjusted round costs and the total surplus penalty from bumping.
 */
function resolveRoundCollisions(
  keepers: KeeperWithSurplus[],
  allPlayers: RankedPlayer[],
): number {
  // Collect round costs and sort ascending (earliest round first)
  const costs = keepers.map(k => k.roundCost).sort((a, b) => a - b)
  let penalty = 0
  for (let i = 1; i < costs.length; i++) {
    while (costs[i] <= costs[i - 1]) {
      // Bump to one round earlier (more expensive)
      const oldRound = costs[i]
      costs[i] = Math.max(1, costs[i - 1] - 1)
      if (costs[i] === oldRound) break // can't go earlier than round 1
      // Penalty = difference in expected value between old and new round
      const oldExpected = expectedValueAtRound(oldRound, allPlayers)
      const newExpected = expectedValueAtRound(costs[i], allPlayers)
      penalty += (newExpected - oldExpected) // positive = higher expected value = lower surplus
    }
  }
  return penalty
}

function findOptimalKeepers(
  candidates: KeeperWithSurplus[],
  allPlayers: RankedPlayer[],
): KeeperWithSurplus[] {
  if (candidates.length <= MAX_KEEPERS) return [...candidates]
  let bestCombo: KeeperWithSurplus[] = []
  let bestScore = -Infinity

  function combine(start: number, current: KeeperWithSurplus[]) {
    if (current.length === MAX_KEEPERS) {
      const totalSurplus = current.reduce((s, k) => s + k.surplus, 0)
      const diversity = categoryDiversityBonus(current)
      const collisionPenalty = resolveRoundCollisions(current, allPlayers)
      const score = totalSurplus + diversity - collisionPenalty
      if (score > bestScore) {
        bestScore = score
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

/** Compute per-category z-score totals for a set of keepers */
function keeperCategoryTotals(keepers: KeeperWithSurplus[]): { key: string; label: string; value: number }[] {
  return ALL_CATS.map(cat => {
    let total = 0
    for (const k of keepers) {
      total += ((k.resolved as unknown as Record<string, number>)[cat.key] ?? 0)
    }
    return { key: cat.key, label: cat.label, value: total }
  })
}

function surplusBg(v: number): string {
  if (v >= 3) return 'text-emerald-300'
  if (v >= 1) return 'text-emerald-400'
  if (v >= 0) return 'text-gray-400'
  if (v >= -1) return 'text-red-400'
  return 'text-red-300'
}

// ── Per-team localStorage helpers ──

function loadTeamRoster(teamId: number): RosterEntry[] | null {
  try {
    const raw = localStorage.getItem(`keeperRoster_${teamId}`)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return null
}

function saveTeamRoster(teamId: number, roster: RosterEntry[]) {
  localStorage.setItem(`keeperRoster_${teamId}`, JSON.stringify(roster))
}

function loadTeamResolved(teamId: number): { resolved: ResolvedKeeper[]; unmatched: UnmatchedPlayer[] } | null {
  try {
    const raw = localStorage.getItem(`keeperResolved_${teamId}`)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return null
}

function saveTeamResolved(teamId: number, data: { resolved: ResolvedKeeper[]; unmatched: UnmatchedPlayer[] }) {
  localStorage.setItem(`keeperResolved_${teamId}`, JSON.stringify(data))
}

function loadTeamSelected(teamId: number): Set<number> {
  try {
    const raw = localStorage.getItem(`keeperSelected_${teamId}`)
    if (raw) return new Set(JSON.parse(raw))
  } catch { /* ignore */ }
  return new Set()
}

function saveTeamSelected(teamId: number, selected: Set<number>) {
  localStorage.setItem(`keeperSelected_${teamId}`, JSON.stringify([...selected]))
}

// Other team keepers: simplified entries
function loadOtherTeamKeepers(teamId: number): OtherTeamKeeperEntry[] {
  try {
    const raw = localStorage.getItem(`keeperOther_${teamId}`)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return [{ name: '', roundCost: 10 }, { name: '', roundCost: 10 }, { name: '', roundCost: 10 }, { name: '', roundCost: 10 }]
}

function saveOtherTeamKeepers(teamId: number, entries: OtherTeamKeeperEntry[]) {
  localStorage.setItem(`keeperOther_${teamId}`, JSON.stringify(entries))
}

function loadOtherTeamResolved(teamId: number): ResolvedKeeper[] {
  try {
    const raw = localStorage.getItem(`keeperOtherResolved_${teamId}`)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return []
}

function saveOtherTeamResolved(teamId: number, resolved: ResolvedKeeper[]) {
  localStorage.setItem(`keeperOtherResolved_${teamId}`, JSON.stringify(resolved))
}

/** Hydrate localStorage from server state (runs on mount before team setup) */
function hydrateFromServerState(state: Record<string, unknown>) {
  try {
    if (state.myTeamId != null) {
      localStorage.setItem('keeperMyTeamId', String(state.myTeamId))
    }
    const roster = state.roster as Record<string, unknown> | undefined
    if (roster) {
      for (const [id, data] of Object.entries(roster)) {
        localStorage.setItem(`keeperRoster_${id}`, JSON.stringify(data))
      }
    }
    const resolved = state.resolved as Record<string, unknown> | undefined
    if (resolved) {
      for (const [id, data] of Object.entries(resolved)) {
        localStorage.setItem(`keeperResolved_${id}`, JSON.stringify(data))
      }
    }
    const selected = state.selected as Record<string, unknown> | undefined
    if (selected) {
      for (const [id, data] of Object.entries(selected)) {
        localStorage.setItem(`keeperSelected_${id}`, JSON.stringify(data))
      }
    }
    const other = state.other as Record<string, unknown> | undefined
    if (other) {
      for (const [id, data] of Object.entries(other)) {
        localStorage.setItem(`keeperOther_${id}`, JSON.stringify(data))
      }
    }
    const otherResolved = state.otherResolved as Record<string, unknown> | undefined
    if (otherResolved) {
      for (const [id, data] of Object.entries(otherResolved)) {
        localStorage.setItem(`keeperOtherResolved_${id}`, JSON.stringify(data))
      }
    }
  } catch { /* ignore */ }
}

/** Collect all keepers state from localStorage into a single document for server sync */
function collectKeepersState(myTeamId: number | null, teamIds: number[]): Record<string, unknown> {
  const rosterMap: Record<number, RosterEntry[]> = {}
  const resolvedMap: Record<number, unknown> = {}
  const selectedMap: Record<number, number[]> = {}
  const otherMap: Record<number, OtherTeamKeeperEntry[]> = {}
  const otherResolvedMap: Record<number, ResolvedKeeper[]> = {}

  for (const id of teamIds) {
    const r = loadTeamRoster(id)
    if (r) rosterMap[id] = r
    const res = loadTeamResolved(id)
    if (res) resolvedMap[id] = res
    const sel = loadTeamSelected(id)
    if (sel.size > 0) selectedMap[id] = [...sel]
    const oe = loadOtherTeamKeepers(id)
    if (oe.some(e => e.name.trim())) otherMap[id] = oe
    const or = loadOtherTeamResolved(id)
    if (or.length > 0) otherResolvedMap[id] = or
  }

  return {
    myTeamId,
    roster: rosterMap,
    resolved: resolvedMap,
    selected: selectedMap,
    other: otherMap,
    otherResolved: otherResolvedMap,
  }
}

/** Migrate old single-team localStorage keys to per-team keys */
function migrateOldStorage(myTeamId: number) {
  try {
    const oldRoster = localStorage.getItem('keeperRoster')
    if (oldRoster && !localStorage.getItem(`keeperRoster_${myTeamId}`)) {
      localStorage.setItem(`keeperRoster_${myTeamId}`, oldRoster)
      localStorage.removeItem('keeperRoster')
    }
    const oldResolved = localStorage.getItem('keeperResolved')
    if (oldResolved && !localStorage.getItem(`keeperResolved_${myTeamId}`)) {
      localStorage.setItem(`keeperResolved_${myTeamId}`, oldResolved)
      localStorage.removeItem('keeperResolved')
    }
    const oldSelected = localStorage.getItem('keeperSelected')
    if (oldSelected && !localStorage.getItem(`keeperSelected_${myTeamId}`)) {
      localStorage.setItem(`keeperSelected_${myTeamId}`, oldSelected)
      localStorage.removeItem('keeperSelected')
    }
  } catch { /* ignore */ }
}

// ── Component ──

export default function KeepersPage() {
  // Team state
  const [leagueTeams, setLeagueTeams] = useState<DraftTeam[]>([])
  const [myTeamId, setMyTeamId] = useState<number | null>(null)
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null)

  // My team roster state (editable, persisted in localStorage)
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

  // Other team keeper entry state
  const [otherEntries, setOtherEntries] = useState<OtherTeamKeeperEntry[]>([])
  const [otherResolved, setOtherResolved] = useState<ResolvedKeeper[]>([])
  const [otherResolving, setOtherResolving] = useState(false)

  // Export state
  const [exportMessage, setExportMessage] = useState<string | null>(null)

  // Server sync state
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const serverHydratedRef = useRef(false)

  // Computed: is viewing my team?
  const isMyTeam = selectedTeamId != null && selectedTeamId === myTeamId

  // Load teams + draft board on mount
  useEffect(() => {
    getDraftBoard()
      .then((data) => setAllPlayers(data.players))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))

    fetchLeagueTeams().then(async (teams) => {
      setLeagueTeams(teams)
      saveTeamsToStorage(teams)

      // Try server state first to hydrate localStorage
      try {
        const res = await fetch('/api/v2/keepers/state?season=2026')
        if (res.ok) {
          const data = await res.json()
          if (data.state) {
            hydrateFromServerState(data.state as Record<string, unknown>)
            serverHydratedRef.current = true
          }
        }
      } catch { /* fall through to localStorage */ }

      // Restore persisted myTeamId (may have been updated by server hydration)
      try {
        const savedMyTeam = localStorage.getItem('keeperMyTeamId')
        if (savedMyTeam) {
          const id = parseInt(savedMyTeam)
          setMyTeamId(id)
          setSelectedTeamId(id)
          migrateOldStorage(id)
        } else {
          // Default to first team
          setMyTeamId(teams[0]?.id ?? null)
          setSelectedTeamId(teams[0]?.id ?? null)
        }
      } catch {
        setMyTeamId(teams[0]?.id ?? null)
        setSelectedTeamId(teams[0]?.id ?? null)
      }
    })
  }, [])

  // Load data for the selected team whenever it changes
  useEffect(() => {
    if (selectedTeamId == null) return

    if (selectedTeamId === myTeamId) {
      // Load my team data
      const savedRoster = loadTeamRoster(selectedTeamId)
      if (savedRoster) setRoster(savedRoster)
      else setRoster(DEFAULT_ROSTER)

      const savedResolved = loadTeamResolved(selectedTeamId)
      if (savedResolved) {
        setResolvedPlayers(savedResolved.resolved)
        setUnmatchedPlayers(savedResolved.unmatched || [])
      } else {
        setResolvedPlayers(null)
        setUnmatchedPlayers([])
      }

      setSelectedKeepers(loadTeamSelected(selectedTeamId))
      setEditingRoster(false)
    } else {
      // Load other team data
      setOtherEntries(loadOtherTeamKeepers(selectedTeamId))
      setOtherResolved(loadOtherTeamResolved(selectedTeamId))
    }
  }, [selectedTeamId, myTeamId])

  // Persist myTeamId
  useEffect(() => {
    if (myTeamId != null) {
      localStorage.setItem('keeperMyTeamId', String(myTeamId))
    }
  }, [myTeamId])

  // Persist my team roster to localStorage
  useEffect(() => {
    if (myTeamId != null && selectedTeamId === myTeamId) {
      saveTeamRoster(myTeamId, roster)
    }
  }, [roster, myTeamId, selectedTeamId])

  // Persist selected keepers
  useEffect(() => {
    if (myTeamId != null && selectedTeamId === myTeamId) {
      saveTeamSelected(myTeamId, selectedKeepers)
    }
  }, [selectedKeepers, myTeamId, selectedTeamId])

  // Debounced server save (mirrors draft page pattern)
  useEffect(() => {
    if (leagueTeams.length === 0 || myTeamId == null) return

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      const state = collectKeepersState(myTeamId, leagueTeams.map(t => t.id))
      setSaveStatus('saving')
      fetch('/api/v2/keepers/state', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ season: 2026, state }),
      })
        .then((res) => {
          if (!res.ok) throw new Error('Save failed')
          setSaveStatus('saved')
          fadeTimerRef.current = setTimeout(() => setSaveStatus('idle'), 3000)
        })
        .catch(() => {
          setSaveStatus('error')
        })
    }, 2000)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roster, selectedKeepers, resolvedPlayers, otherEntries, otherResolved, myTeamId, leagueTeams])

  // Resolve my team's players against DB
  const handleResolve = useCallback(async () => {
    if (myTeamId == null) return
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
      saveTeamResolved(myTeamId, result)
      setEditingRoster(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to resolve players')
    } finally {
      setResolving(false)
    }
  }, [roster, myTeamId])

  // Resolve other team's keepers
  const handleResolveOther = useCallback(async () => {
    if (selectedTeamId == null || selectedTeamId === myTeamId) return
    const nonEmpty = otherEntries.filter(e => e.name.trim())
    if (nonEmpty.length === 0) return

    setOtherResolving(true)
    setError(null)
    try {
      const result = await resolveKeepers(
        nonEmpty.map((e) => ({
          name: e.name,
          draft_round: e.roundCost, // For other teams, roundCost IS the keeper cost directly
          keeper_season: 1,         // season 1 so keeperCost returns draftRound as-is
        }))
      )
      setOtherResolved(result.resolved)
      saveOtherTeamKeepers(selectedTeamId, otherEntries)
      saveOtherTeamResolved(selectedTeamId, result.resolved)
      if (result.unmatched.length > 0) {
        setError(`Could not match: ${result.unmatched.map(u => u.name).join(', ')}`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to resolve players')
    } finally {
      setOtherResolving(false)
    }
  }, [otherEntries, selectedTeamId, myTeamId])

  // Build depleted draft pool: remove other teams' confirmed keepers from the
  // full player list.  This reflects the real draft — kept players won't be
  // available, making remaining picks less valuable and keeper surplus higher.
  const draftPoolPlayers = useMemo<RankedPlayer[]>(() => {
    if (allPlayers.length === 0) return allPlayers

    // Collect all other teams' kept player MLB IDs
    const keptIds = new Set<number>()
    for (const team of leagueTeams) {
      if (team.id === myTeamId) continue // don't exclude our own candidates
      const resolved = loadOtherTeamResolved(team.id)
      for (const r of resolved) {
        if (r.mlb_id) keptIds.add(r.mlb_id)
      }
    }

    if (keptIds.size === 0) return allPlayers

    // Filter and re-rank
    const filtered = allPlayers
      .filter(p => !keptIds.has(p.mlb_id))
      .map((p, i) => ({ ...p, overall_rank: i + 1 }))
    return filtered
  }, [allPlayers, leagueTeams, myTeamId, otherResolved])

  // Compute surplus for all resolved players (my team only)
  // Uses the depleted draft pool so expected values reflect what's actually
  // available after other teams' keepers are removed.
  const keeperAnalysis = useMemo<KeeperWithSurplus[]>(() => {
    if (!resolvedPlayers || draftPoolPlayers.length === 0) return []

    return resolvedPlayers
      .map((r) => {
        const cost = keeperCost({ draftRound: r.draft_round, keeperSeason: r.keeper_season })
        const expected = expectedValueAtRound(cost, draftPoolPlayers)
        const value = r.total_zscore ?? 0
        return {
          resolved: r,
          roundCost: cost,
          expectedValue: expected,
          surplus: value - expected,
        }
      })
      .sort((a, b) => b.surplus - a.surplus)
  }, [resolvedPlayers, draftPoolPlayers])

  // Optimal keepers (accounts for round collisions and depleted pool)
  const optimalKeepers = useMemo(
    () => findOptimalKeepers(keeperAnalysis, draftPoolPlayers),
    [keeperAnalysis, draftPoolPlayers]
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
    if (myTeamId == null) return
    setRoster(DEFAULT_ROSTER)
    setResolvedPlayers(null)
    setUnmatchedPlayers([])
    setSelectedKeepers(new Set())
    localStorage.removeItem(`keeperResolved_${myTeamId}`)
    localStorage.removeItem(`keeperSelected_${myTeamId}`)
  }

  // Other team entry editing
  function updateOtherEntry(index: number, updates: Partial<OtherTeamKeeperEntry>) {
    setOtherEntries((prev) => prev.map((e, i) => (i === index ? { ...e, ...updates } : e)))
  }

  function addOtherEntry() {
    setOtherEntries((prev) => [...prev, { name: '', roundCost: 10 }])
  }

  function removeOtherEntry(index: number) {
    setOtherEntries((prev) => prev.filter((_, i) => i !== index))
  }

  function clearOtherTeam() {
    if (selectedTeamId == null) return
    setOtherEntries([{ name: '', roundCost: 10 }, { name: '', roundCost: 10 }, { name: '', roundCost: 10 }, { name: '', roundCost: 10 }])
    setOtherResolved([])
    localStorage.removeItem(`keeperOther_${selectedTeamId}`)
    localStorage.removeItem(`keeperOtherResolved_${selectedTeamId}`)
  }

  // Build league-wide keepers summary for sidebar
  const leagueKeepersSummary = useMemo(() => {
    return leagueTeams.map((team) => {
      if (team.id === myTeamId) {
        // My team: use selected keepers
        const selected = loadTeamSelected(team.id)
        const resolved = loadTeamResolved(team.id)
        if (selected.size === 0 || !resolved) return { team, keepers: [] }
        const keepers = resolved.resolved
          .filter(r => selected.has(r.mlb_id))
          .map(r => ({
            name: r.matched_name,
            roundCost: keeperCost({ draftRound: r.draft_round, keeperSeason: r.keeper_season }),
            position: r.primary_position,
          }))
        return { team, keepers }
      } else {
        // Other team: use resolved entries
        const resolved = loadOtherTeamResolved(team.id)
        const entries = loadOtherTeamKeepers(team.id)
        if (resolved.length > 0) {
          const keepers = resolved.map((r, i) => ({
            name: r.matched_name,
            roundCost: entries[i]?.roundCost ?? keeperCost({ draftRound: r.draft_round, keeperSeason: r.keeper_season }),
            position: r.primary_position,
          }))
          return { team, keepers }
        }
        return { team, keepers: [] }
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueTeams, myTeamId, selectedKeepers, otherResolved, selectedTeamId])

  // Export all keepers to draft
  function exportToDraft() {
    const entries: LeagueKeeperEntry[] = []

    for (const team of leagueTeams) {
      if (team.id === myTeamId) {
        // My team: selected keepers with computed costs
        const selected = loadTeamSelected(team.id)
        const resolved = loadTeamResolved(team.id)
        if (selected.size === 0 || !resolved) continue
        for (const r of resolved.resolved) {
          if (!selected.has(r.mlb_id)) continue
          entries.push({
            teamId: team.id,
            mlb_id: r.mlb_id,
            playerName: r.matched_name,
            roundCost: keeperCost({ draftRound: r.draft_round, keeperSeason: r.keeper_season }),
            primaryPosition: r.primary_position,
          })
        }
      } else {
        // Other teams: resolved entries with entered round costs
        const resolved = loadOtherTeamResolved(team.id)
        const keeperEntries = loadOtherTeamKeepers(team.id)
        for (let i = 0; i < resolved.length; i++) {
          const r = resolved[i]
          entries.push({
            teamId: team.id,
            mlb_id: r.mlb_id,
            playerName: r.matched_name,
            roundCost: keeperEntries[i]?.roundCost ?? keeperCost({ draftRound: r.draft_round, keeperSeason: r.keeper_season }),
            primaryPosition: r.primary_position,
          })
        }
      }
    }

    localStorage.setItem('leagueKeepers', JSON.stringify(entries))
    setExportMessage(`Exported ${entries.length} keepers across ${new Set(entries.map(e => e.teamId)).size} teams`)
    setTimeout(() => setExportMessage(null), 5000)
  }

  // Count teams with keepers entered
  function teamHasKeepers(teamId: number): boolean {
    if (teamId === myTeamId) {
      return loadTeamSelected(teamId).size > 0
    }
    return loadOtherTeamResolved(teamId).length > 0
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

  const showAnalysis = isMyTeam && resolvedPlayers && !editingRoster

  return (
    <main className="min-h-screen bg-gray-950">
      <div className="max-w-[90rem] mx-auto px-6 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Keeper Analysis</h1>
            <p className="text-sm text-gray-500 mt-1">
              Manage keepers for all teams, then export to draft
              {saveStatus !== 'idle' && (
                <>
                  <span className="text-gray-600 mx-1.5">/</span>
                  {saveStatus === 'saving' && <span className="text-gray-400">Saving…</span>}
                  {saveStatus === 'saved' && <span className="text-emerald-400">Saved</span>}
                  {saveStatus === 'error' && <span className="text-amber-400">Save failed</span>}
                </>
              )}
            </p>
          </div>
          <div className="flex gap-2 items-center">
            <div className="flex items-center gap-2 mr-4">
              <label className="text-gray-500 text-xs">My team:</label>
              <select
                value={myTeamId ?? ''}
                onChange={(e) => {
                  const id = e.target.value ? parseInt(e.target.value) : null
                  if (id != null && myTeamId != null) migrateOldStorage(id)
                  setMyTeamId(id)
                  if (id != null) setSelectedTeamId(id)
                }}
                className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select...</option>
                {leagueTeams.map((t) => (
                  <option key={t.id} value={t.id}>{teamDisplayName(t)}</option>
                ))}
              </select>
            </div>
            <button
              onClick={exportToDraft}
              className="px-4 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 text-white hover:bg-emerald-500 transition-colors"
            >
              Export to Draft
            </button>
          </div>
        </div>

        {/* Export success message */}
        {exportMessage && (
          <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm flex items-center justify-between">
            <span>{exportMessage}</span>
            <Link href="/draft" className="text-emerald-300 hover:text-emerald-200 underline text-xs font-medium">
              Go to Draft &rarr;
            </Link>
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Team selector bar */}
        <div className="flex gap-1.5 mb-5 overflow-x-auto pb-1">
          {leagueTeams.map((team) => {
            const isActive = team.id === selectedTeamId
            const hasKeepers = teamHasKeepers(team.id)
            const isMine = team.id === myTeamId
            return (
              <button
                key={team.id}
                onClick={() => setSelectedTeamId(team.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 ${
                  isActive
                    ? isMine ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20' : 'bg-gray-600 text-white shadow-md'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                }`}
              >
                {teamDisplayName(team)}
                {isMine && <span className="text-[8px] opacity-70">(me)</span>}
                {hasKeepers && <span className={`w-1.5 h-1.5 rounded-full ${isActive ? 'bg-white/60' : 'bg-emerald-500'}`} />}
              </button>
            )
          })}
        </div>

        {/* Content area: My team vs Other team */}
        {selectedTeamId != null && isMyTeam ? (
          // ── My Team: Full keeper analysis UI ──
          <>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-300">
                {(() => { const t = leagueTeams.find(t => t.id === myTeamId); return t ? teamDisplayName(t) : '' })()} — Full Keeper Analysis
              </h2>
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
                                  {r.overall_rank ?? '\u2014'}
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
                    {optimalKeepers.length > 0 && (
                      <KeeperCategoryBalance keepers={optimalKeepers} title="Category Coverage" />
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
                    {selectedKeeperData.length > 0 && (
                      <KeeperCategoryBalance keepers={selectedKeeperData} title="Category Coverage" />
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

                  {/* League Keepers Summary */}
                  <LeagueKeepersSummaryPanel summary={leagueKeepersSummary} myTeamId={myTeamId} />

                  {/* Keeper History */}
                  <KeeperHistoryPanel />
                </div>
              </div>
            )}
          </>
        ) : selectedTeamId != null ? (
          // ── Other Team: Simplified keeper entry ──
          <>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-300">
                {(() => { const t = leagueTeams.find(t => t.id === selectedTeamId); return t ? teamDisplayName(t) : '' })()} — Keeper Entry
              </h2>
              <button
                onClick={clearOtherTeam}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 text-gray-400 hover:bg-gray-700 transition-colors"
              >
                Clear
              </button>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
              <div className="lg:col-span-3">
                <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                      Keepers ({otherEntries.filter(e => e.name.trim()).length} entered)
                    </h3>
                    <div className="flex gap-2">
                      <button
                        onClick={addOtherEntry}
                        className="px-3 py-1 text-xs font-medium rounded-md bg-blue-600 text-white hover:bg-blue-500 transition-colors"
                      >
                        + Add Row
                      </button>
                      <button
                        onClick={handleResolveOther}
                        disabled={otherResolving || otherEntries.every(e => !e.name.trim())}
                        className="px-4 py-1 text-xs font-medium rounded-md bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {otherResolving ? 'Resolving...' : 'Resolve Players'}
                      </button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {otherEntries.map((entry, i) => (
                      <div key={i} className="flex items-center gap-3">
                        <input
                          type="text"
                          value={entry.name}
                          onChange={(e) => updateOtherEntry(i, { name: e.target.value })}
                          className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                          placeholder="Player name"
                        />
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] text-gray-500">Rd</span>
                          <input
                            type="number"
                            min={1}
                            max={MAX_ROUNDS}
                            value={entry.roundCost}
                            onChange={(e) => updateOtherEntry(i, { roundCost: parseInt(e.target.value) || 1 })}
                            className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-white text-center focus:outline-none focus:border-blue-500"
                          />
                        </div>
                        <button
                          onClick={() => removeOtherEntry(i)}
                          className="text-gray-600 hover:text-red-400 transition-colors text-xs px-1"
                          title="Remove"
                        >
                          &times;
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Resolved entries display */}
                  {otherResolved.length > 0 && (
                    <div className="mt-5 pt-4 border-t border-gray-800">
                      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Resolved Keepers</h4>
                      <div className="space-y-1.5">
                        {otherResolved.map((r, i) => (
                          <div key={r.mlb_id} className="flex items-center gap-3 py-1.5 px-2 rounded-lg bg-gray-800/50">
                            <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold text-white ${posColor[r.primary_position] || 'bg-gray-600'}`}>
                              {r.primary_position}
                            </span>
                            <Link
                              href={`/player/${r.mlb_id}`}
                              className="text-xs font-medium text-blue-400 hover:text-blue-300 transition-colors flex-1"
                            >
                              {r.matched_name}
                            </Link>
                            <span className="text-xs text-gray-500">{r.team}</span>
                            <span className="text-xs text-gray-400 font-mono">
                              Rd {otherEntries[i]?.roundCost ?? '?'}
                            </span>
                            {r.match_confidence < 1 && (
                              <span className="text-[10px] text-amber-400" title={`Input: "${r.name}"`}>~</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Sidebar */}
              <div className="space-y-4">
                <LeagueKeepersSummaryPanel summary={leagueKeepersSummary} myTeamId={myTeamId} />
                <KeeperHistoryPanel />
              </div>
            </div>
          </>
        ) : (
          <div className="text-center py-20 text-gray-500">Select a team above to manage keepers</div>
        )}
      </div>
    </main>
  )
}

// ── League Keepers Summary Panel ──
function LeagueKeepersSummaryPanel({
  summary,
  myTeamId,
}: {
  summary: { team: DraftTeam; keepers: { name: string; roundCost: number; position: string }[] }[]
  myTeamId: number | null
}) {
  const totalKeepers = summary.reduce((s, t) => s + t.keepers.length, 0)

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
        League Keepers ({totalKeepers})
      </h3>
      <div className="space-y-2.5">
        {summary.map(({ team, keepers }) => {
          const isMine = team.id === myTeamId
          return (
            <div key={team.id}>
              <div className={`text-[11px] font-semibold mb-0.5 ${isMine ? 'text-blue-400' : 'text-gray-400'}`}>
                {teamDisplayName(team)}
              </div>
              {keepers.length === 0 ? (
                <div className="text-[10px] text-gray-600 italic pl-2">(none)</div>
              ) : (
                keepers.map((k, i) => (
                  <div key={i} className="flex items-center justify-between pl-2 py-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className={`inline-block w-1.5 h-1.5 rounded-full ${posColor[k.position] || 'bg-gray-600'}`} />
                      <span className="text-[11px] text-gray-300">{k.name}</span>
                    </div>
                    <span className="text-[10px] text-gray-500 font-mono">Rd {k.roundCost}</span>
                  </div>
                ))
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Category balance visualization for keeper combinations ──
function KeeperCategoryBalance({ keepers, title }: { keepers: KeeperWithSurplus[]; title: string }) {
  const cats = keeperCategoryTotals(keepers)
  const covered = cats.filter(c => c.value > 0.5).length
  const gaps = cats.filter(c => c.value <= 0.5)

  return (
    <div className="mt-3 pt-3 border-t border-gray-700/50">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">{title}</span>
        <span className={`text-[10px] font-bold ${covered >= 8 ? 'text-emerald-400' : covered >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>
          {covered}/10
        </span>
      </div>
      <div className="space-y-0.5">
        {cats.map(cat => {
          const maxVal = 8
          const clamped = Math.max(-maxVal, Math.min(maxVal, cat.value))
          const pct = Math.abs(clamped) / maxVal * 100
          const isGap = cat.value <= 0.5
          return (
            <div key={cat.key} className="flex items-center gap-1.5">
              <span className={`w-8 text-[9px] font-bold text-right shrink-0 ${isGap ? 'text-red-400' : 'text-gray-500'}`}>
                {cat.label}
              </span>
              <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${cat.value > 0.5 ? 'bg-emerald-500/50' : cat.value > 0 ? 'bg-yellow-500/40' : 'bg-red-500/40'}`}
                  style={{ width: `${Math.max(pct, 3)}%` }}
                />
              </div>
              <span className={`w-7 text-[9px] font-bold tabular-nums text-right shrink-0 ${cat.value > 0.5 ? 'text-emerald-400' : cat.value > 0 ? 'text-yellow-400' : 'text-red-400'}`}>
                {cat.value > 0 ? '+' : ''}{cat.value.toFixed(1)}
              </span>
            </div>
          )
        })}
      </div>
      {gaps.length > 0 && (
        <div className="mt-1.5 text-[9px] text-gray-500">
          Gaps: <span className="text-red-400 font-semibold">{gaps.map(g => g.label).join(', ')}</span>
          <span className="text-gray-600"> — target in draft</span>
        </div>
      )}
    </div>
  )
}

// ── Keeper History Panel ──
function KeeperHistoryPanel() {
  const [expanded, setExpanded] = useState(false)
  const histories = useMemo(() => getKeeperHistory(), [])
  const multiYear = histories.filter(h => h.entries.length >= 2)
  const display = expanded ? multiYear : multiYear.slice(0, 8)

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between mb-3"
      >
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Keeper History
        </h3>
        <span className="text-[10px] text-gray-500">
          {expanded ? '▲ Less' : `▼ ${multiYear.length} keepers`}
        </span>
      </button>
      <div className="space-y-2.5">
        {display.map((h) => {
          const lastEntry = h.entries[h.entries.length - 1]
          const isActive = lastEntry.year >= 2026
          return (
            <div key={h.playerName}>
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className={`text-[11px] font-semibold ${isActive ? 'text-emerald-400' : 'text-gray-300'}`}>
                  {h.playerName}
                </span>
                {isActive && (
                  <span className="text-[8px] px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-medium leading-none">
                    ACTIVE
                  </span>
                )}
              </div>
              <div className="flex items-center gap-0.5 pl-2 text-[10px] text-gray-500">
                <span className="text-gray-600">{h.entries[0].manager}</span>
                <span className="mx-1 text-gray-700">·</span>
                {h.entries.map((e, i) => (
                  <span key={i} className="flex items-center gap-0.5">
                    {i > 0 && <span className="text-gray-700 mx-0.5">&rarr;</span>}
                    <span className={`px-1 py-0.5 rounded font-mono ${
                      e.year >= 2026
                        ? 'bg-emerald-500/15 text-emerald-400'
                        : 'bg-gray-800 text-gray-400'
                    }`}>
                      Rd {e.roundCost}
                    </span>
                    <span className="text-gray-600">&rsquo;{String(e.year).slice(2)}</span>
                  </span>
                ))}
              </div>
            </div>
          )
        })}
      </div>
      {multiYear.length > 8 && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="mt-3 w-full text-[10px] text-gray-500 hover:text-gray-400 transition-colors"
        >
          {expanded ? 'Show less' : `Show all ${multiYear.length} keepers...`}
        </button>
      )}
    </div>
  )
}
