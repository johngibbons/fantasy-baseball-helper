'use client'

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import Link from 'next/link'
import { getDraftBoard, recalculateDraftValues, RankedPlayer } from '@/lib/valuations-api'
import {
  fetchLeagueTeams,
  saveTeamsToStorage,
  keeperPickIndex,
  generateSnakeSchedule,
  keeperPickIndexFromSchedule,
  tradePickInSchedule,
  type LeagueKeeperEntry,
  type PickSchedule,
  type PickTrade,
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
import { computeTiers } from '@/lib/tier-engine'
import { computeAvailability } from '@/lib/pick-predictor'
import { projectStandings, type ProjectedStanding } from '@/lib/projected-standings'
import {
  ROSTER_SLOTS, POSITION_TO_SLOTS, SLOT_ORDER, STARTER_SLOT_COUNT,
  PITCHER_BENCH_CONTRIBUTION, HITTER_BENCH_CONTRIBUTION,
  pitcherRole, getPositions, getEligibleSlots, optimizeRoster, type RosterResult,
} from '@/lib/roster-optimizer'
import {
  type CatDef, HITTING_CATS, PITCHING_CATS, ALL_CATS,
  posColor, getHeatColor, formatStat, computeTeamCategories,
} from '@/lib/draft-categories'
import { CategoryBar } from '@/components/CategoryBar'

// ── Position filter buttons ──
const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP']

// ── Default teams fallback ──
const DEFAULT_NUM_TEAMS = 10

// ── Default draft order (reverse of 2025 final standings) ──
const DEFAULT_DRAFT_ORDER = [5, 9, 2, 8, 3, 10, 4, 6, 1, 7]

// ── Snake order helper ──
function getActiveTeamId(pickIndex: number, order: number[]): number {
  if (order.length === 0) return -1
  const numTeams = order.length
  const round = Math.floor(pickIndex / numTeams)
  const posInRound = pickIndex % numTeams
  // Snake: even rounds go forward, odd rounds go backward
  return round % 2 === 0 ? order[posInRound] : order[numTeams - 1 - posInRound]
}

// ── Picks until a team's next turn (schedule-based) ──
function getPicksUntilNextTurn(currentPickIndex: number, schedule: number[], teamId: number): number {
  if (schedule.length === 0) return 999
  for (let i = currentPickIndex + 1; i < schedule.length; i++) {
    if (schedule[i] === teamId) return i - currentPickIndex
  }
  return 999
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
  pickSchedule?: number[]
  pickTrades?: PickTrade[]
  pickLog?: { pickIndex: number; mlbId: number; teamId: number }[]
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
  const [sortKey, setSortKey] = useState<'rank' | 'adp' | 'avail' | 'name' | 'pos' | 'team' | 'value' | 'score'>('rank')
  const [sortAsc, setSortAsc] = useState(true)
  const [mobileTab, setMobileTab] = useState<'board' | 'info'>('board')

  // ── Team-aware draft state ──
  const [leagueTeams, setLeagueTeams] = useState<DraftTeam[]>([])
  const [draftPicks, setDraftPicks] = useState<Map<number, number>>(new Map()) // mlb_id → teamId
  const [myTeamId, setMyTeamId] = useState<number | null>(null)
  const [draftOrder, setDraftOrder] = useState<number[]>([])
  const [currentPickIndex, setCurrentPickIndex] = useState(0)
  const [showDraftOrder, setShowDraftOrder] = useState(false)
  const [overrideTeam, setOverrideTeam] = useState<number | null>(null)
  const [pickSchedule, setPickSchedule] = useState<PickSchedule>([])
  const [pickTrades, setPickTrades] = useState<PickTrade[]>([])
  const [showPickTrader, setShowPickTrader] = useState(false)
  const [pickLog, setPickLog] = useState<{ pickIndex: number; mlbId: number; teamId: number }[]>([])
  const [showProjected, setShowProjected] = useState(false)

  // ── Keeper state ──
  const [leagueKeepersData, setLeagueKeepersData] = useState<LeagueKeeperEntry[]>([])
  const [keeperMlbIds, setKeeperMlbIds] = useState<Set<number>>(new Set())

  // ── Server sync state ──
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Derived state (backward-compatible) ──
  const draftedIds = useMemo(() => new Set(draftPicks.keys()), [draftPicks])
  const myPickIds = useMemo(() => {
    if (!myTeamId) return new Set<number>()
    return new Set([...draftPicks].filter(([, tid]) => tid === myTeamId).map(([id]) => id))
  }, [draftPicks, myTeamId])

  // ── Active team on the clock ──
  const activeTeamId = useMemo(
    () => overrideTeam ?? (pickSchedule.length > 0 ? pickSchedule[currentPickIndex] : getActiveTeamId(currentPickIndex, draftOrder)),
    [currentPickIndex, draftOrder, overrideTeam, pickSchedule]
  )
  const activeTeam = useMemo(
    () => leagueTeams.find((t) => t.id === activeTeamId),
    [leagueTeams, activeTeamId]
  )
  // ── Keeper pick indices (snake draft positions occupied by keepers) ──
  const keeperPickIndices = useMemo(() => {
    if (leagueKeepersData.length === 0 || draftOrder.length === 0) return new Set<number>()
    const numTeams = draftOrder.length
    const indices = new Set<number>()
    for (const k of leagueKeepersData) {
      const idx = pickSchedule.length > 0
        ? keeperPickIndexFromSchedule(k.teamId, k.roundCost, pickSchedule, numTeams)
        : keeperPickIndex(k.teamId, k.roundCost, draftOrder)
      if (idx >= 0) indices.add(idx)
    }
    return indices
  }, [leagueKeepersData, draftOrder, pickSchedule])

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
    if (name.startsWith('Team ')) return name.slice(5)
    return name.slice(0, 4).toUpperCase()
  }, [teamNameMap])

  // ── Load players + restore state ──
  useEffect(() => {
    getDraftBoard()
      .then((data) => setAllPlayers(data.players))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))

    // Restore saved state — try server first, fall back to localStorage
    const restoreFromState = (state: DraftState) => {
      if (state.picks) {
        setDraftPicks(new Map(state.picks))
        setMyTeamId(state.myTeamId ?? null)
        setDraftOrder(state.draftOrder ?? [])
        setCurrentPickIndex(state.currentPickIndex ?? 0)
        if (state.keeperMlbIds) {
          setKeeperMlbIds(new Set(state.keeperMlbIds))
        }
        if (state.pickSchedule && state.pickSchedule.length > 0) {
          setPickSchedule(state.pickSchedule)
        }
        if (state.pickTrades && state.pickTrades.length > 0) {
          setPickTrades(state.pickTrades)
        }
        if (state.pickLog && state.pickLog.length > 0) {
          setPickLog(state.pickLog)
        }
      }
    }

    const restoreFromLocalStorage = () => {
      try {
        const saved = localStorage.getItem('draftState')
        if (saved) {
          const state: DraftState = JSON.parse(saved)
          if (state.picks) {
            restoreFromState(state)
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
    }

    fetch('/api/v2/draft/state?season=2026')
      .then((res) => {
        if (!res.ok) throw new Error('Server error')
        return res.json()
      })
      .then((data) => {
        if (data.state) {
          restoreFromState(data.state as DraftState)
        } else {
          restoreFromLocalStorage()
        }
      })
      .catch(() => {
        restoreFromLocalStorage()
      })

    // Load keepers from localStorage
    const keepers = loadKeepersFromStorage()
    if (keepers.length > 0) {
      setLeagueKeepersData(keepers)
    }
  }, [])

  // ── Auto-generate schedule from draftOrder (only if no trades) ──
  useEffect(() => {
    if (draftOrder.length === 0) return
    if (pickTrades.length === 0) {
      setPickSchedule(generateSnakeSchedule(draftOrder))
    }
  }, [draftOrder, pickTrades.length])

  // ── Load teams (shared logic) ──
  useEffect(() => {
    fetchLeagueTeams().then((teams) => {
      setLeagueTeams(teams)
      saveTeamsToStorage(teams)
      setDraftOrder(prev => prev.length > 0 ? prev : DEFAULT_DRAFT_ORDER)
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

  // ── Save state to localStorage + server (debounced) ──
  useEffect(() => {
    if (allPlayers.length > 0) {
      const state: DraftState = {
        picks: [...draftPicks.entries()],
        myTeamId,
        draftOrder,
        currentPickIndex,
        keeperMlbIds: [...keeperMlbIds],
        pickSchedule,
        pickTrades,
        pickLog,
      }
      localStorage.setItem('draftState', JSON.stringify(state))

      // Debounced server save (2s)
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current)
      saveTimerRef.current = setTimeout(() => {
        setSaveStatus('saving')
        fetch('/api/v2/draft/state', {
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
    }
  }, [draftPicks, myTeamId, draftOrder, currentPickIndex, allPlayers.length, keeperMlbIds, pickSchedule, pickTrades, pickLog])

  // ── Draft actions ──
  const draftPlayer = useCallback((mlbId: number) => {
    const teamId = overrideTeam ?? (pickSchedule.length > 0 ? pickSchedule[currentPickIndex] : getActiveTeamId(currentPickIndex, draftOrder))
    setDraftPicks(prev => new Map(prev).set(mlbId, teamId))
    setPickLog(prev => [...prev, { pickIndex: currentPickIndex, mlbId, teamId }])
    // Advance past keeper-occupied slots
    let nextIdx = currentPickIndex + 1
    while (keeperPickIndices.has(nextIdx)) nextIdx++
    setCurrentPickIndex(nextIdx)
    setOverrideTeam(null)
  }, [currentPickIndex, draftOrder, overrideTeam, keeperPickIndices, pickSchedule])

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
    // Remove last non-keeper entry from pickLog
    setPickLog(prev => {
      const copy = [...prev]
      for (let i = copy.length - 1; i >= 0; i--) {
        if (!keeperMlbIds.has(copy[i].mlbId)) {
          copy.splice(i, 1)
          break
        }
      }
      return copy
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
    setPickLog(prev => prev.filter(e => e.mlbId !== mlbId))
    // Don't change currentPickIndex for individual undo — only last pick undo adjusts it
  }, [keeperMlbIds])

  const resetDraft = () => {
    if (confirm('Reset all draft picks? (Draft order, keepers, and pick trades will be preserved)')) {
      setRecalcData(null)
      setOverrideTeam(null)
      setPickLog([])

      // Re-apply keepers from localStorage
      const keepers = loadKeepersFromStorage()
      const newPicks = new Map<number, number>()
      const newKeeperIds = new Set<number>()
      const keeperIndicesSet = new Set<number>()
      const numTeams = draftOrder.length

      for (const k of keepers) {
        newPicks.set(k.mlb_id, k.teamId)
        newKeeperIds.add(k.mlb_id)
        const idx = pickSchedule.length > 0
          ? keeperPickIndexFromSchedule(k.teamId, k.roundCost, pickSchedule, numTeams)
          : keeperPickIndex(k.teamId, k.roundCost, draftOrder)
        if (idx >= 0) keeperIndicesSet.add(idx)
      }

      setLeagueKeepersData(keepers)
      setDraftPicks(newPicks)
      setKeeperMlbIds(newKeeperIds)

      // Find first non-keeper slot
      let startIdx = 0
      while (keeperIndicesSet.has(startIdx)) startIdx++
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

  // ── Per-team roster optimization (shared across memos) ──
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

  // ── My team roster assignment (derived from teamRosters) ──
  const rosterState = useMemo(
    () => teamRosters.get(myTeamId!) ?? optimizeRoster([]),
    [teamRosters, myTeamId]
  )

  // ── Category balance (my team: starters at full weight, bench weighted by player type) ──
  const categoryBalance = useMemo(() => {
    const totals: Record<string, number> = {}
    for (const cat of ALL_CATS) totals[cat.key] = 0
    for (const p of rosterState.starters) {
      for (const cat of ALL_CATS) {
        totals[cat.key] += ((p as unknown as Record<string, number>)[cat.key] ?? 0)
      }
    }
    for (const p of rosterState.bench) {
      const bc = p.player_type === 'pitcher' ? PITCHER_BENCH_CONTRIBUTION : HITTER_BENCH_CONTRIBUTION
      for (const cat of ALL_CATS) {
        totals[cat.key] += ((p as unknown as Record<string, number>)[cat.key] ?? 0) * bc
      }
    }
    return totals
  }, [rosterState])

  // ── Draft comparison: all teams' category totals (starters full, bench discounted) ──
  const teamCategories = useMemo(
    () => computeTeamCategories(teamRosters, teamNameMap),
    [teamRosters, teamNameMap],
  )

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
      if (slot === 'BE') continue // skip bench for best-available suggestions
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

  // ── Per-category standardization stats for z-score normalization ──
  // Full standardization (subtract mean, divide by stdev) equalizes hitter/pitcher
  // contributions. Without centering, hitter counting stats have much higher means
  // than pitcher rate stats, creating a ~12-point inherent offset in raw sums.
  const catStats = useMemo(() => {
    const availablePlayers = allPlayers.filter((p) => !draftedIds.has(p.mlb_id))
    const numTeams = leagueTeams.length || DEFAULT_NUM_TEAMS
    const draftableLimit = numTeams * 25
    const normPool = [...availablePlayers].sort((a, b) => a.overall_rank - b.overall_rank).slice(0, draftableLimit)
    const stats: Record<string, { mean: number; stdev: number }> = {}
    for (const cat of ALL_CATS) {
      const isHitterCat = HITTING_CATS.some(c => c.key === cat.key)
      const relevant = normPool.filter(p =>
        isHitterCat ? p.player_type === 'hitter' : p.player_type === 'pitcher'
      )
      const values = relevant.map(p => (p[cat.key as keyof RankedPlayer] as number) ?? 0)
      const mean = values.reduce((s, v) => s + v, 0) / (values.length || 1)
      const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / (values.length || 1)
      stats[cat.key] = { mean, stdev: Math.sqrt(variance) || 1 }
    }
    return stats
  }, [allPlayers, draftedIds, leagueTeams.length])

  // Sum of standardized z-scores (centered + scaled) — used for VONA and BPA scoring
  const getNormalizedValue = useCallback((p: RankedPlayer): number => {
    const cats = p.player_type === 'pitcher' ? PITCHING_CATS : HITTING_CATS
    let total = 0
    for (const cat of cats) {
      const recalc = recalcData?.get(p.mlb_id)
      const raw = recalc
        ? (recalc[cat.key as keyof RankedPlayer] as number) ?? 0
        : (p[cat.key as keyof RankedPlayer] as number) ?? 0
      const { mean, stdev } = catStats[cat.key]
      total += (raw - mean) / stdev
    }
    return total
  }, [catStats, recalcData])

  // ── Replacement levels for surplus value (VORP) ──
  const POSITION_DEMAND_SLOTS: Record<string, number> = { C: 1, '1B': 1, '2B': 1, '3B': 1, SS: 1, OF: 3, SP: 3, RP: 2 }
  const OF_ALIASES: Record<string, string> = { LF: 'OF', CF: 'OF', RF: 'OF' }
  const normalizePos = (pos: string) => OF_ALIASES[pos] ?? pos

  const replacementLevels = useMemo(() => {
    const availablePlayers = allPlayers.filter((p) => !draftedIds.has(p.mlb_id))
    const numTeams = leagueTeams.length || DEFAULT_NUM_TEAMS
    const byPos: Record<string, number[]> = {}
    for (const p of availablePlayers) {
      const nv = getNormalizedValue(p)
      if (p.player_type === 'pitcher') {
        const pos = pitcherRole(p)
        if (POSITION_DEMAND_SLOTS[pos] != null) {
          if (!byPos[pos]) byPos[pos] = []
          byPos[pos].push(nv)
        }
      } else {
        for (const rawPos of getPositions(p)) {
          const pos = normalizePos(rawPos)
          if (POSITION_DEMAND_SLOTS[pos] != null) {
            if (!byPos[pos]) byPos[pos] = []
            byPos[pos].push(nv)
          }
        }
      }
    }
    const levels: Record<string, number> = {}
    for (const [pos, slots] of Object.entries(POSITION_DEMAND_SLOTS)) {
      const nvs = (byPos[pos] || []).sort((a, b) => b - a)
      const depth = slots * numTeams
      const idx = Math.min(depth - 1, nvs.length - 1)
      levels[pos] = idx >= 0 ? nvs[idx] : 0
    }
    return levels
  }, [allPlayers, draftedIds, catStats, leagueTeams.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const getSurplusValue = useCallback((p: RankedPlayer, nv: number): number => {
    const positions = p.player_type === 'pitcher'
      ? [pitcherRole(p)]
      : [...new Set(getPositions(p).map(normalizePos))]
    let best: number | null = null
    for (const pos of positions) {
      const repl = replacementLevels[pos]
      if (repl != null) {
        const surplus = nv - repl
        if (best === null || surplus > best) best = surplus
      }
    }
    return best ?? nv
  }, [replacementLevels])

  // ── Picks until my next turn (needed by window VONA and availability) ──
  const picksUntilMine = useMemo(
    () => myTeamId != null ? getPicksUntilNextTurn(currentPickIndex, pickSchedule.length > 0 ? pickSchedule : draftOrder, myTeamId) : 999,
    [currentPickIndex, draftOrder, myTeamId, pickSchedule]
  )

  // ── VONA (Value Over Next Available) — window-based ──
  // Uses availability-weighted expected replacement value instead of literal next-best.
  // For each position, computes what you'd realistically get if you wait until your
  // next pick, accounting for the probability each alternative gets taken.
  const vonaMap = useMemo(() => {
    const availablePlayers = allPlayers.filter((p) => !draftedIds.has(p.mlb_id))
    const byPosition: Record<string, { player: RankedPlayer; nv: number; adp: number }[]> = {}
    for (const p of availablePlayers) {
      const nv = getNormalizedValue(p)
      const adp = p.espn_adp ?? 999
      for (const pos of getPositions(p)) {
        if (!byPosition[pos]) byPosition[pos] = []
        byPosition[pos].push({ player: p, nv, adp })
      }
    }
    for (const pos of Object.keys(byPosition)) {
      byPosition[pos].sort((a, b) => b.nv - a.nv)
    }
    // Compute window VONA at a single position for a given player
    const windowVonaAtPosition = (mlbId: number, myValue: number, pos: string): number => {
      const posPlayers = byPosition[pos] || []
      const alternatives: { nv: number; adp: number }[] = []
      for (const entry of posPlayers) {
        if (entry.player.mlb_id !== mlbId) {
          alternatives.push(entry)
        }
      }
      if (alternatives.length === 0) return myValue
      let expectedReplacement = 0
      let pAllGoneSoFar = 1.0
      for (const alt of alternatives) {
        const pAvail = computeAvailability(alt.adp, currentPickIndex, picksUntilMine)
        const pIsBest = pAllGoneSoFar * pAvail
        expectedReplacement += alt.nv * pIsBest
        pAllGoneSoFar *= (1 - pAvail)
      }
      return myValue - expectedReplacement
    }

    const vona = new Map<number, number>()
    for (const p of availablePlayers) {
      const myValue = getNormalizedValue(p)
      const positions = p.player_type === 'pitcher' ? [pitcherRole(p)] : getPositions(p)
      let bestVona = -Infinity
      for (const pos of positions) {
        bestVona = Math.max(bestVona, windowVonaAtPosition(p.mlb_id, myValue, pos))
      }
      vona.set(p.mlb_id, bestVona === -Infinity ? 0 : bestVona)
    }
    return vona
  }, [allPlayers, draftedIds, recalcData, catStats, currentPickIndex, picksUntilMine])

  const hasAdpData = allPlayers.some((p) => p.espn_adp != null)
  const isMyTeamOnClock = myTeamId != null && activeTeamId === myTeamId

  // ── Pick availability predictor ──
  const availabilityMap = useMemo(() => {
    if (myTeamId == null || !hasAdpData) return new Map<number, number>()
    const map = new Map<number, number>()
    for (const p of available) {
      if (p.espn_adp != null) {
        map.set(p.mlb_id, computeAvailability(p.espn_adp, currentPickIndex, picksUntilMine))
      }
    }
    return map
  }, [myTeamId, hasAdpData, available, currentPickIndex, picksUntilMine])

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

      // Roster fit: 1 if fills a starting roster need, 0 otherwise (bench doesn't count)
      const needSlots = getEligibleSlots(p).filter(s => s !== 'BE' && (rosterState.remainingCapacity[s] || 0) > 0)
      const rosterFit = needSlots.length > 0 ? 1 : 0

      let score: number
      const normalizedValue = getNormalizedValue(p)
      const surplusValue = getSurplusValue(p, normalizedValue)
      if (hasMCW && confidence > 0) {
        score = computeDraftScore(mcw, vona, urgency, rosterFit, confidence, draftProgress)
        // Blend with BPA (using surplus value) when confidence is low
        const rawScore = surplusValue + vona * 0.42 + urgency * 0.55
        score = score * confidence + rawScore * (1 - confidence)
      } else {
        // Fallback: BPA formula using surplus value
        score = surplusValue + vona * 0.42 + urgency * 0.55
      }

      // ── Multiplicative adjustments so #1 score = "pick this player now" ──

      // Bench penalty — pitcher-aware: softer penalty for first few bench pitchers
      // (daily league streaming/swap value), then saturates to full penalty
      if (rosterFit === 0 && draftProgress > 0.15) {
        if (p.player_type === 'pitcher') {
          const benchPitcherCount = rosterState.bench.filter(bp => bp.player_type === 'pitcher').length
          const saturation = Math.min(1, benchPitcherCount / 3)
          const floor = 0.65 - saturation * 0.30
          const scale = 0.35 + saturation * 0.28
          score *= Math.max(floor, 1 - draftProgress * scale)
        } else {
          score *= Math.max(0.35, 1 - draftProgress * 0.63)
        }
      }

      map.set(p.mlb_id, { mlbId: p.mlb_id, score, mcw, vona, urgency, badge, categoryGains })
    }
    return map
  }, [allPlayers, draftedIds, vonaMap, myTeamId, currentPickIndex, picksUntilMine, recalcData,
      categoryStandings, otherTeamTotals, strategyMap, teamCategories, leagueTeams.length,
      myTeam.length, draftPicks.size, rosterState.remainingCapacity, catStats,
      replacementLevels, getSurplusValue])

  // ── Score rank + recommendation zone ──
  // Zone uses stddev of top scores to adapt to score distribution.
  // Tight clusters → narrow zone; spread out scores → wider zone.
  // Clamped to [3, 8] players to avoid degenerate cases.
  const scoreRankMap = useMemo(() => {
    const entries = [...draftScoreMap.entries()]
      .sort((a, b) => b[1].score - a[1].score)
    const topScore = entries[0]?.[1].score ?? 0

    // Compute stddev of top ~15 scores for distribution-aware threshold
    const topN = entries.slice(0, Math.min(15, entries.length))
    const scores = topN.map(([, ds]) => ds.score)
    const mean = scores.reduce((a, b) => a + b, 0) / (scores.length || 1)
    const std = Math.sqrt(scores.reduce((a, s) => a + (s - mean) ** 2, 0) / (scores.length || 1))
    const rawThreshold = topScore - std

    // Count how many are above the raw threshold, then clamp to [3, 8]
    let zoneCount = 0
    for (const [, ds] of entries) {
      if (ds.score >= rawThreshold && ds.score > 0) zoneCount++
      else break
    }
    zoneCount = Math.max(3, Math.min(8, zoneCount))
    const threshold = entries[Math.min(zoneCount - 1, entries.length - 1)]?.[1].score ?? 0

    const map = new Map<number, { rank: number; inZone: boolean }>()
    entries.forEach(([mlbId, ds], i) => {
      map.set(mlbId, { rank: i + 1, inZone: ds.score >= threshold && ds.score > 0 })
    })
    return { map, threshold }
  }, [draftScoreMap])

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

  // ── Tier-based drafting ──
  const playerTiers = useMemo(
    () => computeTiers(available.map(p => ({ mlb_id: p.mlb_id, value: getPlayerValue(p) }))),
    [available, recalcData] // eslint-disable-line react-hooks/exhaustive-deps
  )
  const tierUrgency = useMemo(() => {
    // Tiers with <=2 remaining players
    const tierCounts = new Map<number, number>()
    for (const [, tier] of playerTiers) {
      tierCounts.set(tier, (tierCounts.get(tier) ?? 0) + 1)
    }
    const urgent = new Set<number>()
    for (const [tier, count] of tierCounts) {
      if (count <= 2) urgent.add(tier)
    }
    return urgent
  }, [playerTiers])

  // ── Opponent needs ──
  const opponentNeeds = useMemo(() => {
    if (!myTeamId || leagueTeams.length < 2) return []

    return leagueTeams
      .filter(t => t.id !== myTeamId)
      .map(team => {
        const roster = teamRosters.get(team.id)
        const capacity = roster ? { ...roster.remainingCapacity } : { ...ROSTER_SLOTS }

        // Compute open roster slots (remaining capacity per slot, excluding bench)
        const openSlots: { slot: string; remaining: number }[] = []
        for (const slot of SLOT_ORDER) {
          if (slot === 'BE') continue
          if ((capacity[slot] || 0) > 0) {
            openSlots.push({ slot, remaining: capacity[slot] })
          }
        }

        // Compute weakest 3 categories (starters full, bench weighted by player type)
        const totals: Record<string, number> = {}
        for (const cat of ALL_CATS) totals[cat.key] = 0
        if (roster) {
          for (const p of roster.starters) {
            for (const cat of ALL_CATS) {
              totals[cat.key] += ((p as unknown as Record<string, number>)[cat.key] ?? 0)
            }
          }
          for (const p of roster.bench) {
            const bc = p.player_type === 'pitcher' ? PITCHER_BENCH_CONTRIBUTION : HITTER_BENCH_CONTRIBUTION
            for (const cat of ALL_CATS) {
              totals[cat.key] += ((p as unknown as Record<string, number>)[cat.key] ?? 0) * bc
            }
          }
        }
        const weakCats = ALL_CATS
          .map(c => ({ key: c.key, label: c.label, value: totals[c.key] }))
          .sort((a, b) => a.value - b.value)
          .slice(0, 3)

        // Picks until their next turn
        const nextPickIn = getPicksUntilNextTurn(currentPickIndex, pickSchedule.length > 0 ? pickSchedule : draftOrder, team.id)

        return {
          teamId: team.id,
          teamName: team.name,
          pickCount: roster ? roster.starters.length + roster.bench.length : 0,
          openSlots,
          weakCats,
          nextPickIn,
        }
      })
      .sort((a, b) => a.nextPickIn - b.nextPickIn)
  }, [myTeamId, leagueTeams, teamRosters, currentPickIndex, pickSchedule, draftOrder])

  // ── Projected standings ──
  const projectedStandingsData = useMemo((): ProjectedStanding[] => {
    if (teamCategories.rows.length < 2 || pickSchedule.length === 0) return []
    const availablePlayers = allPlayers
      .filter(p => !draftedIds.has(p.mlb_id))
      .map(p => {
        const pd = p as unknown as Record<string, number>
        const zscores: Record<string, number> = {}
        const stats: Record<string, number> = {}
        for (const cat of ALL_CATS) {
          zscores[cat.key] = pd[cat.key] ?? 0
          stats[cat.projKey] = pd[cat.projKey] ?? 0
        }
        stats['proj_pa'] = pd.proj_pa ?? 0
        stats['proj_ip'] = pd.proj_ip ?? 0
        return { mlb_id: p.mlb_id, zscores, stats }
      })

    const remainingStarters = new Map<number, number>()
    for (const team of leagueTeams) {
      const roster = teamRosters.get(team.id)
      const filled = roster ? roster.starters.length : 0
      remainingStarters.set(team.id, Math.max(0, STARTER_SLOT_COUNT - filled))
    }

    return projectStandings(
      teamCategories.rows,
      availablePlayers,
      ALL_CATS,
      remainingStarters
    )
  }, [teamCategories, allPlayers, draftedIds, leagueTeams, teamRosters])

  const handleSort = useCallback((key: typeof sortKey) => {
    if (sortKey === key) {
      setSortAsc(prev => !prev)
    } else {
      setSortKey(key)
      // Sensible defaults: descending for value/score, ascending for others
      setSortAsc(key !== 'value' && key !== 'score' && key !== 'avail')
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
        case 'avail':
          cmp = (availabilityMap.get(a.mlb_id) ?? -1) - (availabilityMap.get(b.mlb_id) ?? -1)
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
  }, [available, sortKey, sortAsc, draftScoreMap, vonaMap, recalcData, availabilityMap])

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
      <div className="max-w-7xl mx-auto px-3 sm:px-6 py-6">
        <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
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
          <div className="flex gap-2">
            <button
              onClick={resetDraft}
              className="px-4 py-2 text-xs font-semibold bg-red-950 text-red-400 border border-red-800 rounded-lg hover:bg-red-900 transition-colors"
            >
              Reset Picks
            </button>
          </div>
        </div>

        {/* Draft Toolbar */}
        <div className={`bg-gray-900 rounded-xl border mb-4 p-3 flex flex-wrap items-center gap-2 lg:gap-4 ${isMyTeamOnClock ? 'border-blue-600 shadow-lg shadow-blue-500/10' : 'border-gray-800'}`}>
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

          <button
            onClick={() => setShowPickTrader(!showPickTrader)}
            className={`px-3 py-1.5 text-xs font-semibold border rounded-lg transition-colors ${
              pickTrades.length > 0
                ? 'bg-amber-950 text-amber-400 border-amber-800 hover:bg-amber-900'
                : 'bg-gray-800 text-gray-400 border-gray-700 hover:bg-gray-700 hover:text-gray-200'
            }`}
          >
            Pick Trades{pickTrades.length > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-amber-800 text-amber-200">{pickTrades.length}</span>
            )}
          </button>
        </div>

        {/* Draft Complete Banner */}
        {pickSchedule.length > 0 && currentPickIndex >= pickSchedule.length && (
          <div className="bg-emerald-950/50 border border-emerald-700 rounded-xl mb-4 p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-2xl">&#9989;</span>
              <div>
                <h3 className="text-emerald-300 font-bold text-sm">Draft Complete!</h3>
                <p className="text-emerald-400/70 text-xs mt-0.5">All {pickSchedule.length} picks have been made.</p>
              </div>
            </div>
            <Link
              href="/draft/results"
              className="px-4 py-2 text-sm font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 transition-colors"
            >
              View Results &rarr;
            </Link>
          </div>
        )}

        {/* Draft Order Editor */}
        {showDraftOrder && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-white">Draft Order</h3>
              <button
                onClick={() => {
                  if (confirm('Reset draft order to default? This will also clear pick trades.')) {
                    setDraftOrder(DEFAULT_DRAFT_ORDER)
                    setPickTrades([])
                  }
                }}
                className="px-2.5 py-1 text-[10px] font-semibold bg-gray-800 text-gray-400 border border-gray-700 rounded-md hover:bg-gray-700 hover:text-white transition-colors"
              >
                Reset Order
              </button>
            </div>
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
                          if (pickTrades.length > 0 && !confirm('This will reset all pick trades. Continue?')) return
                          if (pickTrades.length > 0) setPickTrades([])
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
                          if (pickTrades.length > 0 && !confirm('This will reset all pick trades. Continue?')) return
                          if (pickTrades.length > 0) setPickTrades([])
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

        {/* Pick Trade Grid */}
        {showPickTrader && pickSchedule.length > 0 && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-white">Pick Trades</h3>
              {pickTrades.length > 0 && (
                <button
                  onClick={() => {
                    if (confirm('Reset all pick trades?')) {
                      setPickTrades([])
                      setPickSchedule(generateSnakeSchedule(draftOrder))
                    }
                  }}
                  className="px-2.5 py-1 text-[10px] font-semibold bg-red-950 text-red-400 border border-red-800 rounded-lg hover:bg-red-900 transition-colors"
                >
                  Reset Trades
                </button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-gray-800">
                    <th className="px-1.5 py-1 text-left text-gray-500 font-semibold w-16">Round</th>
                    {Array.from({ length: draftOrder.length }, (_, i) => (
                      <th key={i} className="px-1 py-1 text-center text-gray-500 font-semibold">{i + 1}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const numTeams = draftOrder.length
                    const totalPicks = pickSchedule.length
                    const numRounds = Math.ceil(totalPicks / numTeams)
                    // Build set of traded pick indices
                    const tradedIndices = new Set(pickTrades.map(t => t.pickIndex))
                    // Build keeper pick index → keeper info map
                    const keeperAtIndex = new Map<number, LeagueKeeperEntry>()
                    for (const k of leagueKeepersData) {
                      const idx = keeperPickIndexFromSchedule(k.teamId, k.roundCost, pickSchedule, numTeams)
                      if (idx >= 0) keeperAtIndex.set(idx, k)
                    }

                    return Array.from({ length: numRounds }, (_, round) => {
                      const isSupplemental = round >= 25
                      return (
                        <tr key={round} className="border-b border-gray-800/50">
                          <td className="px-1.5 py-1 font-semibold text-gray-400">
                            {isSupplemental ? `S${round - 24}` : round + 1}
                          </td>
                          {Array.from({ length: numTeams }, (_, pos) => {
                            const pickIdx = round * numTeams + pos
                            if (pickIdx >= totalPicks) return <td key={pos} />
                            const teamId = pickSchedule[pickIdx]
                            const isPast = pickIdx < currentPickIndex
                            const isKeeper = keeperAtIndex.has(pickIdx)
                            const isTraded = tradedIndices.has(pickIdx)
                            const canTrade = !isPast && !isKeeper && pickIdx >= currentPickIndex

                            return (
                              <td key={pos} className="px-0.5 py-0.5 text-center">
                                {canTrade ? (
                                  <select
                                    value={teamId}
                                    onChange={(e) => {
                                      const newTeamId = parseInt(e.target.value)
                                      if (newTeamId === teamId) return
                                      const allTeamIds = leagueTeams.map(t => t.id)
                                      const { schedule, trade } = tradePickInSchedule(pickSchedule, pickIdx, newTeamId, allTeamIds)
                                      setPickSchedule(schedule)
                                      setPickTrades(prev => [...prev, trade])
                                    }}
                                    className={`w-full text-[10px] font-bold rounded px-0.5 py-0.5 border cursor-pointer focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                                      isTraded
                                        ? 'bg-amber-950 text-amber-300 border-amber-700'
                                        : 'bg-gray-800 text-gray-300 border-gray-700 hover:border-gray-500'
                                    }`}
                                  >
                                    {leagueTeams.map(t => (
                                      <option key={t.id} value={t.id}>{getTeamAbbrev(t.id)}</option>
                                    ))}
                                  </select>
                                ) : (
                                  <span className={`inline-block w-full rounded px-1 py-0.5 text-[10px] font-bold ${
                                    isPast ? 'text-gray-600 bg-gray-800/30' :
                                    isKeeper ? 'text-amber-400 bg-amber-950/40 border border-amber-800/30' :
                                    isTraded ? 'text-amber-300 bg-amber-950' :
                                    'text-gray-400 bg-gray-800/50'
                                  }`}>
                                    {getTeamAbbrev(teamId)}
                                    {isKeeper && <span className="text-[7px] ml-0.5">K</span>}
                                  </span>
                                )}
                              </td>
                            )
                          })}
                        </tr>
                      )
                    })
                  })()}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
          {/* Mobile tab switcher */}
          <div className="col-span-full lg:hidden sticky top-0 z-20 bg-gray-950 pb-2 -mt-1">
            <div className="flex rounded-lg bg-gray-900 border border-gray-800 p-0.5">
              <button
                onClick={() => setMobileTab('board')}
                className={`flex-1 py-2 text-xs font-semibold rounded-md transition-colors ${
                  mobileTab === 'board'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Board
              </button>
              <button
                onClick={() => setMobileTab('info')}
                className={`flex-1 py-2 text-xs font-semibold rounded-md transition-colors ${
                  mobileTab === 'info'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Info
              </button>
            </div>
          </div>

          {/* Main board */}
          <div className={`lg:col-span-3 ${mobileTab === 'board' ? '' : 'hidden'} lg:!block`}>
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
                      <th className="px-2 lg:px-3 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider w-20 lg:w-28">Draft</th>
                      <DraftTh label="#" field="rank" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="left" className="w-14" />
                      {hasAdpData && (
                        <DraftTh label="ADP" field="adp" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="right" className="w-16" />
                      )}
                      {myTeamId != null && hasAdpData && (
                        <DraftTh label="Avl%" field="avail" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="right" className="w-14" />
                      )}
                      <DraftTh label="Player" field="name" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="left" />
                      <DraftTh label="Pos" field="pos" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="left" className="w-24" />
                      <DraftTh label="Team" field="team" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} align="left" className="hidden lg:table-cell" />
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
                        className="w-20 lg:w-28"
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {displayList.flatMap((p, idx) => {
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
                      const needSlots = isDrafted ? [] : getEligibleSlots(p).filter((s) => s !== 'BE' && (rosterState.remainingCapacity[s] || 0) > 0)
                      const fillsNeed = needSlots.length > 0

                      // Tier separator: only when sorted by value (the ordering where tiers are contiguous)
                      const rows: React.ReactNode[] = []
                      if (!isDrafted && idx > 0 && !showDrafted && sortKey === 'value') {
                        const prevPlayer = displayList[idx - 1]
                        const prevTier = playerTiers.get(prevPlayer?.mlb_id)
                        const curTier = playerTiers.get(p.mlb_id)
                        if (prevTier != null && curTier != null && curTier !== prevTier) {
                          const colSpan = 7 + (hasAdpData ? 1 : 0) + (myTeamId != null && hasAdpData ? 1 : 0)
                          rows.push(
                            <tr key={`tier-${curTier}`} className="bg-indigo-950/30 border-y border-indigo-800/40">
                              <td colSpan={colSpan} className="px-3 py-1 text-center">
                                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-900/60 text-indigo-300 border border-indigo-700/50">
                                  TIER {curTier}
                                </span>
                                {tierUrgency.has(curTier) && (
                                  <span className="ml-2 px-2 py-0.5 rounded text-[10px] font-bold bg-red-900/60 text-red-300 border border-red-700/50 animate-pulse">
                                    END OF TIER
                                  </span>
                                )}
                              </td>
                            </tr>
                          )
                        }
                      }

                      // Recommendation zone divider: when sorted by score, separate in-zone from out-of-zone
                      if (!isDrafted && idx > 0 && !showDrafted && sortKey === 'score') {
                        const prevPlayer = displayList[idx - 1]
                        const prevInZone = !draftedIds.has(prevPlayer?.mlb_id) && (scoreRankMap.map.get(prevPlayer?.mlb_id)?.inZone ?? false)
                        const curInZone = scoreRankMap.map.get(p.mlb_id)?.inZone ?? false
                        if (prevInZone && !curInZone) {
                          const colSpan = 7 + (hasAdpData ? 1 : 0) + (myTeamId != null && hasAdpData ? 1 : 0)
                          rows.push(
                            <tr key="zone-divider" className="bg-gray-800/30 border-y border-gray-700/40">
                              <td colSpan={colSpan} className="px-3 py-1 text-center">
                                <span className="text-[10px] font-medium text-gray-500 tracking-wider">
                                  — below recommendation line —
                                </span>
                              </td>
                            </tr>
                          )
                        }
                      }

                      rows.push(
                        <tr key={p.mlb_id} className={`${rowBg} hover:bg-gray-800/80 transition-colors border-b border-gray-800/50`}>
                          <td className="px-2 lg:px-3 py-1.5">
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
                                className={`px-2 lg:px-3 py-1 text-[10px] rounded-md font-bold uppercase tracking-wide transition-all ${
                                  isMyTeamOnClock
                                    ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20 hover:bg-blue-500'
                                    : 'bg-gray-800 text-gray-300 border border-gray-700 hover:bg-gray-700'
                                }`}
                              >
                                Draft
                              </button>
                            )}
                          </td>
                          <td className="px-2 lg:px-3 py-1.5 text-gray-500 font-mono text-xs tabular-nums">{p.overall_rank}</td>
                          {hasAdpData && (
                            <td className="px-2 lg:px-3 py-1.5 text-right">
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
                          {myTeamId != null && hasAdpData && (
                            <td className="px-2 lg:px-3 py-1.5 text-right">
                              {!isDrafted && (() => {
                                const avail = availabilityMap.get(p.mlb_id)
                                if (avail == null) return <span className="text-xs text-gray-700">--</span>
                                const pct = Math.round(avail * 100)
                                const color = pct >= 80 ? 'text-emerald-400' : pct >= 50 ? 'text-yellow-400' : pct >= 20 ? 'text-orange-400' : 'text-red-400'
                                return <span className={`text-xs font-bold tabular-nums ${color}`}>{pct}%</span>
                              })()}
                            </td>
                          )}
                          <td className="px-2 lg:px-3 py-1.5">
                            <Link href={`/player/${p.mlb_id}`} className="font-medium text-white hover:text-blue-400 transition-colors text-sm">
                              {p.full_name}
                            </Link>
                          </td>
                          <td className="px-2 lg:px-3 py-1.5">
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
                          <td className="px-2 lg:px-3 py-1.5 text-gray-400 text-sm hidden lg:table-cell">{p.team}</td>
                          <td className="px-2 lg:px-3 py-1.5 text-right">
                            {(() => {
                              const value = getPlayerValue(p)
                              return (
                                <span className={`inline-block font-bold tabular-nums text-xs ${value > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {value > 0 ? '+' : ''}{value.toFixed(1)}
                                </span>
                              )
                            })()}
                          </td>
                          <td className="px-2 lg:px-3 py-1.5 text-right">
                            {!isDrafted && (() => {
                              const ds = draftScoreMap.get(p.mlb_id)
                              const vona = vonaMap.get(p.mlb_id)
                              const showScore = hasAdpData && myTeamId != null

                              if (showScore && ds) {
                                const rankInfo = scoreRankMap.map.get(p.mlb_id)
                                const inZone = rankInfo?.inZone ?? false
                                return (
                                  <div className="flex items-center justify-end gap-1.5">
                                    {inZone && rankInfo && (
                                      <span className="border-l-2 border-emerald-500 pl-1.5 text-[10px] font-bold text-white tabular-nums">
                                        #{rankInfo.rank}
                                      </span>
                                    )}
                                    <span className={`font-bold tabular-nums text-xs ${inZone ? 'text-purple-400' : 'text-gray-600'}`}>
                                      {ds.score.toFixed(1)}
                                    </span>
                                  </div>
                                )
                              }

                              // Fallback: VONA display
                              if (vona == null) return <span className="text-xs text-gray-700">--</span>
                              const opacity = Math.min(1, 0.3 + (vona / 3) * 0.7)
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
                      return rows
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Sidebar */}
          <div className={`lg:col-span-1 ${mobileTab === 'info' ? '' : 'hidden'} lg:!block`}>
            <div className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] overflow-y-auto space-y-4">

              {/* Suggestions */}
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

              {/* Draft Log */}
              {pickLog.length > 0 && (
                <div className="bg-gray-900 rounded-xl border border-gray-800">
                  <div className="px-4 py-3 border-b border-gray-800">
                    <h2 className="font-bold text-white text-sm">Draft Log</h2>
                    <div className="text-[11px] text-gray-500 mt-0.5">{pickLog.length} picks</div>
                  </div>
                  <div className="px-2 py-2 max-h-[200px] overflow-y-auto space-y-0.5" ref={(el) => { if (el) el.scrollTop = el.scrollHeight }}>
                    {pickLog.map((entry, i) => {
                      const player = allPlayers.find(pl => pl.mlb_id === entry.mlbId)
                      if (!player) return null
                      const numTeams = draftOrder.length || 10
                      const round = Math.floor(entry.pickIndex / numTeams) + 1
                      const pickInRound = (entry.pickIndex % numTeams) + 1
                      const isMyTeamPick = entry.teamId === myTeamId
                      const value = getPlayerValue(player)
                      const pos = getPositions(player)[0]
                      return (
                        <div
                          key={`${entry.pickIndex}-${entry.mlbId}`}
                          className={`flex items-center gap-1.5 py-1 px-2 rounded text-[11px] ${
                            i === pickLog.length - 1 ? 'bg-gray-800/80 ring-1 ring-gray-700' : ''
                          } ${isMyTeamPick ? 'text-blue-300' : 'text-gray-400'}`}
                        >
                          <span className="font-mono text-[10px] text-gray-500 w-8 shrink-0 tabular-nums">{round}.{String(pickInRound).padStart(2, '0')}</span>
                          <span className={`font-bold text-[10px] w-9 shrink-0 ${isMyTeamPick ? 'text-blue-400' : 'text-gray-500'}`}>{getTeamAbbrev(entry.teamId)}</span>
                          <span className="truncate flex-1">{player.full_name}</span>
                          <span className={`text-[9px] font-bold ${posColor[pos] ? 'text-gray-500' : ''}`}>({pos})</span>
                          <span className={`text-[10px] font-bold tabular-nums shrink-0 ${value > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {value > 0 ? '+' : ''}{value.toFixed(1)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Section 3: Draft Comparison Heatmap */}
              {teamCategories.rows.length > 0 && (
                <div className="bg-gray-900 rounded-xl border border-gray-800">
                  <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
                    <div>
                      <h2 className="font-bold text-white text-sm">Draft Comparison</h2>
                      <div className="text-[11px] text-gray-500 mt-0.5">
                        {teamCategories.rows.length} teams &middot; {showProjected ? 'Projected' : 'Current'} stats
                      </div>
                    </div>
                    {projectedStandingsData.length > 0 && (
                      <div className="flex rounded-lg border border-gray-700 overflow-hidden">
                        <button
                          onClick={() => setShowProjected(false)}
                          className={`px-2 py-1 text-[10px] font-semibold transition-colors ${!showProjected ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}
                        >
                          Current
                        </button>
                        <button
                          onClick={() => setShowProjected(true)}
                          className={`px-2 py-1 text-[10px] font-semibold transition-colors ${showProjected ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}
                        >
                          Projected
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[10px]">
                      <thead>
                        <tr className="border-b border-gray-800">
                          <th className="px-2 py-1.5 text-left text-gray-500 font-semibold">Team</th>
                          {ALL_CATS.map((cat) => (
                            <th key={cat.key} className="px-1 py-1.5 text-center text-gray-500 font-semibold">{cat.label}</th>
                          ))}
                          <th className="px-2 py-1.5 text-right text-gray-500 font-semibold" title="Expected weekly wins">E(W)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(() => {
                          if (showProjected && projectedStandingsData.length > 0) {
                            // Use pre-computed projected ranks from projectedStandingsData
                            const projN = projectedStandingsData.length

                            return [...projectedStandingsData]
                              .sort((a, b) => b.projectedWins - a.projectedWins)
                              .map(standing => {
                                const isMyRow = standing.teamId === myTeamId
                                return (
                                  <tr
                                    key={standing.teamId}
                                    className={`border-b border-gray-800/50 ${isMyRow ? 'bg-blue-950/30' : ''}`}
                                  >
                                    <td className={`px-2 py-1 font-semibold truncate max-w-[80px] ${isMyRow ? 'text-blue-400 border-l-2 border-l-blue-500' : 'text-gray-300'}`}>
                                      {standing.teamName.length > 12 ? getTeamAbbrev(standing.teamId) : standing.teamName}
                                      {isMyRow && standing.overallRank > 0 && (
                                        <span className="ml-1 text-[8px] text-blue-300">#{standing.overallRank}</span>
                                      )}
                                    </td>
                                    {ALL_CATS.map((cat) => {
                                      const val = standing.projectedStatTotals[cat.projKey] ?? 0
                                      const rank = standing.projectedRanks[cat.key] ?? projN
                                      const heatColor = getHeatColor(rank, projN)
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
                                      {standing.projectedWins.toFixed(1)}
                                    </td>
                                  </tr>
                                )
                              })
                          }

                          // Current view — projected stats sorted by expected wins
                          return teamCategories.rows.map((row) => {
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
                          })
                        })()}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Opponent Needs */}
              {opponentNeeds.length > 0 && (
                <div className="bg-gray-900 rounded-xl border border-gray-800">
                  <div className="px-4 py-3 border-b border-gray-800">
                    <h2 className="font-bold text-white text-sm">Opponent Needs</h2>
                    <div className="text-[11px] text-gray-500 mt-0.5">Teams picking soonest</div>
                  </div>
                  <div className="px-3 py-2 space-y-2">
                    {opponentNeeds.slice(0, 4).map((opp, i) => (
                      <div key={opp.teamId} className="py-1.5 px-2 rounded-lg bg-gray-800/30">
                        <div className="flex items-center gap-1.5 mb-1">
                          {opp.nextPickIn <= 1 && (
                            <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-orange-900/60 text-orange-300 border border-orange-700/50 leading-none">
                              NEXT
                            </span>
                          )}
                          <span className="text-xs font-bold text-white">{opp.teamName}</span>
                          <span className="text-[10px] text-gray-500 ml-auto">({opp.pickCount}/25 picks)</span>
                        </div>
                        {opp.openSlots.length > 0 && (
                          <div className="flex flex-wrap gap-1 mb-1">
                            <span className="text-[9px] text-gray-500">Need:</span>
                            {opp.openSlots.map(s => (
                              <span key={s.slot} className="px-1 py-0.5 rounded text-[9px] font-bold bg-gray-700/60 text-gray-300">
                                {s.slot}{s.remaining > 1 ? ` x${s.remaining}` : ''}
                              </span>
                            ))}
                          </div>
                        )}
                        {opp.weakCats.length > 0 && (
                          <div className="text-[10px] text-gray-500">
                            Weak: {opp.weakCats.map(c => (
                              <span key={c.key} className="mr-2">
                                <span className="text-gray-400">{c.label}</span>{' '}
                                <span className={`font-bold ${c.value >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {c.value > 0 ? '+' : ''}{c.value.toFixed(1)}
                                </span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

            </div>
          </div>
        </div>
      </div>
    </main>
  )
}

// ── Sortable table header for draft board ──
type DraftSortKey = 'rank' | 'adp' | 'avail' | 'name' | 'pos' | 'team' | 'value' | 'score'

function DraftTh({ label, field, sortKey, sortAsc, onSort, align = 'left', className = '', children }: {
  label: string; field: DraftSortKey; sortKey: DraftSortKey; sortAsc: boolean;
  onSort: (k: DraftSortKey) => void; align?: 'left' | 'right'; className?: string; children?: React.ReactNode
}) {
  const active = sortKey === field
  return (
    <th
      className={`px-2 lg:px-3 py-2.5 ${align === 'right' ? 'text-right' : 'text-left'} text-[11px] font-semibold uppercase tracking-wider cursor-pointer select-none transition-colors whitespace-nowrap ${
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

