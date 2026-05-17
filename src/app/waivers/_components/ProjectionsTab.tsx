'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
import Link from 'next/link'
import FormBadge from '@/components/FormBadge'
import InfoTip from '@/components/InfoTip'
import { SCORE_COMPONENT_COPY } from '@/lib/waiver-symbol-copy'

interface Props {
  selectedLeague: string
  selectedTeam: string
  credentialsOk: boolean | null
}

interface PlayerRef {
  id: number
  name: string
  position: string
  form_level?: 'hot' | 'cool' | 'cold' | 'neutral' | null
}

interface Recommendation {
  rank: number
  add_player: PlayerRef
  drop_player: PlayerRef | null
  delta_expected_wins: number
  suggested_faab_bid: number
  category_impact: Record<string, number>
  category_stat_delta: Record<string, number>
  blended_score?: number
  score_breakdown?: {
    projection_contribution: number
    production_contribution: number
    xwoba_contribution: number
    luck_contribution: number
  }
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
  stream_slot_player: { id: number; name: string; position: string } | null
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

/** First listed position, used for color lookup when eligibility is "2B/SS"-style. */
function primaryPos(p: string): string {
  return (p || '').split('/')[0] || ''
}

/** True if the player is eligible at the requested position. */
function isEligibleAt(p: string, pos: string): boolean {
  const parts = (p || '').split('/').filter(Boolean)
  if (pos === 'OF') return parts.some((x) => ['OF', 'LF', 'CF', 'RF'].includes(x))
  return parts.includes(pos)
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

export default function ProjectionsTab({ selectedLeague, selectedTeam, credentialsOk }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<WaiverResults | null>(null)
  const [posFilter, setPosFilter] = useState('All')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null)
  const [excludeStreamSlot, setExcludeStreamSlot] = useState(true)
  const [includeCrossType, setIncludeCrossType] = useState(false)
  type FormLevel = 'hot' | 'cool' | 'cold' | 'neutral'
  type RosterValueEntry = { z: number; form: FormLevel | null }
  const [rosterValue, setRosterValue] = useState<Record<number, RosterValueEntry>>({})

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
          excludeStreamSlot,
          includeCrossType,
        }),
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || `Error ${response.status}`)
      }

      const data = await response.json()
      console.log('Waiver diagnostics:', data.diagnostics, 'roster_names_debug:', data.roster_names_debug)
      setResults(data)

      // Optional enrichment: fetch roster-health to flag drop candidates who
      // are overperforming their projection (value_z > 0). Failures are
      // non-fatal — the recs table still renders without the warning icon.
      try {
        const rhResp = await fetch('/api/waivers/roster-health', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ leagueId: selectedLeague, teamId: selectedTeam, season: '2026' }),
        })
        if (rhResp.ok) {
          const rhData = await rhResp.json()
          const map: Record<number, RosterValueEntry> = {}
          for (const r of rhData.roster_value || []) {
            if (r.mlb_id != null) map[r.mlb_id] = { z: r.value_z, form: r.form_level ?? null }
          }
          setRosterValue(map)
        }
      } catch {
        // Roster health is optional enrichment; ignore failures silently
      }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch recommendations')
    } finally {
      setLoading(false)
    }
  }

  // Auto-fetch recommendations when all settings (league + team + creds) are
  // available. Runs once per league/team combo. Reset on selection change.
  const autoFetched = useRef<string>('')
  useEffect(() => {
    const key = `${selectedLeague}|${selectedTeam}`
    if (
      selectedLeague &&
      selectedTeam &&
      credentialsOk &&
      autoFetched.current !== key
    ) {
      autoFetched.current = key
      handleFetchRecommendations()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLeague, selectedTeam, credentialsOk])

  // Re-run the waiver query when a toggle flips, but only if we already have
  // data (avoids fetching on mount) and aren't already fetching (avoids
  // overlapping requests on rapid clicks). `results` and `loading` are used as
  // guards and intentionally omitted from deps — including them would cause a
  // re-fetch on every response arrival or loading transition.
  useEffect(() => {
    if (!results || loading) return
    handleFetchRecommendations()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [excludeStreamSlot, includeCrossType])

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
    return results.recommendations.filter((r) => isEligibleAt(r.add_player.position, posFilter))
  }, [results, posFilter])

  return (
    <div>
      {/* Action bar */}
      <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-4 mb-4">
        <div className="flex flex-wrap items-center gap-3">
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
        {selectedLeague && credentialsOk === false && (
          <div className="text-sm text-yellow-400 mt-3">
            ESPN credentials not configured.{' '}
            <Link href="/settings" className="underline hover:text-yellow-300">Set them up in Settings</Link>
            {' '}to use waiver recommendations.
          </div>
        )}
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
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-x-8 gap-y-1 text-xs">
              {rosterBySlot.map(({ slot, players }) => (
                players.map((p, i) => {
                  const isStreamSlot = !!(
                    results.stream_slot_player &&
                    p.mlb_id === results.stream_slot_player.id &&
                    excludeStreamSlot
                  )
                  const rv = p.mlb_id != null ? rosterValue[p.mlb_id] : undefined
                  const zColor = rv === undefined
                    ? 'text-gray-600'
                    : rv.z > 0.5 ? 'text-emerald-400'
                    : rv.z < -0.5 ? 'text-red-400'
                    : 'text-gray-500'
                  return (
                    <div key={`${slot}-${i}`} className="flex items-center gap-1.5 px-1 py-0.5">
                      <span className={`shrink-0 text-[10px] font-mono ${posColors[primaryPos(p.position)] || 'text-gray-500'}`}>
                        {p.position}
                      </span>
                      <div className="flex-1 min-w-0 flex items-center gap-1.5">
                        {p.mlb_id ? (
                          <Link
                            href={`/player/${p.mlb_id}`}
                            className={`truncate hover:underline ${
                              slot === 'IL'
                                ? 'text-gray-600 line-through'
                                : isStreamSlot
                                  ? 'text-gray-500 hover:text-white'
                                  : 'text-gray-300 hover:text-white'
                            }`}
                          >
                            {p.name}
                          </Link>
                        ) : (
                          <span className={`truncate ${slot === 'IL' ? 'text-gray-600 line-through' : 'text-gray-300'}`}>{p.name}</span>
                        )}
                        {isStreamSlot && (
                          <span className="text-[9px] font-bold text-orange-400 bg-orange-500/10 px-1 rounded shrink-0">STREAM</span>
                        )}
                      </div>
                      <div className="flex items-center gap-0.5 w-14 shrink-0 justify-end">
                        <span className="w-4 flex justify-center shrink-0">
                          {rv ? <FormBadge level={rv.form} /> : null}
                        </span>
                        <span className={`text-[10px] font-mono tabular-nums w-9 text-right ${rv ? zColor : 'text-gray-700'}`}>
                          {rv ? (rv.z > 0 ? `+${rv.z.toFixed(2)}` : rv.z.toFixed(2)) : '—'}
                        </span>
                      </div>
                      {slot === 'IL' && (
                        <span className="text-[9px] font-bold text-red-400 bg-red-500/10 px-1 rounded shrink-0">IL</span>
                      )}
                    </div>
                  )
                })
              ))}
            </div>
          </div>

          {/* Recommendation filters */}
          <div className="flex gap-4 mb-2 text-xs">
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={excludeStreamSlot}
                onChange={(e) => setExcludeStreamSlot(e.target.checked)}
                className="accent-blue-500"
              />
              <span className="text-gray-400">
                Exclude stream slot
                {results.stream_slot_player && (
                  <span className="text-gray-500"> ({results.stream_slot_player.name})</span>
                )}
              </span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={includeCrossType}
                onChange={(e) => setIncludeCrossType(e.target.checked)}
                className="accent-blue-500"
              />
              <span className="text-gray-400">Show cross-type swaps</span>
            </label>
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
          <div className="bg-[#161b22] border border-white/[0.06] rounded-lg overflow-x-auto overflow-y-clip">
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
                      <span className={`ml-1.5 text-xs ${posColors[primaryPos(rec.add_player.position)] || 'text-gray-400'}`}>
                        {rec.add_player.position}
                      </span>
                      <span className="ml-1.5">
                        <FormBadge level={rec.add_player.form_level ?? null} />
                      </span>
                      {rec.score_breakdown && (
                        <div className="text-[10px] text-gray-400 mt-0.5 font-mono">
                          <InfoTip content={SCORE_COMPONENT_COPY.projection}>
                            <span>📊 {rec.score_breakdown.projection_contribution.toFixed(2)}</span>
                          </InfoTip>{' '}
                          <InfoTip content={SCORE_COMPONENT_COPY.production}>
                            <span>🔥 {rec.score_breakdown.production_contribution.toFixed(2)}</span>
                          </InfoTip>{' '}
                          <InfoTip content={SCORE_COMPONENT_COPY.xwoba}>
                            <span>🎯 {rec.score_breakdown.xwoba_contribution.toFixed(2)}</span>
                          </InfoTip>{' '}
                          <InfoTip content={SCORE_COMPONENT_COPY.luck}>
                            <span className={rec.score_breakdown.luck_contribution < -0.001 ? 'text-red-400' : ''}>
                              🍀 {rec.score_breakdown.luck_contribution.toFixed(2)}
                            </span>
                          </InfoTip>
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {rec.drop_player?.name ? (
                        <>
                          <Link href={`/player/${rec.drop_player.id}`} className="text-gray-400 hover:underline hover:text-white">{rec.drop_player.name}</Link>
                          <span className={`ml-1.5 text-xs ${posColors[primaryPos(rec.drop_player.position)] || 'text-gray-400'}`}>
                            {rec.drop_player.position}
                          </span>
                          {rosterValue[rec.drop_player.id] !== undefined && rosterValue[rec.drop_player.id].z > 0 && (
                            <InfoTip
                              className="ml-1.5 align-middle"
                              content={`⚠️ Overperforming projection — roster value z = +${rosterValue[rec.drop_player.id].z.toFixed(2)}. This player is currently producing ABOVE their rest-of-season projection, so dropping them may be premature.`}
                            >
                              <span className="text-xs text-amber-400 cursor-help">⚠️</span>
                            </InfoTip>
                          )}
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
  )
}
