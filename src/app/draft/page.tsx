'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import Link from 'next/link'
import { getDraftBoard, recalculateDraftValues, RankedPlayer } from '@/lib/valuations-api'

// ── Position filter buttons ──
const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP']

// ── Position badge colors ──
const posColor: Record<string, string> = {
  C: 'bg-blue-500', '1B': 'bg-amber-500', '2B': 'bg-orange-500', '3B': 'bg-purple-500',
  SS: 'bg-red-500', OF: 'bg-emerald-500', LF: 'bg-emerald-500', CF: 'bg-emerald-500',
  RF: 'bg-emerald-500', DH: 'bg-gray-500', SP: 'bg-sky-500', RP: 'bg-pink-500', P: 'bg-teal-500',
  UTIL: 'bg-gray-500',
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

function makeDefaultTeams(n: number): DraftTeam[] {
  return Array.from({ length: n }, (_, i) => ({ id: i + 1, name: `Team ${i + 1}` }))
}

// ── Snake order helper ──
function getActiveTeamId(pickIndex: number, order: number[]): number {
  if (order.length === 0) return -1
  const numTeams = order.length
  const round = Math.floor(pickIndex / numTeams)
  const posInRound = pickIndex % numTeams
  // Snake: even rounds go forward, odd rounds go backward
  return round % 2 === 0 ? order[posInRound] : order[numTeams - 1 - posInRound]
}

// ── Types ──
interface DraftTeam { id: number; name: string }

interface DraftState {
  picks: [number, number][]  // [mlbId, teamId][]
  myTeamId: number | null
  draftOrder: number[]
  currentPickIndex: number
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

  // ── Team-aware draft state ──
  const [leagueTeams, setLeagueTeams] = useState<DraftTeam[]>([])
  const [draftPicks, setDraftPicks] = useState<Map<number, number>>(new Map()) // mlb_id → teamId
  const [myTeamId, setMyTeamId] = useState<number | null>(null)
  const [draftOrder, setDraftOrder] = useState<number[]>([])
  const [currentPickIndex, setCurrentPickIndex] = useState(0)
  const [showDraftOrder, setShowDraftOrder] = useState(false)
  const [overrideTeam, setOverrideTeam] = useState<number | null>(null)

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
        const state = JSON.parse(saved)
        // New format
        if (state.picks) {
          setDraftPicks(new Map(state.picks))
          setMyTeamId(state.myTeamId ?? null)
          setDraftOrder(state.draftOrder ?? [])
          setCurrentPickIndex(state.currentPickIndex ?? 0)
        }
        // Old format migration
        else if (state.drafted || state.myPicks) {
          const picks = new Map<number, number>()
          const oldMyPicks = new Set<number>(state.myPicks || [])
          for (const id of (state.drafted || [])) {
            if (oldMyPicks.has(id)) {
              picks.set(id, 0) // assign to team 0 (will be re-mapped when myTeamId is set)
            } else {
              picks.set(id, -1) // unknown team
            }
          }
          setDraftPicks(picks)
        }
      }
    } catch {}
  }, [])

  // ── Load teams from ESPN league ──
  useEffect(() => {
    fetch('/api/leagues').then(r => r.json()).then((leagues: { id: string }[]) => {
      if (leagues.length > 0) {
        fetch(`/api/leagues/${leagues[0].id}/teams`).then(r => r.json()).then((data: { teams: { externalId: string; name: string }[] }) => {
          const teams = data.teams.map(t => ({ id: parseInt(t.externalId), name: t.name }))
          setLeagueTeams(teams)
          // Only set draft order if not already restored from localStorage
          setDraftOrder(prev => prev.length > 0 ? prev : teams.map(t => t.id))
        })
      }
    }).catch(() => {})
  }, [])

  // ── Fallback to generic teams if no league loaded ──
  useEffect(() => {
    // Wait a tick for league load to complete
    const timer = setTimeout(() => {
      setLeagueTeams(prev => {
        if (prev.length > 0) return prev
        const defaults = makeDefaultTeams(DEFAULT_NUM_TEAMS)
        setDraftOrder(o => o.length > 0 ? o : defaults.map(t => t.id))
        return defaults
      })
    }, 1500)
    return () => clearTimeout(timer)
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

  // ── Save state to localStorage ──
  useEffect(() => {
    if (allPlayers.length > 0) {
      const state: DraftState = {
        picks: [...draftPicks.entries()],
        myTeamId,
        draftOrder,
        currentPickIndex,
      }
      localStorage.setItem('draftState', JSON.stringify(state))
    }
  }, [draftPicks, myTeamId, draftOrder, currentPickIndex, allPlayers.length])

  // ── Draft actions ──
  const draftPlayer = useCallback((mlbId: number) => {
    const teamId = overrideTeam ?? getActiveTeamId(currentPickIndex, draftOrder)
    setDraftPicks(prev => new Map(prev).set(mlbId, teamId))
    setCurrentPickIndex(prev => prev + 1)
    setOverrideTeam(null)
  }, [currentPickIndex, draftOrder, overrideTeam])

  const undoLastPick = useCallback(() => {
    if (currentPickIndex <= 0 && draftPicks.size === 0) return
    // Find the last pick: the entry that was made at currentPickIndex - 1
    // We go by the last entry in the map (insertion order)
    const entries = [...draftPicks.entries()]
    if (entries.length === 0) return
    const [lastMlbId] = entries[entries.length - 1]
    setDraftPicks(prev => {
      const next = new Map(prev)
      next.delete(lastMlbId)
      return next
    })
    setCurrentPickIndex(prev => Math.max(0, prev - 1))
  }, [currentPickIndex, draftPicks])

  const undoPick = useCallback((mlbId: number) => {
    setDraftPicks(prev => {
      const next = new Map(prev)
      next.delete(mlbId)
      return next
    })
    // Don't change currentPickIndex for individual undo — only last pick undo adjusts it
  }, [])

  const resetDraft = () => {
    if (confirm('Reset all draft picks?')) {
      setDraftPicks(new Map())
      setCurrentPickIndex(0)
      setRecalcData(null)
      setOverrideTeam(null)
      localStorage.removeItem('draftState')
    }
  }

  const handleRecalculate = async () => {
    if (draftedIds.size === 0) return
    setRecalculating(true)
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
  }

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
      .filter((p) => p.adp_diff != null && p.adp_diff > 10)
      .sort((a, b) => (b.adp_diff ?? 0) - (a.adp_diff ?? 0))
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
    ? [...available, ...drafted].sort((a, b) => a.overall_rank - b.overall_rank)
    : available

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
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleRecalculate}
              disabled={recalculating || draftedIds.size === 0}
              className="px-4 py-2 text-xs font-semibold bg-indigo-950 text-indigo-400 border border-indigo-800 rounded-lg hover:bg-indigo-900 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {recalculating && (
                <span className="inline-block w-3 h-3 border-2 border-indigo-600 border-t-indigo-300 rounded-full animate-spin" />
              )}
              Recalculate Values
            </button>
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
            onClick={() => setShowDraftOrder(!showDraftOrder)}
            className="px-3 py-1.5 text-xs font-semibold bg-gray-800 text-gray-400 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-gray-200 transition-colors"
          >
            Draft Order
          </button>
        </div>

        {/* Draft Order Editor */}
        {showDraftOrder && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 mb-4 p-4">
            <h3 className="text-sm font-bold text-white mb-3">Draft Order (Round 1)</h3>
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
                      <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider w-14">#</th>
                      <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Player</th>
                      <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider w-24">Pos</th>
                      <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Team</th>
                      <th className="px-3 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase tracking-wider w-20">
                        <div className="flex items-center justify-end gap-1">
                          Value
                          {recalcData && (
                            <span className="text-[8px] px-1 py-0.5 rounded bg-indigo-900 text-indigo-300 font-bold normal-case tracking-normal">Dyn</span>
                          )}
                        </div>
                      </th>
                      <th className="px-3 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase tracking-wider w-16">VONA</th>
                      {hasAdpData && (
                        <th className="px-3 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase tracking-wider w-16">ADP</th>
                      )}
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
                                <button
                                  onClick={() => undoPick(p.mlb_id)}
                                  className="text-gray-600 hover:text-gray-300 text-xs transition-colors"
                                  title="Undo pick"
                                >
                                  &#10005;
                                </button>
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
                              const vona = vonaMap.get(p.mlb_id)
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
                          {hasAdpData && (
                            <td className="px-3 py-1.5 text-right">
                              {p.espn_adp != null ? (
                                <div className="flex items-center justify-end gap-1">
                                  <span className="text-xs text-gray-500 tabular-nums">{Math.round(p.espn_adp)}</span>
                                  {p.adp_diff != null && Math.abs(p.adp_diff) > 5 && (
                                    <span className={`text-[10px] ${p.adp_diff > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                      {p.adp_diff > 0 ? '\u25B2' : '\u25BC'}
                                    </span>
                                  )}
                                </div>
                              ) : (
                                <span className="text-xs text-gray-700">--</span>
                              )}
                            </td>
                          )}
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
                            +{Math.round(p.adp_diff!)}
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
