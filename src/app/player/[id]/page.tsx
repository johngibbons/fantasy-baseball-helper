'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { getPlayerDetail, getPlayerStatcast, PlayerDetail, StatcastData } from '@/lib/valuations-api'

const posColor: Record<string, string> = {
  C: 'bg-blue-500', '1B': 'bg-amber-500', '2B': 'bg-orange-500', '3B': 'bg-purple-500',
  SS: 'bg-red-500', OF: 'bg-emerald-500', LF: 'bg-emerald-500', CF: 'bg-emerald-500',
  RF: 'bg-emerald-500', DH: 'bg-gray-500', SP: 'bg-sky-500', RP: 'bg-pink-500', P: 'bg-sky-500',
  TWP: 'bg-violet-500',
}

export default function PlayerDetailPage() {
  const params = useParams()
  const mlbId = Number(params.id)
  const [player, setPlayer] = useState<PlayerDetail | null>(null)
  const [statcast, setStatcast] = useState<StatcastData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!mlbId) return
    Promise.all([
      getPlayerDetail(mlbId),
      getPlayerStatcast(mlbId).catch(() => null),
    ])
      .then(([p, sc]) => {
        setPlayer(p)
        setStatcast(sc)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [mlbId])

  if (loading) {
    return (
      <main className="min-h-screen bg-gray-950">
        <div className="max-w-5xl mx-auto px-6 py-20 text-center text-gray-500">
          <div className="inline-block w-6 h-6 border-2 border-gray-600 border-t-blue-500 rounded-full animate-spin mb-3" />
          <div>Loading player...</div>
        </div>
      </main>
    )
  }

  if (error || !player) {
    return (
      <main className="min-h-screen bg-gray-950">
        <div className="max-w-5xl mx-auto px-6 py-8">
          <div className="bg-red-950 border border-red-800 rounded-xl p-6 text-red-300">
            {error || 'Player not found'}
          </div>
          <Link href="/rankings" className="text-blue-400 hover:text-blue-300 text-sm mt-4 inline-block">
            &larr; Back to Rankings
          </Link>
        </div>
      </main>
    )
  }

  const r = player.ranking
  const isHitter = player.player_type === 'hitter'

  // Classify pitchers as SP/RP using z-score data (matches roster-optimizer logic)
  const displayPosition = player.primary_position === 'P' && r
    ? (r.zscore_qs && r.zscore_qs !== 0 ? 'SP'
       : r.zscore_svhd && r.zscore_svhd !== 0 ? 'RP'
       : 'SP')
    : player.primary_position

  // Detect two-way player: has non-zero z-scores in both hitting AND pitching categories
  const hasHittingZ = r && [r.zscore_r, r.zscore_tb, r.zscore_rbi, r.zscore_sb, r.zscore_obp].some(v => v != null && v !== 0)
  const hasPitchingZ = r && [r.zscore_k, r.zscore_qs, r.zscore_era, r.zscore_whip, r.zscore_svhd].some(v => v != null && v !== 0)
  const isTwoWay = hasHittingZ && hasPitchingZ

  const hitterCats = [
    { label: 'R', value: r?.zscore_r ?? 0 },
    { label: 'TB', value: r?.zscore_tb ?? 0 },
    { label: 'RBI', value: r?.zscore_rbi ?? 0 },
    { label: 'SB', value: r?.zscore_sb ?? 0 },
    { label: 'OBP', value: r?.zscore_obp ?? 0 },
  ]
  const pitcherCats = [
    { label: 'K', value: r?.zscore_k ?? 0 },
    { label: 'QS', value: r?.zscore_qs ?? 0 },
    { label: 'ERA', value: r?.zscore_era ?? 0 },
    { label: 'WHIP', value: r?.zscore_whip ?? 0 },
    { label: 'SVHD', value: r?.zscore_svhd ?? 0 },
  ]

  const categories = isTwoWay
    ? [...hitterCats, ...pitcherCats]
    : isHitter ? hitterCats : pitcherCats

  return (
    <main className="min-h-screen bg-gray-950">
      <div className="max-w-5xl mx-auto px-6 py-6">
        <Link href="/rankings" className="text-blue-400 hover:text-blue-300 text-sm mb-4 inline-flex items-center gap-1">
          <span>&larr;</span> Back to Rankings
        </Link>

        {/* Player header */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-5">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <h1 className="text-3xl font-bold text-white">{player.full_name}</h1>
                <span className={`inline-flex items-center justify-center px-2.5 h-6 rounded-md text-xs font-bold text-white ${posColor[displayPosition] || 'bg-gray-600'}`}>
                  {displayPosition}
                </span>
              </div>
              <p className="text-gray-400">
                {player.team}
                {isTwoWay ? (
                  <span className="text-gray-600">
                    {player.bats && <> &middot; Bats: {player.bats}</>}
                    {player.throws && <> / Throws: {player.throws}</>}
                  </span>
                ) : (isHitter ? player.bats : player.throws) ? (
                  <span className="text-gray-600"> &middot; {isHitter ? 'Bats' : 'Throws'}: {isHitter ? player.bats : player.throws}</span>
                ) : null}
              </p>
            </div>
            {r && (
              <div className="text-right">
                <div className="text-4xl font-black text-white tabular-nums">#{r.overall_rank}</div>
                <div className="text-[11px] text-gray-500 font-semibold uppercase tracking-wider">Overall</div>
                <div className={`text-2xl font-bold mt-1 tabular-nums ${r.total_zscore > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {r.total_zscore > 0 ? '+' : ''}{r.total_zscore.toFixed(2)}
                </div>
                <div className="text-[11px] text-gray-500 font-semibold uppercase tracking-wider">Z-Score</div>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Z-Score breakdown */}
          {r && (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
              <h2 className="text-sm font-bold text-gray-300 uppercase tracking-wider mb-4">Category Z-Scores</h2>
              <div className="space-y-3">
                {categories.map((cat) => {
                  const pct = Math.min(Math.abs(cat.value) / 4 * 100, 100)
                  return (
                    <div key={cat.label} className="flex items-center gap-3">
                      <span className="text-xs font-bold text-gray-400 w-10 text-right">{cat.label}</span>
                      <div className="flex-1 h-7 bg-gray-800 rounded-lg relative overflow-hidden">
                        <div
                          className={`absolute top-0 h-full rounded-lg transition-all ${
                            cat.value >= 0
                              ? 'left-0 bg-gradient-to-r from-emerald-600 to-emerald-500'
                              : 'right-0 bg-gradient-to-l from-red-600 to-red-500'
                          }`}
                          style={{ width: `${pct}%` }}
                        />
                        <div className="absolute inset-0 flex items-center justify-end pr-2">
                          <span className={`text-xs font-bold tabular-nums ${cat.value >= 2 || cat.value <= -2 ? 'text-white' : cat.value > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {cat.value > 0 ? '+' : ''}{cat.value.toFixed(2)}
                          </span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="mt-4 pt-4 border-t border-gray-800 flex justify-between items-center">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Position Rank</span>
                <span className="text-sm font-bold text-white">#{r.position_rank} <span className="text-gray-400">{displayPosition}</span></span>
              </div>
            </div>
          )}

          {/* Projections */}
          {player.projection && (
            <div className={`bg-gray-900 rounded-xl border border-gray-800 p-5 ${isTwoWay ? 'lg:col-span-2' : ''}`}>
              <h2 className="text-sm font-bold text-gray-300 uppercase tracking-wider mb-4">2026 Projections</h2>
              {isTwoWay ? (
                <div className="space-y-4">
                  <div>
                    <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Hitting</div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      <StatBox label="PA" value={player.projection.proj_pa} />
                      <StatBox label="R" value={player.projection.proj_runs} highlight />
                      <StatBox label="TB" value={player.projection.proj_total_bases} highlight />
                      <StatBox label="RBI" value={player.projection.proj_rbi} highlight />
                      <StatBox label="SB" value={player.projection.proj_stolen_bases} highlight />
                      <StatBox label="OBP" value={player.projection.proj_obp} decimal highlight />
                      <StatBox label="HR" value={player.projection.proj_home_runs} />
                      <StatBox label="H" value={player.projection.proj_hits} />
                    </div>
                  </div>
                  <div className="border-t border-gray-800 pt-4">
                    <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Pitching</div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      <StatBox label="IP" value={player.projection.proj_ip} decimal />
                      <StatBox label="K" value={player.projection.proj_pitcher_strikeouts} highlight />
                      <StatBox label="QS" value={player.projection.proj_quality_starts} highlight />
                      <StatBox label="ERA" value={player.projection.proj_era} decimal highlight />
                      <StatBox label="WHIP" value={player.projection.proj_whip} decimal highlight />
                      <StatBox label="SV" value={player.projection.proj_saves} />
                      <StatBox label="HLD" value={player.projection.proj_holds} />
                      <StatBox label="SVHD" value={(player.projection.proj_saves ?? 0) + (player.projection.proj_holds ?? 0)} highlight />
                    </div>
                  </div>
                </div>
              ) : isHitter ? (
                <div className="grid grid-cols-2 gap-3">
                  <StatBox label="PA" value={player.projection.proj_pa} />
                  <StatBox label="R" value={player.projection.proj_runs} highlight />
                  <StatBox label="TB" value={player.projection.proj_total_bases} highlight />
                  <StatBox label="RBI" value={player.projection.proj_rbi} highlight />
                  <StatBox label="SB" value={player.projection.proj_stolen_bases} highlight />
                  <StatBox label="OBP" value={player.projection.proj_obp} decimal highlight />
                  <StatBox label="HR" value={player.projection.proj_home_runs} />
                  <StatBox label="H" value={player.projection.proj_hits} />
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  <StatBox label="IP" value={player.projection.proj_ip} decimal />
                  <StatBox label="K" value={player.projection.proj_pitcher_strikeouts} highlight />
                  <StatBox label="QS" value={player.projection.proj_quality_starts} highlight />
                  <StatBox label="ERA" value={player.projection.proj_era} decimal highlight />
                  <StatBox label="WHIP" value={player.projection.proj_whip} decimal highlight />
                  <StatBox label="SV" value={player.projection.proj_saves} />
                  <StatBox label="HLD" value={player.projection.proj_holds} />
                  <StatBox label="SVHD" value={(player.projection.proj_saves ?? 0) + (player.projection.proj_holds ?? 0)} highlight />
                </div>
              )}
            </div>
          )}

          {/* Statcast Profile */}
          {statcast?.data && (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 lg:col-span-2">
              <h2 className="text-sm font-bold text-gray-300 uppercase tracking-wider mb-4">
                Statcast Profile <span className="text-gray-600 font-normal">({statcast.season})</span>
              </h2>
              {isHitter ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatcastMetric label="Avg Exit Velo" value={statcast.data.avg_exit_velocity} unit="mph" thresholds={[87, 89, 91]} />
                    <StatcastMetric label="Barrel%" value={statcast.data.barrel_pct} unit="%" thresholds={[5, 8, 12]} />
                    <StatcastMetric label="Hard Hit%" value={statcast.data.hard_hit_pct} unit="%" thresholds={[30, 38, 45]} />
                    <StatcastMetric label="Sprint Speed" value={statcast.data.sprint_speed} unit="ft/s" thresholds={[26, 27.5, 29]} />
                  </div>
                  {(statcast.data.xwoba != null && statcast.data.woba != null) && (
                    <div className="bg-gray-800 rounded-lg p-4">
                      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">xwOBA vs wOBA (Luck Adjusted)</div>
                      <div className="flex items-center gap-4">
                        <div className="flex-1">
                          <div className="flex justify-between text-xs mb-1">
                            <span className="text-gray-400">wOBA: {statcast.data.woba.toFixed(3)}</span>
                            <span className={statcast.data.xwoba > statcast.data.woba ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
                              xwOBA: {statcast.data.xwoba.toFixed(3)}
                            </span>
                          </div>
                          <div className="h-3 bg-gray-700 rounded-full relative overflow-hidden">
                            <div className="absolute h-full bg-gray-500 rounded-full" style={{ width: `${Math.min((statcast.data.woba / 0.500) * 100, 100)}%` }} />
                            <div
                              className={`absolute h-full rounded-full ${statcast.data.xwoba > statcast.data.woba ? 'bg-emerald-500' : 'bg-red-500'}`}
                              style={{ width: `${Math.min((statcast.data.xwoba / 0.500) * 100, 100)}%`, opacity: 0.7 }}
                            />
                          </div>
                          {Math.abs(statcast.data.xwoba - statcast.data.woba) > 0.015 && (
                            <div className={`text-xs mt-1 ${statcast.data.xwoba > statcast.data.woba ? 'text-emerald-400' : 'text-red-400'}`}>
                              {statcast.data.xwoba > statcast.data.woba ? 'Underperforming expected — upside' : 'Overperforming expected — regression risk'}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatcastMetric label="xBA" value={statcast.data.xba} decimal thresholds={[0.230, 0.260, 0.290]} />
                    <StatcastMetric label="xSLG" value={statcast.data.xslg} decimal thresholds={[0.350, 0.430, 0.520]} />
                    <StatcastMetric label="Sweet Spot%" value={statcast.data.sweet_spot_pct} unit="%" thresholds={[25, 33, 40]} />
                    <StatcastMetric label="Launch Angle" value={statcast.data.launch_angle} unit="°" />
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatcastMetric label="Whiff%" value={statcast.data.whiff_pct} unit="%" thresholds={[22, 27, 32]} />
                    <StatcastMetric label="CSW%" value={statcast.data.csw_pct} unit="%" thresholds={[26, 29, 32]} />
                    <StatcastMetric label="K%" value={statcast.data.k_pct} unit="%" thresholds={[20, 25, 30]} />
                    <StatcastMetric label="BB%" value={statcast.data.bb_pct} unit="%" thresholds={[10, 8, 6]} invertColor />
                  </div>
                  {(statcast.data.xera != null) && (
                    <div className="bg-gray-800 rounded-lg p-4">
                      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">xERA (Expected ERA)</div>
                      <div className="flex items-center gap-6">
                        <div>
                          <div className={`text-3xl font-black tabular-nums ${statcast.data.xera < 3.50 ? 'text-emerald-400' : statcast.data.xera < 4.50 ? 'text-amber-400' : 'text-red-400'}`}>
                            {statcast.data.xera.toFixed(2)}
                          </div>
                          <div className="text-[10px] text-gray-500 font-semibold uppercase">xERA</div>
                        </div>
                        <div className="text-xs text-gray-400">
                          {statcast.data.xera < 3.00 ? 'Elite' : statcast.data.xera < 3.50 ? 'Excellent' : statcast.data.xera < 4.00 ? 'Above Average' : statcast.data.xera < 4.50 ? 'Average' : 'Below Average'}
                        </div>
                      </div>
                    </div>
                  )}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatcastMetric label="xBA Against" value={statcast.data.xba_against} decimal thresholds={[0.260, 0.240, 0.220]} invertColor />
                    <StatcastMetric label="xwOBA Against" value={statcast.data.xwoba_against} decimal thresholds={[0.330, 0.300, 0.270]} invertColor />
                    <StatcastMetric label="Barrel% Against" value={statcast.data.barrel_pct_against} unit="%" thresholds={[9, 7, 5]} invertColor />
                    <StatcastMetric label="Avg EV Against" value={statcast.data.avg_exit_velocity_against} unit="mph" thresholds={[90, 88, 86]} invertColor />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Batting history */}
          {player.batting_history.length > 0 && (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 lg:col-span-2">
              <h2 className="text-sm font-bold text-gray-300 uppercase tracking-wider mb-4">Batting History</h2>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-800">
                      {['Year','G','PA','R','H','2B','HR','TB','RBI','SB','BB','AVG','OBP','OPS'].map(h => (
                        <th key={h} className="px-3 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wider text-right first:text-left">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {player.batting_history.map((s, idx) => (
                      <tr key={s.season} className={`${idx % 2 === 0 ? 'bg-gray-900' : 'bg-gray-800/30'} border-b border-gray-800/50 hover:bg-gray-800/60 transition-colors`}>
                        <td className="px-3 py-2 text-sm font-bold text-white">{s.season}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.games}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.plate_appearances}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-semibold">{s.runs}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.hits}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.doubles}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.home_runs}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-bold">{s.total_bases}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-semibold">{s.rbi}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-semibold">{s.stolen_bases}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.walks}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{(s.batting_average ?? 0).toFixed(3)}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-bold">{(s.obp ?? 0).toFixed(3)}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{(s.ops ?? 0).toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Pitching history */}
          {player.pitching_history.length > 0 && (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 lg:col-span-2">
              <h2 className="text-sm font-bold text-gray-300 uppercase tracking-wider mb-4">Pitching History</h2>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-800">
                      {['Year','G','GS','IP','W','L','K','QS','ERA','WHIP','SV','HLD','SVHD'].map(h => (
                        <th key={h} className="px-3 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wider text-right first:text-left">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {player.pitching_history.map((s, idx) => (
                      <tr key={s.season} className={`${idx % 2 === 0 ? 'bg-gray-900' : 'bg-gray-800/30'} border-b border-gray-800/50 hover:bg-gray-800/60 transition-colors`}>
                        <td className="px-3 py-2 text-sm font-bold text-white">{s.season}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.games}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.games_started}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.innings_pitched}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.wins}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.losses}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-bold">{s.strikeouts}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.quality_starts}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-bold">{(s.era ?? 0).toFixed(2)}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-bold">{(s.whip ?? 0).toFixed(2)}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.saves}</td>
                        <td className="px-3 py-2 text-sm text-gray-300 text-right tabular-nums">{s.holds}</td>
                        <td className="px-3 py-2 text-sm text-emerald-400 text-right tabular-nums font-bold">{(s.saves ?? 0) + (s.holds ?? 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  )
}

function StatBox({ label, value, decimal, highlight }: { label: string; value: number; decimal?: boolean; highlight?: boolean }) {
  return (
    <div className={`rounded-lg p-3 ${highlight ? 'bg-gray-800 border border-gray-700' : 'bg-gray-800/50'}`}>
      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">{label}</div>
      <div className={`text-xl font-bold mt-0.5 tabular-nums ${highlight ? 'text-white' : 'text-gray-300'}`}>
        {decimal ? (value ?? 0).toFixed(value < 10 ? 3 : 1) : Math.round(value ?? 0)}
      </div>
    </div>
  )
}

function StatcastMetric({ label, value, unit, decimal, thresholds, invertColor }: {
  label: string
  value?: number | null
  unit?: string
  decimal?: boolean
  thresholds?: [number, number, number]  // [poor, avg, elite] or [elite, avg, poor] if invertColor
  invertColor?: boolean
}) {
  if (value == null) return null

  let colorClass = 'text-gray-300'
  if (thresholds) {
    const [t1, t2, t3] = thresholds
    if (invertColor) {
      // Lower is better (e.g., BB%, xBA against)
      colorClass = value <= t3 ? 'text-emerald-400' : value <= t2 ? 'text-emerald-300' : value <= t1 ? 'text-amber-400' : 'text-red-400'
    } else {
      // Higher is better (e.g., EV, barrel%)
      colorClass = value >= t3 ? 'text-emerald-400' : value >= t2 ? 'text-emerald-300' : value >= t1 ? 'text-amber-400' : 'text-red-400'
    }
  }

  const formatted = decimal ? value.toFixed(3) : value.toFixed(1)

  return (
    <div className="bg-gray-800/50 rounded-lg p-3">
      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">{label}</div>
      <div className={`text-lg font-bold mt-0.5 tabular-nums ${colorClass}`}>
        {formatted}{unit && <span className="text-xs text-gray-500 ml-0.5">{unit}</span>}
      </div>
    </div>
  )
}
