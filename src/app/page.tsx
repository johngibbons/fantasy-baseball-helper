'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { getStatsSummary, StatsSummary } from '@/lib/valuations-api'

const posColor: Record<string, string> = {
  C: 'bg-blue-500', '1B': 'bg-amber-500', '2B': 'bg-orange-500', '3B': 'bg-purple-500',
  SS: 'bg-red-500', OF: 'bg-emerald-500', LF: 'bg-emerald-500', CF: 'bg-emerald-500',
  RF: 'bg-emerald-500', DH: 'bg-gray-500', SP: 'bg-sky-500', RP: 'bg-pink-500', P: 'bg-sky-500',
}

export default function Dashboard() {
  const [summary, setSummary] = useState<StatsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null)

  const loadSummary = () => {
    setLoading(true)
    getStatsSummary()
      .then(setSummary)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadSummary() }, [])

  const handleRefreshProjections = async () => {
    setRefreshing(true)
    setRefreshMsg(null)
    try {
      const res = await fetch('/api/v2/projections/refresh?season=2026', { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setRefreshMsg(`Updated: ${data.total_players} players from FanGraphs`)
      loadSummary()
    } catch (e) {
      setRefreshMsg(`Failed: ${e instanceof Error ? e.message : 'Unknown error'}`)
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <main className="min-h-screen bg-gray-950">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="text-gray-500 text-sm mt-0.5">
              H2H Categories &middot; R, TB, RBI, SB, OBP | K, QS, ERA, WHIP, SVHD
            </p>
          </div>
          {summary && (
            <div className="flex items-center gap-3">
              {refreshMsg && (
                <span className={`text-xs ${refreshMsg.startsWith('Failed') ? 'text-red-400' : 'text-emerald-400'}`}>
                  {refreshMsg}
                </span>
              )}
              <button
                onClick={handleRefreshProjections}
                disabled={refreshing}
                className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-300 text-xs font-medium rounded-md border border-gray-700 transition-colors"
              >
                {refreshing ? 'Fetching...' : 'Refresh Projections'}
              </button>
            </div>
          )}
        </div>

        {loading ? (
          <div className="text-center py-20 text-gray-500">
            <div className="inline-block w-6 h-6 border-2 border-gray-600 border-t-blue-500 rounded-full animate-spin mb-3" />
            <div>Loading data...</div>
          </div>
        ) : error ? (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h2 className="text-lg font-bold text-amber-400 mb-2">Backend not connected</h2>
            <p className="text-gray-400 mb-4 text-sm">Start the FastAPI backend to see valuations data.</p>
            <div className="bg-gray-950 rounded-lg p-4 font-mono text-sm text-emerald-400 border border-gray-800 space-y-1">
              <div><span className="text-gray-500">$</span> python3.10 -m backend.data.sync --season 2026 --stats-seasons 2025 2024</div>
              <div><span className="text-gray-500">$</span> uvicorn backend.api.main:app --reload</div>
            </div>
          </div>
        ) : summary ? (
          <>
            {/* Stats cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
                <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Total Ranked</div>
                <div className="text-3xl font-black text-white mt-1 tabular-nums">{summary.total_players}</div>
              </div>
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
                <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Hitters</div>
                <div className="text-3xl font-black text-blue-400 mt-1 tabular-nums">{summary.total_hitters}</div>
              </div>
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
                <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Pitchers</div>
                <div className="text-3xl font-black text-emerald-400 mt-1 tabular-nums">{summary.total_pitchers}</div>
              </div>
            </div>

            {/* Top 5 */}
            {summary.top_5.length > 0 && (
              <div className="bg-gray-900 rounded-xl border border-gray-800 mb-6 overflow-hidden">
                <div className="px-5 py-3 border-b border-gray-800">
                  <h2 className="text-sm font-bold text-gray-300 uppercase tracking-wider">Top 5 Overall</h2>
                </div>
                <div>
                  {summary.top_5.map((player, idx) => (
                    <Link
                      key={player.mlb_id}
                      href={`/player/${player.mlb_id}`}
                      className={`flex items-center justify-between px-5 py-3.5 hover:bg-gray-800/60 transition-colors border-b border-gray-800/50 ${idx % 2 === 0 ? '' : 'bg-gray-800/20'}`}
                    >
                      <div className="flex items-center gap-4">
                        <span className="text-2xl font-black text-gray-600 w-8 tabular-nums text-right">
                          {player.overall_rank}
                        </span>
                        <div>
                          <div className="font-semibold text-white">{player.full_name}</div>
                          <div className="text-xs text-gray-500 flex items-center gap-1.5 mt-0.5">
                            <span className={`inline-flex items-center justify-center w-7 h-4 rounded text-[9px] font-bold text-white ${posColor[player.primary_position] || 'bg-gray-600'}`}>{player.primary_position}</span>
                            {player.team}
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-lg font-black text-emerald-400 tabular-nums">
                          +{player.total_zscore.toFixed(1)}
                        </div>
                        <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">z-score</div>
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {/* Quick links */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { href: '/rankings', title: 'Rankings', desc: 'Full sortable player rankings with z-score breakdowns', color: 'border-blue-800 hover:border-blue-600' },
                { href: '/draft', title: 'Draft Board', desc: 'Live draft tracker with team builder', color: 'border-emerald-800 hover:border-emerald-600' },
                { href: '/players', title: 'Player Search', desc: 'Search MLB players and view detailed stats', color: 'border-purple-800 hover:border-purple-600' },
                { href: '/leagues', title: 'Leagues', desc: 'Connect ESPN/Yahoo leagues and manage rosters', color: 'border-amber-800 hover:border-amber-600' },
              ].map(link => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`bg-gray-900 rounded-xl border ${link.color} p-5 transition-all hover:bg-gray-800/50`}
                >
                  <h3 className="font-bold text-white mb-1">{link.title}</h3>
                  <p className="text-xs text-gray-500 leading-relaxed">{link.desc}</p>
                </Link>
              ))}
            </div>
          </>
        ) : (
          <div className="text-center py-20 text-gray-600">No data available</div>
        )}
      </div>
    </main>
  )
}
