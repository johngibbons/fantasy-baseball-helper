// ── Draft Results Engine: post-draft analysis computations ──

import type { RankedPlayer } from './valuations-api'
import type { CatDef } from './draft-categories'
import { ALL_CATS } from './draft-categories'
import type { CategoryAnalysis } from './draft-optimizer'
import type { RosterResult } from './roster-optimizer'
import { getPositions } from './roster-optimizer'

// ── Draft Grade ──

export interface DraftGrade {
  letter: string
  description: string
  rank: number
  numTeams: number
}

export function computeDraftGrade(myTeamRank: number, numTeams: number): DraftGrade {
  const gradeScale: [number, string, string][] = [
    [1, 'A+', 'Dominant draft — projected league champion'],
    [2, 'A',  'Excellent draft — strong contender'],
    [3, 'A-', 'Very good draft — solidly in the top tier'],
    [4, 'B+', 'Good draft — playoff-caliber roster'],
    [5, 'B',  'Above average draft — competitive team'],
    [6, 'B-', 'Slightly above average — needs some waiver work'],
    [7, 'C+', 'Average draft — middle of the pack'],
    [8, 'C',  'Below average — significant holes to fill'],
    [9, 'D',  'Poor draft — uphill battle ahead'],
    [10, 'F', 'Rough draft — major rebuild needed on waivers'],
  ]

  // For leagues with fewer than 10 teams, scale the grade
  const scaledRank = numTeams >= 10
    ? myTeamRank
    : Math.round((myTeamRank / numTeams) * 10)

  const clamped = Math.max(1, Math.min(10, scaledRank))
  const [, letter, description] = gradeScale[clamped - 1]

  return { letter, description, rank: myTeamRank, numTeams }
}

// ── Pick Analysis ──

export interface PickAnalysis {
  round: number
  pickInRound: number
  overallPick: number
  player: RankedPlayer
  playerRank: number
  adp: number | null
  valueDiff: number     // positive = value, negative = reach
  zScore: number
}

export function analyzeMyPicks(
  pickLog: { pickIndex: number; mlbId: number; teamId: number }[],
  myTeamId: number,
  allPlayers: RankedPlayer[],
  numTeams: number,
): PickAnalysis[] {
  const playerMap = new Map(allPlayers.map(p => [p.mlb_id, p]))
  const myPicks = pickLog.filter(e => e.teamId === myTeamId)

  return myPicks.map(pick => {
    const p = playerMap.get(pick.mlbId)
    if (!p) return null

    const round = Math.floor(pick.pickIndex / numTeams) + 1
    const pickInRound = (pick.pickIndex % numTeams) + 1
    const overallPick = pick.pickIndex + 1

    return {
      round,
      pickInRound,
      overallPick,
      player: p,
      playerRank: p.overall_rank,
      adp: p.espn_adp ?? null,
      valueDiff: overallPick - p.overall_rank,
      zScore: p.total_zscore,
    }
  }).filter((x): x is PickAnalysis => x !== null)
}

// ── Waiver Recommendations ──

export interface WaiverRec {
  player: RankedPlayer
  reason: string
  targetCategory?: string
  positionNeed?: string
}

export function computeWaiverRecommendations(
  undraftedPlayers: RankedPlayer[],
  categoryStandings: CategoryAnalysis[],
  rosterResult: RosterResult,
  limit: number = 10,
): {
  bestAvailable: WaiverRec[]
  categoryTargets: Map<string, WaiverRec[]>
  positionNeeds: WaiverRec[]
} {
  // Best available overall
  const bestAvailable: WaiverRec[] = undraftedPlayers
    .slice(0, limit)
    .map(p => ({ player: p, reason: `Rank #${p.overall_rank}` }))

  // Target categories (strategy = 'target')
  const targetCats = categoryStandings.filter(c => c.strategy === 'target')
  const categoryTargets = new Map<string, WaiverRec[]>()

  for (const cat of targetCats) {
    const catDef = ALL_CATS.find(c => c.key === cat.catKey)
    if (!catDef) continue

    const sorted = [...undraftedPlayers].sort((a, b) => {
      const aVal = (a as unknown as Record<string, number>)[cat.catKey] ?? 0
      const bVal = (b as unknown as Record<string, number>)[cat.catKey] ?? 0
      return bVal - aVal
    })

    categoryTargets.set(cat.label, sorted.slice(0, 3).map(p => ({
      player: p,
      reason: `${cat.label} z-score: ${((p as unknown as Record<string, number>)[cat.catKey] ?? 0).toFixed(2)}`,
      targetCategory: cat.label,
    })))
  }

  // Position needs: unfilled starter slots
  const positionNeeds: WaiverRec[] = []
  const { remainingCapacity } = rosterResult
  const starterSlots = ['C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP', 'P', 'UTIL']

  for (const slot of starterSlots) {
    if ((remainingCapacity[slot] ?? 0) > 0) {
      // Find best undrafted player eligible for this slot
      const eligible = undraftedPlayers.filter(p => {
        const positions = getPositions(p)
        if (slot === 'UTIL') return p.player_type === 'hitter'
        if (slot === 'P') return p.player_type === 'pitcher'
        if (slot === 'OF') return positions.some(pos => ['OF', 'LF', 'CF', 'RF'].includes(pos))
        return positions.includes(slot)
      })

      if (eligible.length > 0) {
        positionNeeds.push({
          player: eligible[0],
          reason: `Best available ${slot}`,
          positionNeed: slot,
        })
      }
    }
  }

  return { bestAvailable, categoryTargets, positionNeeds }
}
