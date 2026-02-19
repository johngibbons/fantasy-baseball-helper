'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import Link from 'next/link'
import { getDraftBoard, recalculateDraftValues, RankedPlayer } from '@/lib/valuations-api'
import {
  fetchLeagueTeams,
  saveTeamsToStorage,
  keeperPickIndex,
  type LeagueKeeperEntry,
} from '@/lib/league-teams'
import {
  analyzeCategoryStandings,
  detectStrategy,
  computeMCW,
  computeDraftScore,
  standingsConfidence,
  generateExplanation,
  expectedWeeklyWins,
  type CategoryAnalysis,
  type CategoryGain,
  type PlayerDraftScore,
  type DraftRecommendation,
} from '@/lib/draft-optimizer'

// ── Position filter buttons ──
const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP']

// ── Position badge colors ──
const posColor: Record<string, string> = {
  C: 'bg-blue-500', '1B': 'bg-amber-500', '2B': 'bg-orange-500', '3B': 'bg-purple-500',
  SS: 'bg-red-500', OF: 'bg-emerald-500', LF: 'bg-emerald-500', CF: 'bg-emerald-500',
  RF: 'bg-emerald-500', DH: 'bg-gray-500', SP: 'bg-sky-500', RP: 'bg-pink-500', P: 'bg-teal-500',
  TWP: 'bg-violet-500', UTIL: 'bg-gray-500',
}

// ── Roster slot configuration ──
const ROSTER_SLOTS: Record<string, number> = {
  C: 1, '1B': 1, '2B': 1, '3B': 1, SS: 1, OF: 3, UTIL: 2, SP: 3, RP: 2, P: 2,
}

// Maps ESPN positions to the roster slots they can fill (most restrictive first)
const POSITION_TO_SLOTS: Record<string, string[]> = {
  C: ['C', 'UTIL'], '1B': ['1B', 'UTIL'], '2B': ['2B', 'UTIL'],
  '3B': ['3B', 'UTIL'], SS: ['SS', 'UTIL'],
  OF: ['OF', 'UTIL'], LF: ['OF', 'UTIL'], CF: ['OF', 'UTIL'], RF: ['OF', 'UTIL'],
  DH: ['UTIL'],
  SP: ['SP', 'P'], RP: ['RP', 'P'],
  TWP: ['UTIL', 'SP', 'P'],
}

// ── Helpers ──

/** Classify a pitcher as SP or RP using z-score data (matches zscores.py logic) */
function pitcherRole(p: RankedPlayer): 'SP' | 'RP' {
  if (p.zscore_qs && p.zscore_qs !== 0) return 'SP'
  if (p.zscore_svhd && p.zscore_svhd !== 0) return 'RP'
  return 'SP' // default — matches backend's IP >= 80 heuristic
}

/** Parse eligible_positions string into raw position list, inferring SP/RP for pitchers */
function getPositions(p: RankedPlayer): string[] {
  if (p.eligible_positions) return p.eligible_positions.split('/')
  if (p.player_type === 'pitcher') return [pitcherRole(p)]
  return [p.primary_position]
}

/** Parse eligible_positions string into array of roster slots a player can fill */
function getEligibleSlots(p: RankedPlayer): string[] {
  const positions = getPositions(p)
  const slotSet = new Set<string>()
  for (const pos of positions) {
    const slots = POSITION_TO_SLOTS[pos]
    if (slots) slots.forEach((s) => slotSet.add(s))
  }
  return [...slotSet]
}

// ── Category definitions ──
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

// ── Roster slot display order ──
const SLOT_ORDER = ['C', '1B', '2B', '3B', 'SS', 'OF', 'UTIL', 'SP', 'RP', 'P']

// ── Default teams fallback ──
const DEFAULT_NUM_TEAMS = 10

// ── Snake order helper ──
function getActiveTeamId(pickIndex: number, order: number[]): number {
  if (order.length === 0) return -1
  const numTeams = order.length
  const round = Math.floor(pickIndex / numTeams)
  const posInRound = pickIndex % numTeams
  // Snake: even rounds go forward, odd rounds go backward
  return round % 2 === 0 ? order[posInRound] : order[numTeams - 1 - posInRound]
}

// ── Snake order: picks until a team's next turn ──
function getPicksUntilNextTurn(currentPickIndex: number, draftOrder: number[], teamId: number): number {
  if (draftOrder.length === 0) return 999
  for (let i = currentPickIndex + 1; i < currentPickIndex + draftOrder.length * 2; i++) {
    if (getActiveTeamId(i, draftOrder) === teamId) return i - currentPickIndex
  }
  return draftOrder.length * 2 // fallback: full snake round
}

// ── Types ──
interface DraftTeam { id: number; name: string }

/** Load keeper entries from localStorage */
function loadKeepersFromStorage(): LeagueKeeperEntry[] {
  try {
    const raw = localStorage.getItem('leagueKeepers')
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return []
}

interface DraftState {
  picks: [number, number][]  // [mlbId, teamId][]
  myTeamId: number | null
  draftOrder: number[]
  currentPickIndex: number
  keeperMlbIds?: number[]
}

export default function DraftBoardPage() {
  const [allPlayers, setAllPlayers] = useState<RankedPlayer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchText, setSearchText] = useState('')
  const [posFilter, setPosFilter] = useState('All')
  const [showDrafted, setShowDrafted] = useState(false)
  const [recalcData, setRecalcData] = useState<Map<number, RankedPlayer> | null>(null)
  const [recalculating, setRecalculating] = useState(false)
  const [sortKey, setSortKey] = useState<'rank' | 'adp' | 'name' | 'pos' | 'team' | 'value' | 'score'>('rank')
  const [sortAsc, setSortAsc] = useState(true)

  // ── Team-aware draft state ──
  const [leagueTeams, setLeagueTeams] = useState<DraftTeam[]>([])
  const [draftPicks, setDraftPicks] = useState<Map<number, number>>(new Map()) // mlb_id → teamId
  const [myTeamId, setMyTeamId] = useState<number | null>(null)
  const [draftOrder, setDraftOrder] = useState<number[]>([])
  const [currentPickIndex, setCurrentPickIndex] = useState(0)
  const [showDraftOrder, setShowDraftOrder] = useState(false)
  const [overrideTeam, setOverrideTeam] = useState<number | null>(null)

  // ── Keeper state ──
  const [leagueKeepersData, setLeagueKeepersData] = useState<LeagueKeeperEntry[]>([])
  const [keeperMlbIds, setKeeperMlbIds] = useState<Set<number>>(new Set())

  // ── Derived state (backward-compatible) ──
  const draftedIds = useMemo(() => new Set(draftPicks.keys()), [draftPicks])
  const myPickIds = useMemo(() => {
    if (!myTeamId) return new Set<number>()
    return new Set([...draftPicks].filter(([, tid]) => tid === myTeamId).map(([id]) => id))
  }, [draftPicks, myTeamId])

  // ── Active team on the clock ──
  const activeTeamId = useMemo(
    () => overrideTeam ?? getActiveTeamId(currentPickIndex, draftOrder),
    [currentPickIndex, draftOrder, overrideTeam]
  )
  const activeTeam = useMemo(
    () => leagueTeams.find((t) => t.id === activeTeamId),
    [leagueTeams, activeTeamId]
  )
  // ── Keeper pick indices (snake draft positions occupied by keepers) ──
  const keeperPickIndices = useMemo(() => {
    if (leagueKeepersData.length === 0 || draftOrder.length === 0) return new Set<number>()
    const indices = new Set<number>()
    for (const k of leagueKeepersData) {
      const idx = keeperPickIndex(k.teamId, k.roundCost, draftOrder)
      if (idx >= 0) indices.add(idx)
    }
    return indices
  }, [leagueKeepersData, draftOrder])

  const currentRound = draftOrder.length > 0 ? Math.floor(currentPickIndex / draftOrder.length) + 1 : 1
  const currentPickInRound = draftOrder.length > 0 ? (currentPickIndex % draftOrder.length) + 1 : currentPickIndex + 1

  // ── Team name lookup ──
  const teamNameMap = useMemo(() => {
    const m = new Map<number, string>()
    for (const t of leagueTeams) m.set(t.id, t.name)
    m.set(-1, 'Unknown')
    return m
  }, [leagueTeams])

  const getTeamAbbrev = useCallback((teamId: number) => {
    const name = teamNameMap.get(teamId) ?? `T${teamId}`
    // Use first 3 chars or abbreviation
    if (name.startsWith('Team ')) return `TM${name.slice(5)}`
    return name.slice(0, 4).toUpperCase()
  }, [teamNameMap])

  // ── Load players + restore state ──
  useEffect(() => {
    getDraftBoard()
      .then((data) => setAllPlayers(data.players))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))

    // Restore saved state
    try {
      const saved = localStorage.getItem('draftState')
      if (saved) {
        const state: DraftState = JSON.parse(saved)
        // New format
        if (state.picks) {
          setDraftPicks(new Map(state.picks))
          setMyTeamId(state.myTeamId ?? null)
          setDraftOrder(state.draftOrder ?? [])
          setCurrentPickIndex(state.currentPickIndex ?? 0)
          if (state.keeperMlbIds) {
            setKeeperMlbIds(new Set(state.keeperMlbIds))
          }
        }
        // Old format migration
        else if ((saved as unknown as { drafted?: number[]; myPicks?: number[] }).drafted) {
          const oldState = JSON.parse(saved) as { drafted?: number[]; myPicks?: number[] }
          const picks = new Map<number, number>()
          const oldMyPicks = new Set<number>(oldState.myPicks || [])
          for (const id of (oldState.drafted || [])) {
            if (oldMyPicks.has(id)) {
              picks.set(id, 0)
            } else {
              picks.set(id, -1)
            }
          }
          setDraftPicks(picks)
        }
      }
    } catch {}

    // Load keepers from localStorage
    const keepers = loadKeepersFromStorage()
    if (keepers.length > 0) {
      setLeagueKeepersData(keepers)
    }
  }, [])

  // ── Load teams (shared logic) ──
  useEffect(() => {
    fetchLeagueTeams().then((teams) => {
      setLeagueTeams(teams)
      saveTeamsToStorage(teams)
      setDraftOrder(prev => prev.length > 0 ? prev : teams.map(t => t.id))
    })
  }, [])

  // ── Migrate old myPicks to use actual myTeamId once set ──
  useEffect(() => {
    if (myTeamId == null) return
    setDraftPicks(prev => {
      let changed = false
      const next = new Map(prev)
      for (const [mlbId, tid] of next) {
        if (tid === 0) {
          next.set(mlbId, myTeamId)
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [myTeamId])

  // ── Pre-fill keepers into draft picks ──
  useEffect(() => {
    if (leagueKeepersData.length === 0 || draftOrder.length === 0) return
    // Only pre-fill if no non-keeper picks exist yet (fresh draft)
    const nonKeeperPicks = [...draftPicks.entries()].filter(([id]) => !keeperMlbIds.has(id))
    if (nonKeeperPicks.length > 0) return

    const newPicks = new Map(draftPicks)
    const newKeeperIds = new Set(keeperMlbIds)
    let changed = false

    for (const k of leagueKeepersData) {
      if (!newPicks.has(k.mlb_id)) {
        newPicks.set(k.mlb_id, k.teamId)
        newKeeperIds.add(k.mlb_id)
        changed = true
      }
    }

    if (changed) {
      setDraftPicks(newPicks)
      setKeeperMlbIds(newKeeperIds)

      // Set currentPickIndex to first non-keeper slot
      let startIdx = 0
      const keeperIndices = new Set<number>()
      for (const k of leagueKeepersData) {
        const idx = keeperPickIndex(k.teamId, k.roundCost, draftOrder)
        if (idx >= 0) keeperIndices.add(idx)
      }
      while (keeperIndices.has(startIdx)) startIdx++
      setCurrentPickIndex(startIdx)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueKeepersData, draftOrder])

  // ── Load/reload keepers from localStorage ──
  const handleLoadKeepers = useCallback(() => {
    const keepers = loadKeepersFromStorage()
    if (keepers.length === 0) return

    setLeagueKeepersData(keepers)
    const newPicks = new Map(draftPicks)
    const newKeeperIds = new Set<number>()

    // Remove old keeper picks first
    for (const id of keeperMlbIds) {
      newPicks.delete(id)
    }

    // Add new keeper picks
    for (const k of keepers) {
      newPicks.set(k.mlb_id, k.teamId)
      newKeeperIds.add(k.mlb_id)
    }

    setDraftPicks(newPicks)
    setKeeperMlbIds(newKeeperIds)
  }, [draftPicks, keeperMlbIds])

  // ── Save state to localStorage ──
  useEffect(() => {
    if (allPlayers.length > 0) {
      const state: DraftState = {
        picks: [...draftPicks.entries()],
        myTeamId,
        draftOrder,
        currentPickIndex,
        keeperMlbIds: [...keeperMlbIds],
      }
      localStorage.setItem('draftState', JSON.stringify(state))
    }
  }, [draftPicks, myTeamId, draftOrder, currentPickIndex, allPlayers.length, keeperMlbIds])

  // ── Draft actions ──
  const draftPlayer = useCallback((mlbId: number) => {
    const teamId = overrideTeam ?? getActiveTeamId(currentPickIndex, draftOrder)
    setDraftPicks(prev => new Map(prev).set(mlbId, teamId))
    // Advance past keeper-occupied slots
    let nextIdx = currentPickIndex + 1
    while (keeperPickIndices.has(nextIdx)) nextIdx++
    setCurrentPickIndex(nextIdx)
    setOverrideTeam(null)
  }, [currentPickIndex, draftOrder, overrideTeam, keeperPickIndices])

  const undoLastPick = useCallback(() => {
    if (currentPickIndex <= 0 && draftPicks.size === 0) return
    // Find the last non-keeper pick (by insertion order)
    const entries = [...draftPicks.entries()]
    if (entries.length === 0) return
    // Walk backwards to find last non-keeper entry
    let lastNonKeeper: number | null = null
    for (let i = entries.length - 1; i >= 0; i--) {
      if (!keeperMlbIds.has(entries[i][0])) {
        lastNonKeeper = entries[i][0]
        break
      }
    }
    if (lastNonKeeper == null) return // all remaining picks are keepers
    setDraftPicks(prev => {
      const next = new Map(prev)
      next.delete(lastNonKeeper)
      return next
    })
    // Move pick index backward, skipping keeper slots
    let prevIdx = currentPickIndex - 1
    while (prevIdx >= 0 && keeperPickIndices.has(prevIdx)) prevIdx--
    setCurrentPickIndex(Math.max(0, prevIdx))
  }, [currentPickIndex, draftPicks, keeperMlbIds, keeperPickIndices])

  const undoPick = useCallback((mlbId: number) => {
    if (keeperMlbIds.has(mlbId)) return // cannot undo keeper picks
    setDraftPicks(prev => {
      const next = new Map(prev)
      next.delete(mlbId)
      return next
    })
    // Don't change currentPickIndex for individual undo — only last pick undo adjusts it
  }, [keeperMlbIds])

  const resetDraft = () => {
    if (confirm('Reset all draft picks? (Keepers will be preserved)')) {
      setRecalcData(null)
      setOverrideTeam(null)

      // Re-apply keepers from localStorage
      const keepers = loadKeepersFromStorage()
      const newPicks = new Map<number, number>()
      const newKeeperIds = new Set<number>()
      const keeperIndices = new Set<number>()

      for (const k of keepers) {
        newPicks.set(k.mlb_id, k.teamId)
        newKeeperIds.add(k.mlb_id)
        const idx = keeperPickIndex(k.teamId, k.roundCost, draftOrder)
        if (idx >= 0) keeperIndices.add(idx)
      }

      setLeagueKeepersData(keepers)
      setDraftPicks(newPicks)
      setKeeperMlbIds(newKeeperIds)

      // Find first non-keeper slot
      let startIdx = 0
      while (keeperIndices.has(startIdx)) startIdx++
      setCurrentPickIndex(startIdx)
    }
  }

  // ── Auto-recalculate values after every pick ──
  useEffect(() => {
    if (draftedIds.size === 0) {
      setRecalcData(null)
      return
    }
    setRecalculating(true)
    const timeout = setTimeout(async () => {
      try {
        const { players } = await recalculateDraftValues([...draftedIds])
        const map = new Map<number, RankedPlayer>()
        for (const p of players) map.set(p.mlb_id, p)
        setRecalcData(map)
      } catch (e) {
        console.error('Recalculation failed:', e)
      } finally {
        setRecalculating(false)
      }
    }, 300)
    return () => { clearTimeout(timeout); setRecalculating(false) }
  }, [draftedIds.size]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Get the effective value for a player — uses recalculated data if available */
  const getPlayerValue = (p: RankedPlayer): number => {
    if (recalcData) {
      const recalc = recalcData.get(p.mlb_id)
      if (recalc) return recalc.total_zscore
    }
    return p.total_zscore
  }

  // ── Filtered available players (multi-eligibility aware) ──
  const available = useMemo(() => {
    let list = allPlayers.filter((p) => !draftedIds.has(p.mlb_id))
    if (posFilter !== 'All') {
      list = list.filter((p) => {
        const positions = getPositions(p)
        // Map filter positions: OF filter should match LF/CF/RF too
        if (posFilter === 'OF') {
          return positions.some((pos) => ['OF', 'LF', 'CF', 'RF'].includes(pos))
        }
        return positions.includes(posFilter) || p.primary_position === posFilter
      })
    }
    if (searchText) {
      const q = searchText.toLowerCase()
      list = list.filter((p) => p.full_name.toLowerCase().includes(q))
    }
    return list
  }, [allPlayers, draftedIds, posFilter, searchText])

  const drafted = useMemo(() => {
    return allPlayers.filter((p) => draftedIds.has(p.mlb_id)).sort((a, b) => a.overall_rank - b.overall_rank)
  }, [allPlayers, draftedIds])

  const myTeam = useMemo(() => {
    return allPlayers.filter((p) => myPickIds.has(p.mlb_id)).sort((a, b) => a.overall_rank - b.overall_rank)
  }, [allPlayers, myPickIds])

  const myTeamZScore = useMemo(() => myTeam.reduce((s, p) => s + (p.total_zscore || 0), 0), [myTeam])

  // ── Roster assignment (greedy, most constrained first) ──
  const rosterState = useMemo(() => {
    const capacity: Record<string, number> = { ...ROSTER_SLOTS }
    const assignments: { slot: string; player: RankedPlayer }[] = []
    const unassigned: RankedPlayer[] = []

    // Sort by fewest eligible slots first (most constrained)
    const sorted = [...myTeam].sort((a, b) => getEligibleSlots(a).length - getEligibleSlots(b).length)

    for (const player of sorted) {
      const slots = getEligibleSlots(player)
      let placed = false
      for (const slot of slots) {
        if ((capacity[slot] || 0) > 0) {
          capacity[slot]--
          assignments.push({ slot, player })
          placed = true
          break
        }
      }
      if (!placed) unassigned.push(player)
    }

    return { assignments, remainingCapacity: capacity, unassigned }
  }, [myTeam])

  // ── Category balance (my team) ──
  const categoryBalance = useMemo(() => {
    const totals: Record<string, number> = {}
    for (const cat of ALL_CATS) totals[cat.key] = 0
    for (const p of myTeam) {
      for (const cat of ALL_CATS) {
        totals[cat.key] += ((p as unknown as Record<string, number>)[cat.key] ?? 0)
      }
    }
    return totals
  }, [myTeam])

  // ── Draft comparison: all teams' category totals ──
  const teamCategories = useMemo(() => {
    const playerMap = new Map(allPlayers.map(p => [p.mlb_id, p]))
    const teams = new Map<number, { totals: Record<string, number>; count: number; total: number }>()

    for (const [mlbId, teamId] of draftPicks) {
      const p = playerMap.get(mlbId)
      if (!p) continue
      if (!teams.has(teamId)) teams.set(teamId, { totals: {}, count: 0, total: 0 })
      const t = teams.get(teamId)!
      t.count++
      for (const cat of ALL_CATS) {
        const val = (p as unknown as Record<string, number>)[cat.key] ?? 0
        t.totals[cat.key] = (t.totals[cat.key] ?? 0) + val
        t.total += val
      }
    }

    // Build ranked array sorted by total descending
    const rows = [...teams.entries()]
      .filter(([tid]) => tid !== -1) // exclude unknown
      .map(([teamId, data]) => ({
        teamId,
        teamName: teamNameMap.get(teamId) ?? `Team ${teamId}`,
        ...data,
      }))
      .sort((a, b) => b.total - a.total)

    // Compute per-category ranks (1 = best)
    const catRanks = new Map<string, Map<number, number>>()
    for (const cat of ALL_CATS) {
      const sorted = [...rows].sort((a, b) => (b.totals[cat.key] ?? 0) - (a.totals[cat.key] ?? 0))
      const rankMap = new Map<number, number>()
      sorted.forEach((r, i) => rankMap.set(r.teamId, i + 1))
      catRanks.set(cat.key, rankMap)
    }

    return { rows, catRanks, teamCount: rows.length }
  }, [allPlayers, draftPicks, teamNameMap])

  // ── Category standings analysis (MCW model) ──
  const categoryStandings = useMemo((): CategoryAnalysis[] => {
    if (!myTeamId || teamCategories.rows.length < 2) return []
    const numTeams = leagueTeams.length || DEFAULT_NUM_TEAMS
    const myRow = teamCategories.rows.find(r => r.teamId === myTeamId)
    if (!myRow) return []

    const raw = analyzeCategoryStandings(
      myTeamId,
      myRow.totals,
      teamCategories.rows,
      ALL_CATS.map(c => ({ key: c.key, label: c.label })),
      numTeams
    )
    return detectStrategy(raw, myTeam.length, numTeams)
  }, [myTeamId, teamCategories, leagueTeams.length, myTeam.length])

  // ── Other teams' totals per category (sorted desc, for MCW computation) ──
  const otherTeamTotals = useMemo((): Record<string, number[]> => {
    if (!myTeamId) return {}
    const result: Record<string, number[]> = {}
    const otherRows = teamCategories.rows.filter(r => r.teamId !== myTeamId)
    for (const cat of ALL_CATS) {
      result[cat.key] = otherRows
        .map(r => r.totals[cat.key] ?? 0)
        .sort((a, b) => b - a)
    }
    return result
  }, [myTeamId, teamCategories])

  // ── Strategy map (catKey → strategy string) ──
  const strategyMap = useMemo((): Record<string, CategoryAnalysis['strategy']> => {
    const map: Record<string, CategoryAnalysis['strategy']> = {}
    for (const s of categoryStandings) {
      map[s.catKey] = s.strategy
    }
    return map
  }, [categoryStandings])

  // ── Expected weekly wins ──
  const expectedWins = useMemo(() => {
    if (categoryStandings.length === 0) return null
    return expectedWeeklyWins(categoryStandings)
  }, [categoryStandings])

  // ── Best available by need ──
  const bestByNeed = useMemo(() => {
    const results: { slot: string; player: RankedPlayer }[] = []
    const availablePlayers = allPlayers.filter((p) => !draftedIds.has(p.mlb_id))
    for (const slot of SLOT_ORDER) {
      if ((rosterState.remainingCapacity[slot] || 0) <= 0) continue
      const best = availablePlayers.find((p) => getEligibleSlots(p).includes(slot))
      if (best) results.push({ slot, player: best })
    }
    return results
  }, [allPlayers, draftedIds, rosterState.remainingCapacity])

  // ── ADP value picks ──
  const adpSteals = useMemo(() => {
    const availablePlayers = allPlayers.filter((p) => !draftedIds.has(p.mlb_id))
    return availablePlayers
      .filter((p) => p.adp_diff != null && p.adp_diff < -10)
      .sort((a, b) => (a.adp_diff ?? 0) - (b.adp_diff ?? 0))
      .slice(0, 3)
  }, [allPlayers, draftedIds])

  // ── VONA (Value Over Next Available) ──
  const vonaMap = useMemo(() => {
    const availablePlayers = allPlayers.filter((p) => !draftedIds.has(p.mlb_id))
    const byPosition: Record<string, RankedPlayer[]> = {}
    for (const p of availablePlayers) {
      const positions = getPositions(p)
      for (const pos of positions) {
        if (!byPosition[pos]) byPosition[pos] = []
        byPosition[pos].push(p)
      }
    }
    for (const pos of Object.keys(byPosition)) {
      byPosition[pos].sort((a, b) => getPlayerValue(b) - getPlayerValue(a))
    }
    const vona = new Map<number, number>()
    for (const p of availablePlayers) {
      const primaryPos = p.player_type === 'pitcher' ? pitcherRole(p) : getPositions(p)[0]
      const posPlayers = byPosition[primaryPos] || []
      const myIdx = posPlayers.findIndex((x) => x.mlb_id === p.mlb_id)
      const myValue = getPlayerValue(p)
      if (myIdx >= 0 && myIdx < posPlayers.length - 1) {
        const nextValue = getPlayerValue(posPlayers[myIdx + 1])
        vona.set(p.mlb_id, myValue - nextValue)
      } else {
        vona.set(p.mlb_id, myValue)
      }
    }
    return vona
  }, [allPlayers, draftedIds, recalcData])

  const hasAdpData = allPlayers.some((p) => p.espn_adp != null)
  const isMyTeamOnClock = myTeamId != null && activeTeamId === myTeamId

  // ── Priority map ──
  const picksUntilMine = useMemo(
    () => myTeamId != null ? getPicksUntilNextTurn(currentPickIndex, draftOrder, myTeamId) : 999,
    [currentPickIndex, draftOrder, myTeamId]
  )

  const draftScoreMap = useMemo(() => {
    const map = new Map<number, PlayerDraftScore>()
    const availablePlayers = allPlayers.filter((p) => !draftedIds.has(p.mlb_id))
    const numTeams = leagueTeams.length || DEFAULT_NUM_TEAMS
    const totalSlots = Object.values(ROSTER_SLOTS).reduce((a, b) => a + b, 0)
    const totalPicksMade = draftPicks.size
    const confidence = standingsConfidence(totalPicksMade)
    const draftProgress = Math.min(1, myTeam.length / totalSlots)
    const hasMCW = categoryStandings.length > 0 && Object.keys(otherTeamTotals).length > 0
    const myRow = myTeamId ? teamCategories.rows.find(r => r.teamId === myTeamId) : null

    for (const p of availablePlayers) {
      const value = getPlayerValue(p)
      const vona = vonaMap.get(p.mlb_id) ?? 0
      let urgency = 0
      let badge: 'NOW' | 'WAIT' | null = null

      if (myTeamId != null && p.espn_adp != null) {
        const adpGap = p.espn_adp - currentPickIndex
        urgency = Math.max(0, Math.min(15, picksUntilMine - adpGap))

        if (p.espn_adp <= currentPickIndex + picksUntilMine) {
          badge = 'NOW'
        } else if (p.espn_adp > currentPickIndex + picksUntilMine * 2) {
          badge = 'WAIT'
        }
      }

      // Compute MCW if we have standings data
      let mcw = 0
      let categoryGains: CategoryGain[] = []

      if (hasMCW && myRow) {
        const playerZscores: Record<string, number> = {}
        for (const cat of ALL_CATS) {
          playerZscores[cat.key] = (p as unknown as Record<string, number>)[cat.key] ?? 0
        }
        const mcwResult = computeMCW(
          playerZscores,
          myRow.totals,
          otherTeamTotals,
          strategyMap,
          ALL_CATS.map(c => ({ key: c.key, label: c.label })),
          numTeams
        )
        mcw = mcwResult.mcw
        categoryGains = mcwResult.categoryGains
      }

      // Roster fit: 1 if fills a need, 0 otherwise
      const needSlots = getEligibleSlots(p).filter(s => (rosterState.remainingCapacity[s] || 0) > 0)
      const rosterFit = needSlots.length > 0 ? 1 : 0

      let score: number
      if (hasMCW && confidence > 0) {
        score = computeDraftScore(mcw, vona, urgency, rosterFit, confidence, draftProgress)
        // Blend with raw value when confidence is low
        const rawScore = value + vona * 0.5 + urgency * 0.3
        score = score * confidence + rawScore * (1 - confidence)
      } else {
        // Fallback: old formula
        score = value + vona * 0.5 + urgency * 0.3
      }

      map.set(p.mlb_id, { mlbId: p.mlb_id, score, mcw, vona, urgency, badge, categoryGains })
    }
    return map
  }, [allPlayers, draftedIds, vonaMap, myTeamId, currentPickIndex, picksUntilMine, recalcData,
      categoryStandings, otherTeamTotals, strategyMap, teamCategories, leagueTeams.length,
      myTeam.length, draftPicks.size, rosterState.remainingCapacity])

  // ── Top recommendation with explanation ──
  const topRecommendation = useMemo((): DraftRecommendation | null => {
    if (!myTeamId) return null
    const entries = [...draftScoreMap.entries()]
      .sort((a, b) => b[1].score - a[1].score)
      .slice(0, 3)
      .map(([mlbId, ds]) => {
        const p = allPlayers.find(x => x.mlb_id === mlbId)
        if (!p) return null
        return { ...ds, fullName: p.full_name, position: getPositions(p)[0] }
      })
      .filter((x): x is PlayerDraftScore & { fullName: string; position: string } => x !== null)

    if (entries.length === 0) return null

    const primary = entries[0]
    const explanation = generateExplanation(
      primary,
      primary.categoryGains,
      primary.vona,
      primary.urgency,
      getEligibleSlots(allPlayers.find(p => p.mlb_id === primary.mlbId)!).some(s => (rosterState.remainingCapacity[s] || 0) > 0) ? 1 : 0,
      strategyMap
    )

    return {
      primary,
      explanation,
      runnersUp: entries.slice(1),
    }
  }, [draftScoreMap, allPlayers, myTeamId, strategyMap, rosterState.remainingCapacity])

  const handleSort = useCallback((key: typeof sortKey) => {
    if (sortKey === key) {
      setSortAsc(prev => !prev)
    } else {
      setSortKey(key)
      // Sensible defaults: descending for value/score, ascending for others
      setSortAsc(key !== 'value' && key !== 'score')
    }
  }, [sortKey])

  const sortedAvailable = useMemo(() => {
    const list = [...available]
    const dir = sortAsc ? 1 : -1

    list.sort((a, b) => {
      let cmp = 0
      switch (sortKey) {
        case 'rank':
          cmp = a.overall_rank - b.overall_rank
          break
        case 'adp':
          cmp = (a.espn_adp ?? 9999) - (b.espn_adp ?? 9999)
          break
        case 'name':
          cmp = a.full_name.localeCompare(b.full_name)
          break
        case 'pos':
          cmp = getPositions(a)[0].localeCompare(getPositions(b)[0])
          break
        case 'team':
          cmp = (a.team ?? '').localeCompare(b.team ?? '')
          break
        case 'value':
          cmp = getPlayerValue(a) - getPlayerValue(b)
          break
        case 'score': {
          const aScore = draftScoreMap.get(a.mlb_id)?.score ?? vonaMap.get(a.mlb_id) ?? 0
          const bScore = draftScoreMap.get(b.mlb_id)?.score ?? vonaMap.get(b.mlb_id) ?? 0
          cmp = aScore - bScore
          break
        }
      }
      return cmp * dir
    })
    return list
  }, [available, sortKey, sortAsc, draftScoreMap, vonaMap, recalcData])

  if (loading) {
    return (
      <main className="min-h-screen bg-gray-950">
        <div className="max-w-7xl mx-auto px-6 py-20 text-center text-gray-500">
          <div className="inline-block w-6 h-6 border-2 border-gray-600 border-t-blue-500 rounded-full animate-spin mb-3" />
          <div>Loading draft board...</div>
        </div>
      </main>
    )
  }

  if (error) {
    return (
      <main className="min-h-screen bg-gray-950">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="bg-red-950 border border-red-800 rounded-xl p-6 text-red-300">{error}</div>
        </div>
      </main>
    )
  }

  const displayList = showDrafted
    ? [...sortedAvailable, ...drafted]
    : sortedAvailable

  // Build a set of assigned player IDs by slot for the roster grid
  const slotAssignments: Record<string, RankedPlayer[]> = {}
  for (const slot of SLOT_ORDER) {
    slotAssignments[slot] = rosterState.assignments
      .filter((a) => a.slot === slot)
      .map((a) => a.player)
  }

  // Find weakest category
  const allCatEntries = ALL_CATS.map((c) => ({
    ...c,
    value: categoryBalance[c.key] ?? 0,
  }))
  const weakestCat = myTeam.length > 0
    ? allCatEntries.reduce((min, c) => (c.value < min.value ? c : min), allCatEntries[0])
    : null

  // Find the single highest-value suggestion
  const topSuggestion = bestByNeed.length > 0
    ? bestByNeed.reduce((best, cur) => cur.player.total_zscore > best.player.total_zscore ? cur : best)
    : null

  return (
    <main className="min-h-screen bg-gray-950">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex items-end justify-between mb-5">
          <div>
            <h1 className="text-2xl font-bold text-white">Draft Board</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              <span className="text-emerald-400 font-semibold">{available.length}</span> available
              <span className="text-gray-600 mx-1.5">/</span>
              <span className="text-red-400 font-semibold">{draftedIds.size}</span> drafted
              <span className="text-gray-600 mx-1.5">/</span>
              <span className="text-blue-400 font-semibold">{myPickIds.size}</span> my picks
              {keeperMlbIds.size > 0 && (
                <>
                  <span className="text-gray-600 mx-1.5">/</span>
                  <span className="text-amber-400 font-semibold">{keeperMlbIds.size}</span> keepers
                </>
              )}
              {recalculating && (
                <>
                  <span className="text-gray-600 mx-1.5">/</span>
                  <span className="inline-block w-2.5 h-2.5 border-[1.5px] border-indigo-800 border-t-indigo-400 rounded-full animate-spin align-middle" />
                  <span className="text-indigo-400 ml-1">updating values</span>
                </>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={resetDraft}
              className="px-4 py-2 text-xs font-semibold bg-red-950 text-red-400 border border-red-800 rounded-lg hover:bg-red-900 transition-colors"
            >
              Reset Draft
            </button>
          </div>
        </div>

        {/* Draft Toolbar */}
        <div className={`bg-gray-900 rounded-xl border mb-4 p-3 flex flex-wrap items-center gap-4 ${isMyTeamOnClock ? 'border-blue-600 shadow-lg shadow-blue-500/10' : 'border-gray-800'}`}>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-gray-500">Round</span>
            <span className="font-bold text-white tabular-nums">{currentRound}</span>
            <span className="text-gray-700">|</span>
            <span className="text-gray-500">Pick</span>
            <span className="font-bold text-white tabular-nums">{currentPickInRound}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-gray-500 text-sm">On the clock:</span>
            <span className={`font-bold text-sm ${isMyTeamOnClock ? 'text-blue-400' : 'text-white'}`}>
              {activeTeam?.name ?? `Team ${activeTeamId}`}
            </span>
          </div>

          <div className="flex items-center gap-2 ml-auto">
            <label className="text-gray-500 text-xs">My team:</label>
            <select
              value={myTeamId ?? ''}
              onChange={(e) => setMyTeamId(e.target.value ? parseInt(e.target.value) : null)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Select...</option>
              {leagueTeams.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-gray-500 text-xs">Override:</label>
            <select
              value={overrideTeam ?? ''}
              onChange={(e) => setOverrideTeam(e.target.value ? parseInt(e.target.value) : null)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Auto</option>
              {leagueTeams.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>

          <button
            onClick={undoLastPick}
            disabled={draftPicks.size === 0}
            className="px-3 py-1.5 text-xs font-semibold bg-gray-800 text-gray-400 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-gray-200 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Undo Last
          </button>

          <button
            onClick={handleLoadKeepers}
            className="px-3 py-1.5 text-xs font-semibold bg-amber-950 text-amber-400 border border-amber-800 rounded-lg hover:bg-amber-900 hover:text-amber-300 transition-colors"
          >
            Load Keepers
          </button>

          <button
            onClick={() => setShowDraftOrder(!showDraftOrder)}
            className="px-3 py-1.5 text-xs font-semibold bg-gray-800 text-gray-400 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-gray-200 transition-colors"
          >
            Draft Order
          </button>
        </div>

        {/* Draft Order Editor */}
        {showDraftOrder && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4 p-4">
            <h3 className="text-sm font-bold text-white mb-3">Draft Order</h3>
            <div className="flex flex-wrap gap-2">
              {draftOrder.map((teamId, idx) => {
                const team = leagueTeams.find(t => t.id === teamId)
                return (
                  <div key={teamId} className="flex items-center gap-1.5 bg-gray-800 rounded-lg px-2.5 py-1.5">
                    <span className="text-[10px] text-gray-500 font-bold tabular-nums w-4">{idx + 1}.</span>
                    <span className="text-xs text-white">{team?.name ?? `Team ${teamId}`}</span>
                    <div className="flex flex-col gap-0.5 ml-1">
                      <button
                        onClick={() => {
                          if (idx === 0) return
                          setDraftOrder(prev => {
                            const next = [...prev]
                            ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
                            return next
                          })
                        }}
                        disabled={idx === 0}
                        className="text-[8px] text-gray-500 hover:text-white disabled:opacity-20 leading-none"
                      >
                        &#9650;
                      </button>
                      <button
                        onClick={() => {
                          if (idx === draftOrder.length - 1) return
                          setDraftOrder(prev => {
                            const next = [...prev]
                            ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
                            return next
                          })
                        }}
                        disabled={idx === draftOrder.length - 1}
                        className="text-[8px] text-gray-500 hover:text-white disabled:opacity-20 leading-none"
                      >
                        &#9660;
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
          {/* Main board */}
          <div className="lg:col-span-3">
            {/* Filters */}
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-3 mb-4 flex flex-wrap gap-3 items-center">
              <div className="flex gap-1">
                {POSITIONS.map((p) => (
                  <button
                    key={p}
                    onClick={() => setPosFilter(p)}
                    className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                      posFilter === p
                        ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                        : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <input
                type="text"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                placeholder="Search players..."
                className="flex-1 min-w-48 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showDrafted}
                  onChange={(e) => setShowDrafted(e.target.checked)}
                  className="rounded bg-gray-800 border-gray-600 text-blue-600 focus:ring-blue-500 focus:ring-offset-0"
                />
                Show drafted
              </label>
            </div>

            <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-800 bg-gray-900/80">
                      <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider w-28">Draft</th>
                      <DraftTh label="#" field="rank" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="left" className="w-14" />
                      {hasAdpData && (
                        <DraftTh label="ADP" field="adp" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="right" className="w-16" />
                      )}
                      <DraftTh label="Player" field="name" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="left" />
                      <DraftTh label="Pos" field="pos" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="left" className="w-24" />
                      <DraftTh label="Team" field="team" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="left" />
                      <DraftTh label="Value" field="value" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="right" className="w-20">
                        {recalcData && (
                          <span className="text-[8px] px-1 py-0.5 rounded bg-indigo-900 text-indigo-300 font-bold normal-case tracking-normal">Dyn</span>
                        )}
                      </DraftTh>
                      <DraftTh
                        label={hasAdpData && myTeamId != null ? 'Score' : 'VONA'}
                        field="score"
                        sortKey={sortKey}
                        sortAsc={sortAsc}
                        onSort={handleSort}
                        align="right"
                        className="w-28"
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {displayList.map((p, idx) => {
                      const isDrafted = draftedIds.has(p.mlb_id)
                      const isMyPick = myPickIds.has(p.mlb_id)
                      const draftedByTeam = draftPicks.get(p.mlb_id)
                      const stripe = idx % 2 === 0 ? 'bg-gray-900' : 'bg-gray-900/50'
                      const rowBg = isMyPick
                        ? 'bg-blue-950/50 border-l-2 border-l-blue-500'
                        : isDrafted
                        ? 'opacity-40'
                        : stripe

                      const positions = getPositions(p)
                      const displayPos = positions[0]
                      const extraPositions = positions.slice(1)
                      const needSlots = isDrafted ? [] : getEligibleSlots(p).filter((s) => (rosterState.remainingCapacity[s] || 0) > 0)
                      const fillsNeed = needSlots.length > 0

                      return (
                        <tr key={p.mlb_id} className={`${rowBg} hover:bg-gray-800/80 transition-colors border-b border-gray-800/50`}>
                          <td className="px-3 py-1.5">
                            {isDrafted ? (
                              <div className="flex items-center gap-1">
                                <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold ${
                                  isMyPick ? 'bg-blue-900 text-blue-300' : 'bg-gray-700 text-gray-400'
                                }`}>
                                  {getTeamAbbrev(draftedByTeam ?? -1)}
                                </span>
                                {keeperMlbIds.has(p.mlb_id) ? (
                                  <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-900/60 text-amber-400 border border-amber-700/50 leading-none">
                                    KEEPER
                                  </span>
                                ) : (
                                  <button
                                    onClick={() => undoPick(p.mlb_id)}
                                    className="text-gray-600 hover:text-gray-300 text-xs transition-colors"
                                    title="Undo pick"
                                  >
                                    &#10005;
                                  </button>
                                )}
                              </div>
                            ) : (
                              <button
                                onClick={() => draftPlayer(p.mlb_id)}
                                className={`px-3 py-1 text-[10px] rounded-md font-bold uppercase tracking-wide transition-all ${
                                  isMyTeamOnClock
                                    ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20 hover:bg-blue-500'
                                    : 'bg-gray-800 text-gray-300 border border-gray-700 hover:bg-gray-700'
                                }`}
                              >
                                Draft
                              </button>
                            )}
                          </td>
                          <td className="px-3 py-1.5 text-gray-500 font-mono text-xs tabular-nums">{p.overall_rank}</td>
                          {hasAdpData && (
                            <td className="px-3 py-1.5 text-right">
                              {p.espn_adp != null ? (
                                <div className="flex items-center justify-end gap-1">
                                  <span className="text-xs text-gray-500 tabular-nums">{Math.round(p.espn_adp)}</span>
                                  {p.adp_diff != null && Math.abs(p.adp_diff) > 5 && (
                                    <span className={`text-[10px] font-bold tabular-nums ${p.adp_diff < 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                      {p.adp_diff > 0 ? '+' : ''}{Math.round(p.adp_diff)}
                                    </span>
                                  )}
                                </div>
                              ) : (
                                <span className="text-xs text-gray-700">--</span>
                              )}
                            </td>
                          )}
                          <td className="px-3 py-1.5">
                            <Link href={`/player/${p.mlb_id}`} className="font-medium text-white hover:text-blue-400 transition-colors text-sm">
                              {p.full_name}
                            </Link>
                          </td>
                          <td className="px-3 py-1.5">
                            <div className="flex items-center gap-1">
                              <span className={`inline-flex items-center justify-center w-8 h-5 rounded text-[10px] font-bold text-white ${posColor[displayPos] || 'bg-gray-600'}`}>
                                {displayPos}
                              </span>
                              {extraPositions.length > 0 && (
                                <span className="text-[10px] text-gray-500">
                                  {extraPositions.join(' ')}
                                </span>
                              )}
                              {fillsNeed && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-amber-900/60 text-amber-400 border border-amber-700/50 leading-none">
                                  NEED
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-1.5 text-gray-400 text-sm">{p.team}</td>
                          <td className="px-3 py-1.5 text-right">
                            {(() => {
                              const value = getPlayerValue(p)
                              return (
                                <span className={`inline-block font-bold tabular-nums text-xs ${value > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {value > 0 ? '+' : ''}{value.toFixed(1)}
                                </span>
                              )
                            })()}
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            {!isDrafted && (() => {
                              const ds = draftScoreMap.get(p.mlb_id)
                              const vona = vonaMap.get(p.mlb_id)
                              const showScore = hasAdpData && myTeamId != null

                              if (showScore && ds) {
                                return (
                                  <div className="flex items-center justify-end gap-1">
                                    {ds.badge === 'NOW' && (
                                      <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-red-900/60 text-red-300 border border-red-700/50 leading-none">
                                        NOW
                                      </span>
                                    )}
                                    {ds.badge === 'WAIT' && (
                                      <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-gray-800 text-gray-500 border border-gray-700/50 leading-none">
                                        WAIT
                                      </span>
                                    )}
                                    <span className={`font-bold tabular-nums text-xs ${ds.score > 0 ? 'text-purple-400' : 'text-gray-500'}`}>
                                      {ds.score.toFixed(1)}
                                    </span>
                                  </div>
                                )
                              }

                              // Fallback: VONA display
                              if (vona == null) return <span className="text-xs text-gray-700">--</span>
                              const opacity = Math.min(1, 0.3 + (vona / 5) * 0.7)
                              return (
                                <span
                                  className="inline-block font-bold tabular-nums text-xs"
                                  style={{ color: `rgba(52, 211, 153, ${Math.max(0.3, opacity)})` }}
                                >
                                  {vona.toFixed(1)}
                                </span>
                              )
                            })()}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Sidebar */}
          <div className="lg:col-span-1">
            <div className="sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto space-y-4">

              {/* Section 1: Roster Grid */}
              <div className="bg-gray-900 rounded-xl border border-gray-800">
                <div className="px-4 py-3 border-b border-gray-800">
                  <h2 className="font-bold text-white text-sm">Roster</h2>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {myTeam.length} / {Object.values(ROSTER_SLOTS).reduce((a, b) => a + b, 0)} slots
                    <span className="text-gray-600 mx-1">&middot;</span>
                    Total Z: <span className="text-emerald-400 font-bold">{myTeamZScore > 0 ? '+' : ''}{myTeamZScore.toFixed(1)}</span>
                  </div>
                </div>
                <div className="px-3 py-2 space-y-0.5 max-h-[280px] overflow-y-auto">
                  {SLOT_ORDER.map((slot) => {
                    const count = ROSTER_SLOTS[slot]
                    const assigned = slotAssignments[slot] || []
                    return Array.from({ length: count }, (_, i) => {
                      const player = assigned[i]
                      const label = count > 1 ? `${slot}${i + 1}` : slot
                      return (
                        <div
                          key={`${slot}-${i}`}
                          className={`flex items-center gap-2 py-1.5 px-2 rounded-lg ${
                            player ? 'bg-gray-800/50' : 'border border-dashed border-gray-700/50'
                          }`}
                        >
                          <span className={`inline-flex items-center justify-center w-9 h-5 rounded text-[9px] font-bold text-white shrink-0 ${posColor[slot] || 'bg-gray-600'}`}>
                            {label}
                          </span>
                          {player ? (
                            <div className="flex-1 min-w-0 flex items-center justify-between gap-1">
                              <span className="text-xs text-white truncate">{player.full_name}</span>
                              <span className="text-[10px] font-bold tabular-nums text-emerald-400 shrink-0">
                                +{player.total_zscore.toFixed(1)}
                              </span>
                            </div>
                          ) : (
                            <span className="text-[11px] text-gray-600 italic">empty</span>
                          )}
                        </div>
                      )
                    })
                  })}
                  {rosterState.unassigned.length > 0 && (
                    <div className="pt-1 mt-1 border-t border-gray-800">
                      <div className="text-[10px] text-yellow-500 font-semibold uppercase tracking-wider mb-1">Extra</div>
                      {rosterState.unassigned.map((p) => (
                        <div key={p.mlb_id} className="flex items-center justify-between py-1 px-2">
                          <span className="text-xs text-yellow-400 truncate">{p.full_name}</span>
                          <span className="text-[10px] tabular-nums text-gray-500">+{p.total_zscore.toFixed(1)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Section 2: Category Balance */}
              {myTeam.length > 0 && (
                <div className="bg-gray-900 rounded-xl border border-gray-800">
                  <div className="px-4 py-3 border-b border-gray-800">
                    <h2 className="font-bold text-white text-sm">Category Balance</h2>
                    {weakestCat && (
                      <div className="text-[11px] text-red-400 mt-0.5">
                        Weakest: {weakestCat.label} ({weakestCat.value > 0 ? '+' : ''}{weakestCat.value.toFixed(1)})
                      </div>
                    )}
                  </div>
                  <div className="px-4 py-3 space-y-1">
                    <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-1">Hitting</div>
                    {HITTING_CATS.map((cat) => (
                      <CategoryBar
                        key={cat.key}
                        label={cat.label}
                        value={categoryBalance[cat.key]}
                        isWeakest={weakestCat?.key === cat.key}
                      />
                    ))}
                    <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mt-2 mb-1">Pitching</div>
                    {PITCHING_CATS.map((cat) => (
                      <CategoryBar
                        key={cat.key}
                        label={cat.label}
                        value={categoryBalance[cat.key]}
                        isWeakest={weakestCat?.key === cat.key}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Section 2.5: Strategy Panel (MCW model) */}
              {categoryStandings.length > 0 && myTeam.length >= 3 && (
                <div className="bg-gray-900 rounded-xl border border-gray-800">
                  <div className="px-4 py-3 border-b border-gray-800">
                    <h2 className="font-bold text-white text-sm">H2H Strategy</h2>
                    <div className="text-[11px] text-gray-500 mt-0.5">
                      {expectedWins != null ? (
                        <>Expected: <span className={`font-bold ${expectedWins >= 5.5 ? 'text-emerald-400' : expectedWins >= 4.5 ? 'text-yellow-400' : 'text-red-400'}`}>{expectedWins.toFixed(1)}</span> wins/week</>
                      ) : 'Win probability by category'}
                    </div>
                  </div>
                  <div className="px-3 py-2 space-y-0.5">
                    {categoryStandings.map((cat) => {
                      const pct = Math.round(cat.winProb * 100)
                      const strategyBadge = {
                        target: { label: 'TARGET', cls: 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50' },
                        lock: { label: 'LOCK', cls: 'bg-blue-900/60 text-blue-300 border-blue-700/50' },
                        punt: { label: 'PUNT', cls: 'bg-red-900/60 text-red-300 border-red-700/50' },
                        neutral: null,
                      }[cat.strategy]
                      return (
                        <div key={cat.catKey} className="flex items-center gap-1.5 py-1">
                          <span className="w-9 text-[10px] font-bold text-gray-400 text-right shrink-0">{cat.label}</span>
                          <div className="flex-1 h-3 bg-gray-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                cat.strategy === 'punt' ? 'bg-red-500/40' :
                                cat.strategy === 'lock' ? 'bg-blue-500/60' :
                                cat.strategy === 'target' ? 'bg-emerald-500/60' :
                                'bg-gray-600/60'
                              }`}
                              style={{ width: `${Math.max(pct, 3)}%` }}
                            />
                          </div>
                          <span className="w-5 text-[10px] font-bold tabular-nums text-gray-300 text-right shrink-0">{cat.myRank}</span>
                          <span className={`w-8 text-[10px] font-bold tabular-nums text-right shrink-0 ${
                            pct >= 60 ? 'text-emerald-400' : pct >= 40 ? 'text-yellow-400' : 'text-red-400'
                          }`}>{pct}%</span>
                          {strategyBadge && (
                            <span className={`px-1 py-0.5 rounded text-[7px] font-bold border leading-none shrink-0 ${strategyBadge.cls}`}>
                              {strategyBadge.label}
                            </span>
                          )}
                        </div>
                      )
                    })}
                    {/* Summary line */}
                    {(() => {
                      const punts = categoryStandings.filter(c => c.strategy === 'punt')
                      const targets = categoryStandings.filter(c => c.strategy === 'target')
                      if (punts.length === 0 && targets.length === 0) return null
                      return (
                        <div className="pt-1.5 mt-1 border-t border-gray-800 text-[10px] text-gray-500">
                          {punts.length > 0 && (
                            <span>Punting <span className="text-red-400 font-semibold">{punts.map(c => c.label).join(', ')}</span></span>
                          )}
                          {punts.length > 0 && targets.length > 0 && <span className="mx-1">&middot;</span>}
                          {targets.length > 0 && (
                            <span>Targeting <span className="text-emerald-400 font-semibold">{targets.map(c => c.label).join(', ')}</span></span>
                          )}
                        </div>
                      )
                    })()}
                  </div>
                </div>
              )}
              {myTeamId && myTeam.length > 0 && myTeam.length < 3 && (
                <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                  <div className="text-xs text-gray-500 text-center">Draft more players to enable H2H strategy analysis</div>
                </div>
              )}

              {/* Section 3: Draft Comparison Heatmap */}
              {teamCategories.rows.length > 0 && (
                <div className="bg-gray-900 rounded-xl border border-gray-800">
                  <div className="px-4 py-3 border-b border-gray-800">
                    <h2 className="font-bold text-white text-sm">Draft Comparison</h2>
                    <div className="text-[11px] text-gray-500 mt-0.5">
                      {teamCategories.rows.length} teams &middot; Z-score totals by category
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[10px]">
                      <thead>
                        <tr className="border-b border-gray-800">
                          <th className="px-2 py-1.5 text-left text-gray-500 font-semibold">Team</th>
                          {ALL_CATS.map((cat) => (
                            <th key={cat.key} className="px-1 py-1.5 text-center text-gray-500 font-semibold">{cat.label}</th>
                          ))}
                          <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">Tot</th>
                        </tr>
                      </thead>
                      <tbody>
                        {teamCategories.rows.map((row) => {
                          const isMyRow = row.teamId === myTeamId
                          return (
                            <tr
                              key={row.teamId}
                              className={`border-b border-gray-800/50 ${isMyRow ? 'bg-blue-950/30' : ''}`}
                            >
                              <td className={`px-2 py-1 font-semibold truncate max-w-[80px] ${isMyRow ? 'text-blue-400 border-l-2 border-l-blue-500' : 'text-gray-300'}`}>
                                {row.teamName.length > 12 ? getTeamAbbrev(row.teamId) : row.teamName}
                              </td>
                              {ALL_CATS.map((cat) => {
                                const val = row.totals[cat.key] ?? 0
                                const rank = teamCategories.catRanks.get(cat.key)?.get(row.teamId) ?? teamCategories.teamCount
                                const heatColor = getHeatColor(rank, teamCategories.teamCount)
                                return (
                                  <td
                                    key={cat.key}
                                    className="px-1 py-1 text-center font-bold tabular-nums"
                                    style={{ color: heatColor }}
                                  >
                                    {val.toFixed(1)}
                                  </td>
                                )
                              })}
                              <td className={`px-2 py-1 text-right font-bold tabular-nums ${row.total >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                {row.total > 0 ? '+' : ''}{row.total.toFixed(1)}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Section 4: Suggested Picks */}
              <div className="bg-gray-900 rounded-xl border border-gray-800">
                <div className="px-4 py-3 border-b border-gray-800">
                  <h2 className="font-bold text-white text-sm">Suggestions</h2>
                </div>
                <div className="px-3 py-2 space-y-2">
                  {/* Recommendation Card */}
                  {topRecommendation && (() => {
                    const { primary, explanation, runnersUp } = topRecommendation
                    const topGains = primary.categoryGains
                      .filter(g => g.winProbAfter - g.winProbBefore > 0.02)
                      .sort((a, b) => (b.winProbAfter - b.winProbBefore) - (a.winProbAfter - a.winProbBefore))
                      .slice(0, 3)
                    return (
                      <div>
                        <div className="text-[10px] text-purple-400 font-semibold uppercase tracking-wider mb-1">Recommended pick</div>
                        {/* Primary recommendation */}
                        <div className="py-2 px-2.5 rounded-lg bg-purple-950/30 border border-purple-800/30 mb-1.5">
                          <div className="flex items-center gap-2 mb-1.5">
                            <span className={`inline-flex items-center justify-center w-8 h-5 rounded text-[9px] font-bold text-white shrink-0 ${posColor[primary.position] || 'bg-gray-600'}`}>
                              {primary.position}
                            </span>
                            <span className="text-sm font-bold text-white truncate">{primary.fullName}</span>
                            <div className="flex items-center gap-1 ml-auto shrink-0">
                              {primary.badge === 'NOW' && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-red-900/60 text-red-300 border border-red-700/50 leading-none">NOW</span>
                              )}
                              {primary.badge === 'WAIT' && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-gray-800 text-gray-500 border border-gray-700/50 leading-none">WAIT</span>
                              )}
                              <span className="text-xs font-bold tabular-nums text-purple-400">{primary.score.toFixed(1)}</span>
                            </div>
                          </div>
                          {/* Category win probability shifts */}
                          {topGains.length > 0 && (
                            <div className="flex flex-wrap gap-x-3 gap-y-0.5 mb-1.5">
                              {topGains.map(g => (
                                <span key={g.catKey} className="text-[10px] tabular-nums">
                                  <span className="text-gray-500">{g.label}:</span>{' '}
                                  <span className="text-gray-400">{Math.round(g.winProbBefore * 100)}%</span>
                                  <span className="text-gray-600 mx-0.5">&rarr;</span>
                                  <span className="text-emerald-400 font-bold">{Math.round(g.winProbAfter * 100)}%</span>
                                </span>
                              ))}
                            </div>
                          )}
                          {/* Score breakdown */}
                          <div className="flex gap-3 text-[9px] text-gray-500 mb-1">
                            {primary.mcw > 0 && <span>MCW <span className="text-purple-400 font-bold">{primary.mcw.toFixed(2)}</span></span>}
                            <span>VONA <span className="text-emerald-400 font-bold">{primary.vona.toFixed(1)}</span></span>
                            {primary.urgency > 0 && <span>URG <span className="text-yellow-400 font-bold">{primary.urgency.toFixed(0)}</span></span>}
                          </div>
                          {/* Explanation */}
                          <div className="text-[10px] text-gray-400 leading-snug">{explanation}</div>
                        </div>
                        {/* Runners up */}
                        {runnersUp.map((ru) => (
                          <div
                            key={ru.mlbId}
                            className="flex items-center gap-2 py-1.5 px-2 rounded-lg bg-gray-800/30 mb-0.5"
                          >
                            <span className={`inline-flex items-center justify-center w-8 h-5 rounded text-[9px] font-bold text-white shrink-0 ${posColor[ru.position] || 'bg-gray-600'}`}>
                              {ru.position}
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="text-xs text-white truncate">{ru.fullName}</div>
                              {ru.categoryGains.filter(g => g.winProbAfter - g.winProbBefore > 0.02).length > 0 && (
                                <div className="text-[9px] text-gray-500">
                                  {ru.categoryGains
                                    .filter(g => g.winProbAfter - g.winProbBefore > 0.02)
                                    .sort((a, b) => (b.winProbAfter - b.winProbBefore) - (a.winProbAfter - a.winProbBefore))
                                    .slice(0, 2)
                                    .map(g => `${g.label}: ${Math.round(g.winProbBefore * 100)}%\u2192${Math.round(g.winProbAfter * 100)}%`)
                                    .join(' ')}
                                </div>
                              )}
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              {ru.badge === 'NOW' && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-red-900/60 text-red-300 border border-red-700/50 leading-none">NOW</span>
                              )}
                              <span className="text-[10px] font-bold tabular-nums text-purple-400">{ru.score.toFixed(1)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                  {/* Fallback: simple top scores when no recommendation card */}
                  {!topRecommendation && hasAdpData && myTeamId != null && (() => {
                    const topScores = [...draftScoreMap.entries()]
                      .sort((a, b) => b[1].score - a[1].score)
                      .slice(0, 3)
                      .map(([mlbId, ds]) => ({ player: allPlayers.find(p => p.mlb_id === mlbId)!, ...ds }))
                      .filter(x => x.player)
                    if (topScores.length === 0) return null
                    return (
                      <div>
                        <div className="text-[10px] text-purple-400 font-semibold uppercase tracking-wider mb-1">Top scores</div>
                        {topScores.map(({ player, score, badge }) => (
                          <div
                            key={player.mlb_id}
                            className="flex items-center gap-2 py-1.5 px-2 rounded-lg bg-purple-950/30 border border-purple-800/30 mb-0.5"
                          >
                            <span className={`inline-flex items-center justify-center w-8 h-5 rounded text-[9px] font-bold text-white shrink-0 ${posColor[getPositions(player)[0]] || 'bg-gray-600'}`}>
                              {getPositions(player)[0]}
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="text-xs text-white truncate">{player.full_name}</div>
                              <div className="text-[10px] text-gray-500">
                                #{player.overall_rank}
                                {player.espn_adp != null && <> &middot; ADP {Math.round(player.espn_adp)}</>}
                              </div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              {badge === 'NOW' && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-red-900/60 text-red-300 border border-red-700/50 leading-none">NOW</span>
                              )}
                              {badge === 'WAIT' && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-gray-800 text-gray-500 border border-gray-700/50 leading-none">WAIT</span>
                              )}
                              <span className="text-[10px] font-bold tabular-nums text-purple-400">{score.toFixed(1)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  })()}

                  {/* Best by need */}
                  {bestByNeed.length > 0 && (
                    <div>
                      <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-1">Best by need</div>
                      {bestByNeed.map(({ slot, player }) => {
                        const isTop = topSuggestion?.player.mlb_id === player.mlb_id
                        return (
                          <div
                            key={`${slot}-${player.mlb_id}`}
                            className={`flex items-center gap-2 py-1.5 px-2 rounded-lg ${
                              isTop ? 'bg-emerald-950/50 border border-emerald-800/50' : ''
                            }`}
                          >
                            <span className={`inline-flex items-center justify-center w-8 h-5 rounded text-[9px] font-bold text-white shrink-0 ${posColor[slot] || 'bg-gray-600'}`}>
                              {slot}
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="text-xs text-white truncate">{player.full_name}</div>
                              <div className="text-[10px] text-gray-500">#{player.overall_rank}</div>
                            </div>
                            <span className={`text-[10px] font-bold tabular-nums shrink-0 ${isTop ? 'text-emerald-300' : 'text-emerald-400'}`}>
                              +{player.total_zscore.toFixed(1)}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* ADP Steals */}
                  {hasAdpData && adpSteals.length > 0 && (
                    <div>
                      <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-1 mt-1">ADP steals</div>
                      {adpSteals.map((p) => (
                        <div key={p.mlb_id} className="flex items-center gap-2 py-1.5 px-2">
                          <span className={`inline-flex items-center justify-center w-8 h-5 rounded text-[9px] font-bold text-white shrink-0 ${posColor[p.primary_position] || 'bg-gray-600'}`}>
                            {p.primary_position}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="text-xs text-white truncate">{p.full_name}</div>
                            <div className="text-[10px] text-gray-500">
                              #{p.overall_rank} <span className="text-gray-600">&middot;</span> ADP {Math.round(p.espn_adp!)}
                            </div>
                          </div>
                          <span className="text-[10px] font-bold text-emerald-400 shrink-0">
                            +{Math.abs(Math.round(p.adp_diff!))}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {bestByNeed.length === 0 && adpSteals.length === 0 && (
                    <div className="py-4 text-center text-xs text-gray-600">
                      Pick players to see suggestions
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}

// ── Heatmap color helper ──
function getHeatColor(rank: number, total: number): string {
  if (total <= 1) return 'rgb(52, 211, 153)' // emerald
  // Map rank 1→green, rank N→red
  const t = (rank - 1) / (total - 1) // 0 = best, 1 = worst
  // Green (52, 211, 153) → Yellow (234, 179, 8) → Red (239, 68, 68)
  if (t <= 0.5) {
    const s = t * 2
    const r = Math.round(52 + (234 - 52) * s)
    const g = Math.round(211 + (179 - 211) * s)
    const b = Math.round(153 + (8 - 153) * s)
    return `rgb(${r}, ${g}, ${b})`
  } else {
    const s = (t - 0.5) * 2
    const r = Math.round(234 + (239 - 234) * s)
    const g = Math.round(179 + (68 - 179) * s)
    const b = Math.round(8 + (68 - 8) * s)
    return `rgb(${r}, ${g}, ${b})`
  }
}

// ── Category balance bar component ──
// ── Sortable table header for draft board ──
type DraftSortKey = 'rank' | 'adp' | 'name' | 'pos' | 'team' | 'value' | 'score'

function DraftTh({ label, field, sortKey, sortAsc, onSort, align = 'left', className = '', children }: {
  label: string; field: DraftSortKey; sortKey: DraftSortKey; sortAsc: boolean;
  onSort: (k: DraftSortKey) => void; align?: 'left' | 'right'; className?: string; children?: React.ReactNode
}) {
  const active = sortKey === field
  return (
    <th
      className={`px-3 py-2.5 ${align === 'right' ? 'text-right' : 'text-left'} text-[11px] font-semibold uppercase tracking-wider cursor-pointer select-none transition-colors whitespace-nowrap ${
        active ? 'text-blue-400' : 'text-gray-400 hover:text-gray-200'
      } ${className}`}
      onClick={() => onSort(field)}
    >
      <div className={`flex items-center gap-1 ${align === 'right' ? 'justify-end' : ''}`}>
        {label}
        {active && <span className="text-[8px]">{sortAsc ? '\u25B2' : '\u25BC'}</span>}
        {children}
      </div>
    </th>
  )
}

function CategoryBar({ label, value, isWeakest }: { label: string; value: number; isWeakest: boolean }) {
  // Scale bar: clamp to [-10, 10] for display
  const maxVal = 10
  const clamped = Math.max(-maxVal, Math.min(maxVal, value))
  const pct = Math.abs(clamped) / maxVal * 100

  return (
    <div className={`flex items-center gap-2 py-0.5 ${isWeakest ? 'bg-red-950/30 -mx-2 px-2 rounded' : ''}`}>
      <span className={`w-8 text-[10px] font-bold tabular-nums text-right shrink-0 ${isWeakest ? 'text-red-400' : 'text-gray-400'}`}>
        {label}
      </span>
      <div className="flex-1 h-3 bg-gray-800 rounded-full overflow-hidden relative">
        <div
          className={`h-full rounded-full transition-all ${
            value >= 0 ? 'bg-emerald-500/60' : 'bg-red-500/60'
          } ${isWeakest ? (value >= 0 ? 'bg-emerald-500/40' : 'bg-red-500/80') : ''}`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
      <span className={`w-9 text-[10px] font-bold tabular-nums text-right shrink-0 ${value >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
        {value > 0 ? '+' : ''}{value.toFixed(1)}
      </span>
    </div>
  )
}
