'use client'

import { useEffect } from 'react'
import { type CategoryGain, type CategoryAnalysis } from '@/lib/draft-optimizer'
import { type CatDef, HITTING_CATS, PITCHING_CATS, ALL_CATS, posColor } from '@/lib/draft-categories'

// ── Data shape for score detail modal ──

export interface ScoreDetailData {
  // Identity
  mlbId: number
  fullName: string
  positions: string[]
  team: string
  playerType: 'hitter' | 'pitcher'
  overallRank: number
  espnAdp: number | null

  // Final score and components
  finalScore: number
  mcw: number
  vona: number
  urgency: number
  badge: 'NOW' | 'WAIT' | null
  normalizedValue: number
  surplusValue: number
  rosterFit: number
  filledSlots: string[]

  // Formula parameters
  confidence: number
  draftProgress: number
  hasMCW: boolean

  // Bench penalty
  benchPenalty: number
  benchPenaltyReason: string | null

  // Decomposed formula terms
  mcwComponent: number       // mcw * 21.0 * confidence
  vonaComponentHigh: number  // vona * 0.16
  urgencyComponentHigh: number // urgency * 0.02
  rosterFitComponent: number // rosterFit * draftProgress
  highConfidenceTotal: number
  lowConfidenceTotal: number // surplusValue + vona * 0.42 + urgency * 0.55
  blendedScore: number       // before bench penalty

  // Category detail
  categoryGains: CategoryGain[]
  categoryStandings: CategoryAnalysis[]

  // Per-category z-scores (raw and standardized)
  rawZScores: Record<string, number>
  standardizedZScores: Record<string, number>
  catStats: Record<string, { mean: number; stdev: number }>

  // Availability
  availability: number | null
  picksUntilMine: number

  // Replacement context
  replacementLevels: Record<string, number>
}

// ── Helpers ──

function fmt(n: number, decimals = 2): string {
  return n.toFixed(decimals)
}

function pct(n: number): string {
  return `${Math.round(n * 100)}%`
}

function FormulaRow({ label, formula, value, highlight }: {
  label: string; formula: string; value: number; highlight?: boolean
}) {
  return (
    <div className={`flex items-center gap-2 py-0.5 text-[11px] ${highlight ? 'bg-purple-950/20 -mx-2 px-2 rounded' : ''}`}>
      <span className="text-gray-500 w-24 shrink-0">{label}</span>
      <span className="text-gray-400 flex-1 font-mono text-[10px]">{formula}</span>
      <span className={`font-bold tabular-nums w-14 text-right shrink-0 ${
        value > 0 ? 'text-emerald-400' : value < 0 ? 'text-red-400' : 'text-gray-500'
      }`}>
        {value > 0 ? '+' : ''}{fmt(value)}
      </span>
    </div>
  )
}

function StrategyBadge({ strategy }: { strategy: CategoryAnalysis['strategy'] }) {
  const styles = {
    target: 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50',
    lock: 'bg-blue-900/60 text-blue-300 border-blue-700/50',
    punt: 'bg-red-900/60 text-red-300 border-red-700/50 line-through',
    neutral: 'bg-gray-800/60 text-gray-500 border-gray-700/50',
  }
  const labels = { target: 'TARGET', lock: 'LOCK', punt: 'PUNT', neutral: 'NEUTRAL' }
  return (
    <span className={`px-1 py-0.5 rounded text-[8px] font-bold border leading-none ${styles[strategy]}`}>
      {labels[strategy]}
    </span>
  )
}

function ZScoreBar({ value, maxVal = 4 }: { value: number; maxVal?: number }) {
  const clamped = Math.max(-maxVal, Math.min(maxVal, value))
  const widthPct = Math.abs(clamped) / maxVal * 50
  const isPositive = clamped >= 0
  return (
    <div className="flex items-center h-3 w-full">
      {/* Left half (negative) */}
      <div className="w-1/2 flex justify-end">
        {!isPositive && (
          <div
            className="h-2.5 rounded-l bg-red-500/50"
            style={{ width: `${widthPct}%` }}
          />
        )}
      </div>
      {/* Center line */}
      <div className="w-px h-3 bg-gray-600 shrink-0" />
      {/* Right half (positive) */}
      <div className="w-1/2">
        {isPositive && (
          <div
            className="h-2.5 rounded-r bg-emerald-500/50"
            style={{ width: `${widthPct}%` }}
          />
        )}
      </div>
    </div>
  )
}

// ── Modal component ──

export function ScoreDetailModal({ data, onClose }: {
  data: ScoreDetailData | null
  onClose: () => void
}) {
  // Escape key handler
  useEffect(() => {
    if (!data) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [data, onClose])

  // Body scroll lock
  useEffect(() => {
    if (!data) return
    document.body.classList.add('overflow-hidden')
    return () => document.body.classList.remove('overflow-hidden')
  }, [data])

  if (!data) return null

  const d = data
  const primaryPos = d.positions[0]
  const confidencePct = Math.round(d.confidence * 100)

  // Sort category gains: biggest positive delta first, then zero, then negative
  const sortedGains = [...d.categoryGains].sort((a, b) => {
    const deltaA = a.winProbAfter - a.winProbBefore
    const deltaB = b.winProbAfter - b.winProbBefore
    return deltaB - deltaA
  })

  // Strategy map from categoryStandings
  const strategyMap: Record<string, CategoryAnalysis['strategy']> = {}
  for (const s of d.categoryStandings) {
    strategyMap[s.catKey] = s.strategy
  }

  // Standing map from categoryStandings
  const standingMap: Record<string, CategoryAnalysis> = {}
  for (const s of d.categoryStandings) {
    standingMap[s.catKey] = s
  }

  // Determine which cats are relevant for this player type
  const relevantCats: CatDef[] = d.playerType === 'pitcher' ? PITCHING_CATS : HITTING_CATS

  // Eligible positions for replacement level display
  const positionsForReplacement = d.playerType === 'pitcher'
    ? [d.rawZScores['zscore_qs'] ? 'SP' : 'RP']
    : [...new Set(d.positions.map(p => ({ LF: 'OF', CF: 'OF', RF: 'OF' }[p] ?? p)))]

  return (
    // Backdrop
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 backdrop-blur-sm overflow-y-auto py-8 px-4"
      onClick={onClose}
    >
      {/* Modal */}
      <div
        className="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* ─── A) Header ─── */}
        <div className="px-5 py-4 border-b border-gray-800 flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              {d.positions.map(pos => (
                <span
                  key={pos}
                  className={`inline-flex items-center justify-center px-2 h-5 rounded text-[10px] font-bold text-white ${posColor[pos] || 'bg-gray-600'}`}
                >
                  {pos}
                </span>
              ))}
              <span className="text-lg font-bold text-white truncate">{d.fullName}</span>
              {d.badge === 'NOW' && (
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-red-900/60 text-red-300 border border-red-700/50 leading-none">NOW</span>
              )}
              {d.badge === 'WAIT' && (
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-gray-800 text-gray-500 border border-gray-700/50 leading-none">WAIT</span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-400">
              <span>{d.team}</span>
              <span className="text-gray-600">|</span>
              <span>Rank <span className="text-white font-bold">#{d.overallRank}</span></span>
              {d.espnAdp != null && (
                <>
                  <span className="text-gray-600">|</span>
                  <span>ADP <span className="text-white font-bold">{Math.round(d.espnAdp)}</span></span>
                </>
              )}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <div className="text-3xl font-black tabular-nums text-purple-400">{fmt(d.finalScore, 1)}</div>
            <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">Score</div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white transition-colors text-xl leading-none ml-2 mt-1"
          >
            &times;
          </button>
        </div>

        <div className="px-5 py-4 space-y-5 max-h-[calc(100vh-12rem)] overflow-y-auto">

          {/* ─── B) Score Formula ─── */}
          <section>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Score Formula</h3>
            {d.hasMCW && d.confidence > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* MCW path */}
                <div className="bg-gray-800/40 rounded-lg p-3">
                  <div className="text-[10px] font-bold text-purple-400 uppercase tracking-wider mb-1.5">
                    MCW Path <span className="text-gray-500 normal-case">({confidencePct}% weight)</span>
                  </div>
                  <FormulaRow
                    label="MCW"
                    formula={`${fmt(d.mcw, 3)} x 21.0 x ${fmt(d.confidence)}`}
                    value={d.mcwComponent}
                    highlight={d.mcwComponent > d.vonaComponentHigh}
                  />
                  <FormulaRow
                    label="VONA"
                    formula={`${fmt(d.vona)} x 0.16`}
                    value={d.vonaComponentHigh}
                    highlight={d.vonaComponentHigh > d.mcwComponent}
                  />
                  <FormulaRow
                    label="Urgency"
                    formula={`${fmt(d.urgency, 1)} x 0.02`}
                    value={d.urgencyComponentHigh}
                  />
                  <FormulaRow
                    label="Roster Fit"
                    formula={`${d.rosterFit} x ${fmt(d.draftProgress)}`}
                    value={d.rosterFitComponent}
                  />
                  <div className="border-t border-gray-700 mt-1 pt-1">
                    <FormulaRow label="Subtotal" formula="" value={d.highConfidenceTotal} />
                  </div>
                </div>

                {/* BPA path */}
                <div className="bg-gray-800/40 rounded-lg p-3">
                  <div className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider mb-1.5">
                    BPA Path <span className="text-gray-500 normal-case">({100 - confidencePct}% weight)</span>
                  </div>
                  <FormulaRow
                    label="Surplus Value"
                    formula={`${fmt(d.normalizedValue)} - repl`}
                    value={d.surplusValue}
                    highlight={d.surplusValue > d.vona * 0.42}
                  />
                  <FormulaRow
                    label="VONA"
                    formula={`${fmt(d.vona)} x 0.42`}
                    value={d.vona * 0.42}
                    highlight={d.vona * 0.42 > d.surplusValue}
                  />
                  <FormulaRow
                    label="Urgency"
                    formula={`${fmt(d.urgency, 1)} x 0.55`}
                    value={d.urgency * 0.55}
                  />
                  <div className="border-t border-gray-700 mt-1 pt-1">
                    <FormulaRow label="Subtotal" formula="" value={d.lowConfidenceTotal} />
                  </div>
                </div>
              </div>
            ) : (
              /* BPA-only mode (no MCW data) */
              <div className="bg-gray-800/40 rounded-lg p-3 max-w-sm">
                <div className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider mb-1.5">
                  BPA Formula
                </div>
                <FormulaRow
                  label="Surplus Value"
                  formula={`${fmt(d.normalizedValue)} - repl`}
                  value={d.surplusValue}
                />
                <FormulaRow
                  label="VONA"
                  formula={`${fmt(d.vona)} x 0.42`}
                  value={d.vona * 0.42}
                />
                <FormulaRow
                  label="Urgency"
                  formula={`${fmt(d.urgency, 1)} x 0.55`}
                  value={d.urgency * 0.55}
                />
                <div className="border-t border-gray-700 mt-1 pt-1">
                  <FormulaRow label="Total" formula="" value={d.lowConfidenceTotal} />
                </div>
              </div>
            )}

            {/* Confidence blend */}
            {d.hasMCW && d.confidence > 0 && (
              <div className="mt-3 space-y-1.5">
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="text-gray-500">Blended:</span>
                  <span className="text-purple-400 font-bold tabular-nums">{fmt(d.highConfidenceTotal)}</span>
                  <span className="text-gray-600">x {confidencePct}%</span>
                  <span className="text-gray-600">+</span>
                  <span className="text-emerald-400 font-bold tabular-nums">{fmt(d.lowConfidenceTotal)}</span>
                  <span className="text-gray-600">x {100 - confidencePct}%</span>
                  <span className="text-gray-600">=</span>
                  <span className="text-white font-bold tabular-nums">{fmt(d.blendedScore)}</span>
                </div>
                {/* Confidence bar */}
                <div className="h-2 rounded-full overflow-hidden flex bg-gray-800">
                  <div className="bg-purple-500/60 h-full" style={{ width: `${confidencePct}%` }} />
                  <div className="bg-emerald-500/60 h-full" style={{ width: `${100 - confidencePct}%` }} />
                </div>
                <div className="flex justify-between text-[9px] text-gray-500">
                  <span>MCW {confidencePct}%</span>
                  <span>BPA {100 - confidencePct}%</span>
                </div>
              </div>
            )}

            {/* Bench penalty */}
            {d.benchPenalty < 1.0 && (
              <div className="mt-2 flex items-center gap-2 text-[11px] bg-red-950/20 border border-red-900/30 rounded-lg px-3 py-1.5">
                <span className="text-red-400 font-bold">Bench Penalty</span>
                <span className="text-gray-400">x {fmt(d.benchPenalty)}</span>
                {d.benchPenaltyReason && (
                  <span className="text-gray-500 text-[10px]">({d.benchPenaltyReason})</span>
                )}
                <span className="ml-auto text-white font-bold tabular-nums">{fmt(d.blendedScore)} x {fmt(d.benchPenalty)} = {fmt(d.finalScore, 1)}</span>
              </div>
            )}
          </section>

          {/* ─── C) Category Impact Table ─── */}
          {d.categoryGains.length > 0 && d.categoryStandings.length > 0 && (
            <section>
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Category Impact</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="border-b border-gray-800">
                      <th className="px-2 py-1.5 text-left text-gray-500 font-semibold">Cat</th>
                      <th className="px-2 py-1.5 text-left text-gray-500 font-semibold">Strategy</th>
                      <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">Rank</th>
                      <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">Win% Before</th>
                      <th className="px-2 py-1.5 text-center text-gray-500 font-semibold"></th>
                      <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">After</th>
                      <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">Delta</th>
                      <th className="px-2 py-1.5 text-right text-gray-500 font-semibold">Z-Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedGains.map(g => {
                      const delta = g.winProbAfter - g.winProbBefore
                      const strategy = strategyMap[g.catKey] ?? 'neutral'
                      const standing = standingMap[g.catKey]
                      const rawZ = d.rawZScores[g.catKey] ?? 0
                      const isPunted = strategy === 'punt'
                      return (
                        <tr
                          key={g.catKey}
                          className={`border-b border-gray-800/30 ${isPunted ? 'opacity-40' : ''} ${delta > 0.02 ? 'bg-emerald-950/10' : ''}`}
                        >
                          <td className="px-2 py-1.5 font-bold text-gray-300">{g.label}</td>
                          <td className="px-2 py-1.5"><StrategyBadge strategy={strategy} /></td>
                          <td className="px-2 py-1.5 text-right font-bold tabular-nums text-gray-400">
                            {standing ? standing.myRank.toFixed(1) : '--'}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-gray-400">
                            {pct(g.winProbBefore)}
                          </td>
                          <td className="px-2 py-1.5 text-center text-gray-600">&rarr;</td>
                          <td className={`px-2 py-1.5 text-right font-bold tabular-nums ${
                            delta > 0.02 ? 'text-emerald-400' : 'text-gray-400'
                          }`}>
                            {pct(g.winProbAfter)}
                          </td>
                          <td className={`px-2 py-1.5 text-right font-bold tabular-nums ${
                            delta > 0.02 ? 'text-emerald-400' : delta > 0 ? 'text-emerald-400/60' : 'text-gray-600'
                          }`}>
                            {delta > 0 ? '+' : ''}{(delta * 100).toFixed(1)}
                          </td>
                          <td className={`px-2 py-1.5 text-right font-bold tabular-nums ${
                            rawZ > 0 ? 'text-emerald-400' : rawZ < 0 ? 'text-red-400' : 'text-gray-600'
                          }`}>
                            {rawZ > 0 ? '+' : ''}{fmt(rawZ)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* ─── D) Value Breakdown ─── */}
          <section>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Value Breakdown</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-gray-800/40 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Normalized Value</span>
                  <span className={`text-sm font-bold tabular-nums ${d.normalizedValue >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {d.normalizedValue > 0 ? '+' : ''}{fmt(d.normalizedValue)}
                  </span>
                </div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Surplus Value</span>
                  <span className={`text-sm font-bold tabular-nums ${d.surplusValue >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {d.surplusValue > 0 ? '+' : ''}{fmt(d.surplusValue)}
                  </span>
                </div>
                {/* Replacement levels for eligible positions */}
                <div className="border-t border-gray-700 pt-1.5 mt-1.5 space-y-0.5">
                  <div className="text-[9px] text-gray-500 font-semibold">Replacement levels:</div>
                  {positionsForReplacement.map(pos => (
                    <div key={pos} className="flex items-center justify-between text-[10px]">
                      <span className="text-gray-400">{pos}</span>
                      <span className="text-gray-500 tabular-nums">
                        {d.replacementLevels[pos] != null ? fmt(d.replacementLevels[pos]) : '--'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Standardized Z-score bars */}
              <div className="bg-gray-800/40 rounded-lg p-3">
                <div className="text-[10px] text-gray-500 font-bold uppercase tracking-wider mb-1.5">
                  Standardized Z-Scores
                </div>
                <div className="space-y-0.5">
                  {relevantCats.map(cat => {
                    const stdZ = d.standardizedZScores[cat.key] ?? 0
                    return (
                      <div key={cat.key} className="flex items-center gap-1.5">
                        <span className="w-8 text-[10px] font-bold text-gray-400 text-right shrink-0">{cat.label}</span>
                        <div className="flex-1"><ZScoreBar value={stdZ} /></div>
                        <span className={`w-10 text-[10px] font-bold tabular-nums text-right shrink-0 ${
                          stdZ > 0 ? 'text-emerald-400' : stdZ < 0 ? 'text-red-400' : 'text-gray-600'
                        }`}>
                          {stdZ > 0 ? '+' : ''}{fmt(stdZ, 1)}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </section>

          {/* ─── E) Availability & Urgency ─── */}
          {d.espnAdp != null && (
            <section>
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Availability & Urgency</h3>
              <div className="bg-gray-800/40 rounded-lg p-3">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
                  <div>
                    <div className="text-[10px] text-gray-500 font-semibold">ESPN ADP</div>
                    <div className="text-lg font-bold text-white tabular-nums">{Math.round(d.espnAdp)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500 font-semibold">Picks Until Mine</div>
                    <div className="text-lg font-bold text-white tabular-nums">
                      {d.picksUntilMine >= 999 ? '--' : d.picksUntilMine}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500 font-semibold">P(Available)</div>
                    <div className={`text-lg font-bold tabular-nums ${
                      d.availability == null ? 'text-gray-600' :
                      d.availability >= 0.8 ? 'text-emerald-400' :
                      d.availability >= 0.5 ? 'text-yellow-400' :
                      d.availability >= 0.2 ? 'text-orange-400' : 'text-red-400'
                    }`}>
                      {d.availability != null ? pct(d.availability) : '--'}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500 font-semibold">Urgency</div>
                    <div className={`text-lg font-bold tabular-nums ${
                      d.urgency >= 10 ? 'text-red-400' : d.urgency >= 5 ? 'text-yellow-400' : 'text-gray-400'
                    }`}>
                      {fmt(d.urgency, 1)}
                    </div>
                  </div>
                </div>
                {/* Urgency formula walkthrough */}
                <div className="mt-2 pt-2 border-t border-gray-700 text-[10px] text-gray-500 font-mono">
                  urgency = max(0, min(15, {d.picksUntilMine >= 999 ? '?' : d.picksUntilMine} - ({Math.round(d.espnAdp)} - currentPick)))
                  = <span className="text-white font-bold">{fmt(d.urgency, 1)}</span>
                </div>
              </div>
            </section>
          )}

          {/* ─── F) Roster Context ─── */}
          <section>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Roster Context</h3>
            <div className="bg-gray-800/40 rounded-lg p-3">
              {d.filledSlots.length > 0 ? (
                <div>
                  <div className="text-[11px] text-emerald-400 font-semibold mb-1">Fills starting roster slot</div>
                  <div className="flex flex-wrap gap-1.5">
                    {d.filledSlots.map(slot => (
                      <span
                        key={slot}
                        className={`inline-flex items-center px-2 py-1 rounded text-[10px] font-bold text-white ${posColor[slot] || 'bg-gray-600'}`}
                      >
                        {slot}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <div>
                  <div className="text-[11px] text-yellow-400 font-semibold mb-1">Bench only</div>
                  {d.benchPenalty < 1.0 && (
                    <div className="text-[10px] text-gray-500">
                      Score penalized by x{fmt(d.benchPenalty)} ({d.benchPenaltyReason})
                    </div>
                  )}
                  {d.draftProgress <= 0.15 && (
                    <div className="text-[10px] text-gray-500">No bench penalty applied (early draft)</div>
                  )}
                </div>
              )}
            </div>
          </section>

        </div>
      </div>
    </div>
  )
}
