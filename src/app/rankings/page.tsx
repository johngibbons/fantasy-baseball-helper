'use client'

import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { getRankings, RankedPlayer } from '@/lib/valuations-api'
import { getPositions } from '@/lib/roster-optimizer'

const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH', 'SP', 'RP']
const TYPES = ['All', 'hitter', 'pitcher']

type SortKey = 'overall_rank' | 'total_zscore' | 'zscore_r' | 'zscore_tb' | 'zscore_rbi' | 'zscore_sb' | 'zscore_obp' | 'zscore_k' | 'zscore_qs' | 'zscore_era' | 'zscore_whip' | 'zscore_svhd'

const posColors: Record<string, string> = {
  C: 'text-blue-400', '1B': 'text-amber-400', '2B': 'text-orange-400', '3B': 'text-purple-400',
  SS: 'text-red-400', OF: 'text-emerald-400', LF: 'text-emerald-400', CF: 'text-teal-400',
  RF: 'text-emerald-400', DH: 'text-gray-400', SP: 'text-sky-400', RP: 'text-pink-400', P: 'text-sky-400',
  TWP: 'text-violet-400',
}

function zBg(v: number | undefined | null): string {
  if (v == null) return ''
  if (v >= 3)  return 'bg-emerald-500/30 text-emerald-300'
  if (v >= 2)  return 'bg-emerald-500/20 text-emerald-300'
  if (v >= 1)  return 'bg-emerald-500/10 text-emerald-400'
  if (v >= 0)  return 'text-gray-400'
  if (v >= -1) return 'text-red-400/80'
  if (v >= -2) return 'bg-red-500/10 text-red-400'
  return 'bg-red-500/20 text-red-300'
}

function fmtZ(v: number | undefined | null): string {
  if (v == null) return '—'
  const s = v.toFixed(1)
  return v > 0 ? `+${s}` : s
}

export default function RankingsPage() {
  const [players, setPlayers] = useState<RankedPlayer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [posFilter, setPosFilter] = useState('All')
  const [typeFilter, setTypeFilter] = useState('All')
  const [sortKey, setSortKey] = useState<SortKey>('overall_rank')
  const [sortAsc, setSortAsc] = useState(true)
  const [searchText, setSearchText] = useState('')

  useEffect(() => {
    setLoading(true)
    getRankings({
      playerType: typeFilter === 'All' ? undefined : typeFilter,
      position: posFilter === 'All' ? undefined : posFilter,
      limit: 10000,
    })
      .then((data) => setPlayers(data.rankings))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [typeFilter, posFilter])

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(key === 'overall_rank') }
  }

  const filtered = useMemo(() => {
    let list = [...players]
    if (searchText) {
      const q = searchText.toLowerCase()
      list = list.filter((p) => p.full_name.toLowerCase().includes(q))
    }
    list.sort((a, b) => {
      const aVal = ((a as unknown as Record<string, number>)[sortKey]) ?? 0
      const bVal = ((b as unknown as Record<string, number>)[sortKey]) ?? 0
      return sortAsc ? aVal - bVal : bVal - aVal
    })
    return list
  }, [players, searchText, sortKey, sortAsc])

  const showHitterCats = typeFilter !== 'pitcher'
  const showPitcherCats = typeFilter !== 'hitter'

  return (
    <main className="min-h-screen bg-[#0a0e17]">
      <div className="max-w-[90rem] mx-auto px-4 sm:px-6 py-5">
        {/* Header */}
        <div className="flex items-end justify-between mb-4">
          <div>
            <h1 className="text-xl font-bold text-white">Player Rankings</h1>
            <p className="text-xs text-gray-500 mt-0.5">{filtered.length} players &middot; 2026 projections</p>
          </div>
        </div>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <div className="flex items-center bg-[#111827] rounded-lg p-0.5 gap-0.5">
            {TYPES.map((t) => (
              <button
                key={t}
                onClick={() => { setTypeFilter(t); setPosFilter('All') }}
                className={`px-3 py-1 rounded-md text-xs font-semibold transition-all ${
                  typeFilter === t
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {t === 'All' ? 'All' : t === 'hitter' ? 'Hitters' : 'Pitchers'}
              </button>
            ))}
          </div>

          <div className="h-5 w-px bg-gray-800" />

          <div className="flex items-center bg-[#111827] rounded-lg p-0.5 gap-0.5">
            {POSITIONS.map((p) => (
              <button
                key={p}
                onClick={() => setPosFilter(p)}
                className={`px-2 py-1 rounded-md text-xs font-semibold transition-all ${
                  posFilter === p
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {p}
              </button>
            ))}
          </div>

          <div className="h-5 w-px bg-gray-800" />

          <div className="relative">
            <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Search..."
              className="w-52 bg-[#111827] rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-gray-600 border border-transparent focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/30 transition-all"
            />
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <div className="w-5 h-5 border-2 border-gray-700 border-t-blue-500 rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="bg-red-950/50 border border-red-900/50 rounded-xl p-6 text-red-400 text-sm">{error}</div>
        ) : (
          <div className="rounded-xl border border-gray-800/60 overflow-hidden bg-[#0d1117]">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="bg-[#111827]/80 glass sticky top-0 z-10">
                    <Th label="#" field="overall_rank" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} left className="w-12 pl-4" />
                    <th className="px-2 py-2 text-center text-[10px] font-semibold text-gray-500 uppercase tracking-wider w-14">ADP</th>
                    <th className="px-2 py-2 text-center text-[10px] font-semibold text-gray-500 uppercase tracking-wider w-14">NFBC</th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Player</th>
                    <th className="px-2 py-2 text-center text-[10px] font-semibold text-gray-500 uppercase tracking-wider w-12">Pos</th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider min-w-[140px]">Team</th>
                    <Th label="Value" field="total_zscore" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} className="w-16" />
                    {showHitterCats && (
                      <>
                        <th className="px-1 py-2 text-center text-[10px] font-semibold text-gray-600 uppercase tracking-wider" colSpan={5}>
                          <span className="border-b border-gray-700/50 pb-0.5">Hitting</span>
                        </th>
                      </>
                    )}
                    {showPitcherCats && (
                      <>
                        <th className="px-1 py-2 text-center text-[10px] font-semibold text-gray-600 uppercase tracking-wider" colSpan={5}>
                          <span className="border-b border-gray-700/50 pb-0.5">Pitching</span>
                        </th>
                      </>
                    )}
                  </tr>
                  <tr className="bg-[#111827]/50">
                    <th className="h-0" />
                    <th className="h-0" />
                    <th className="h-0" />
                    <th className="h-0" />
                    <th className="h-0" />
                    <th className="h-0" />
                    <th className="h-0" />
                    {showHitterCats && (
                      <>
                        <Th label="R" field="zscore_r" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                        <Th label="TB" field="zscore_tb" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                        <Th label="RBI" field="zscore_rbi" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                        <Th label="SB" field="zscore_sb" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                        <Th label="OBP" field="zscore_obp" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                      </>
                    )}
                    {showPitcherCats && (
                      <>
                        <Th label="K" field="zscore_k" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                        <Th label="QS" field="zscore_qs" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                        <Th label="ERA" field="zscore_era" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                        <Th label="WHIP" field="zscore_whip" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                        <Th label="SVHD" field="zscore_svhd" sortKey={sortKey} sortAsc={sortAsc} onSort={handleSort} sub />
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p, idx) => {
                    const isHitter = p.player_type === 'hitter'
                    return (
                      <tr
                        key={p.mlb_id}
                        className={`group border-b border-white/[0.03] transition-colors hover:bg-white/[0.03] ${
                          idx % 2 === 1 ? 'bg-white/[0.015]' : ''
                        }`}
                      >
                        {/* Rank */}
                        <td className="pl-4 pr-1 py-[7px]">
                          <span className="text-[11px] text-gray-600 font-mono tabular-nums">{p.overall_rank}</span>
                        </td>

                        {/* ADP */}
                        <td className="px-2 py-[7px] text-center">
                          {p.espn_adp != null ? (
                            <div className="flex items-center justify-center gap-1">
                              <span className="text-[11px] text-gray-500 tabular-nums">{Math.round(p.espn_adp)}</span>
                              {p.adp_diff != null && Math.abs(p.adp_diff) > 5 && (
                                <span className={`text-[9px] font-bold tabular-nums ${p.adp_diff < 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {p.adp_diff > 0 ? '+' : ''}{Math.round(p.adp_diff)}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-[11px] text-gray-800">—</span>
                          )}
                        </td>

                        {/* NFBC ADP */}
                        <td className="px-2 py-[7px] text-center">
                          {p.fangraphs_adp != null ? (
                            <span className="text-[11px] text-gray-500 tabular-nums">{Math.round(p.fangraphs_adp)}</span>
                          ) : (
                            <span className="text-[11px] text-gray-800">—</span>
                          )}
                        </td>

                        {/* Name */}
                        <td className="px-3 py-[7px]">
                          <Link href={`/player/${p.mlb_id}`} className="text-[13px] font-medium text-gray-200 hover:text-white transition-colors group-hover:text-white">
                            {p.full_name}
                          </Link>
                        </td>

                        {/* Position */}
                        <td className="px-2 py-[7px] text-center">
                          {(() => {
                            const positions = getPositions(p)
                            return (
                              <span className={`text-[11px] font-bold ${posColors[positions[0]] || 'text-gray-500'}`}>
                                {positions.join(', ')}
                              </span>
                            )
                          })()}
                        </td>

                        {/* Team */}
                        <td className="px-3 py-[7px]">
                          <span className="text-[12px] text-gray-500">{p.team}</span>
                        </td>

                        {/* Total z-score */}
                        <td className="px-2 py-[7px] text-right">
                          <span className={`inline-flex items-center justify-end min-w-[3rem] px-1.5 py-[1px] rounded text-[12px] font-bold tabular-nums ${zBg(p.total_zscore)}`}>
                            {fmtZ(p.total_zscore)}
                          </span>
                        </td>

                        {/* Category z-scores — two-way players show values in both sections */}
                        {showHitterCats && (
                          (isHitter || [p.zscore_r, p.zscore_tb, p.zscore_rbi, p.zscore_sb, p.zscore_obp].some(v => v != null && v !== 0)) ? (
                            <>
                              <ZTd v={p.zscore_r} />
                              <ZTd v={p.zscore_tb} />
                              <ZTd v={p.zscore_rbi} />
                              <ZTd v={p.zscore_sb} />
                              <ZTd v={p.zscore_obp} />
                            </>
                          ) : (
                            <td colSpan={5} className="text-center text-gray-800 text-[11px]">—</td>
                          )
                        )}
                        {showPitcherCats && (
                          (!isHitter || [p.zscore_k, p.zscore_qs, p.zscore_era, p.zscore_whip, p.zscore_svhd].some(v => v != null && v !== 0)) ? (
                            <>
                              <ZTd v={p.zscore_k} />
                              <ZTd v={p.zscore_qs} />
                              <ZTd v={p.zscore_era} />
                              <ZTd v={p.zscore_whip} />
                              <ZTd v={p.zscore_svhd} />
                            </>
                          ) : (
                            <td colSpan={5} className="text-center text-gray-800 text-[11px]">—</td>
                          )
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {filtered.length === 0 && (
              <div className="text-center py-16 text-gray-600 text-sm">No players found</div>
            )}
          </div>
        )}
      </div>
    </main>
  )
}

function Th({ label, field, sortKey, sortAsc, onSort, left, sub, className = '' }: {
  label: string; field: SortKey; sortKey: SortKey; sortAsc: boolean;
  onSort: (k: SortKey) => void; left?: boolean; sub?: boolean; className?: string
}) {
  const active = sortKey === field
  return (
    <th
      className={`px-2 ${sub ? 'py-1' : 'py-2'} ${left ? 'text-left' : 'text-center'} text-[10px] font-semibold uppercase tracking-wider cursor-pointer select-none transition-colors whitespace-nowrap ${
        active ? 'text-blue-400' : 'text-gray-500 hover:text-gray-300'
      } ${className}`}
      onClick={() => onSort(field)}
    >
      {label}
      {active && <span className="ml-0.5 text-[8px]">{sortAsc ? '\u25B2' : '\u25BC'}</span>}
    </th>
  )
}

function ZTd({ v }: { v?: number }) {
  if (v == null) return <td className="px-1 py-[7px] text-center text-gray-800 text-[11px]">—</td>
  return (
    <td className="px-1 py-[7px] text-center">
      <span className={`inline-block min-w-[2.5rem] px-1 py-[1px] rounded text-[11px] font-medium tabular-nums ${zBg(v)}`}>
        {fmtZ(v)}
      </span>
    </td>
  )
}
