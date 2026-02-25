'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  getFreeAgentRankings,
  getAddDropRecommendations,
  getMatchupAnalysis,
  getSeasonStrategy,
  getRosterSignals,
  findTrades,
  evaluateTrade,
  InseasonFreeAgent,
  SwapRecommendation,
  MatchupAnalysis,
  SeasonStrategy,
  RosterSignal,
  TradeProposal,
  TradeEvalResult,
} from '@/lib/valuations-api'

// ── Config (user should set these via the UI; hardcoded defaults for now) ──
const DEFAULT_LEAGUE_ID = ''
const DEFAULT_MY_TEAM_ID = 0
const DEFAULT_SEASON = 2026
const DEFAULT_NUM_TEAMS = 10

type Tab = 'overview' | 'matchup' | 'freeagents' | 'adddrop' | 'trades' | 'signals'

const posColors: Record<string, string> = {
  C: 'text-blue-400', '1B': 'text-amber-400', '2B': 'text-orange-400', '3B': 'text-purple-400',
  SS: 'text-red-400', OF: 'text-emerald-400', DH: 'text-gray-400', SP: 'text-sky-400',
  RP: 'text-pink-400', P: 'text-sky-400',
}

function mcwBg(v: number): string {
  if (v >= 0.05) return 'bg-emerald-500/30 text-emerald-300'
  if (v >= 0.02) return 'bg-emerald-500/15 text-emerald-400'
  if (v >= 0.005) return 'text-gray-300'
  if (v >= 0) return 'text-gray-500'
  return 'text-red-400'
}

function strategyBadge(strategy: string): string {
  switch (strategy) {
    case 'lock': return 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
    case 'target': return 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
    case 'punt': return 'bg-red-500/20 text-red-400 border border-red-500/30'
    default: return 'bg-white/5 text-gray-400 border border-white/10'
  }
}

function matchupStatusColor(status: string): string {
  switch (status) {
    case 'winning': return 'bg-emerald-500/25'
    case 'losing': return 'bg-red-500/25'
    case 'swing': return 'bg-amber-500/25'
    default: return 'bg-white/5'
  }
}

export default function InseasonPage() {
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [leagueId, setLeagueId] = useState(DEFAULT_LEAGUE_ID)
  const [myTeamId, setMyTeamId] = useState(DEFAULT_MY_TEAM_ID)
  const [season] = useState(DEFAULT_SEASON)
  const [numTeams] = useState(DEFAULT_NUM_TEAMS)
  const [syncing, setSyncing] = useState(false)
  const [lastSync, setLastSync] = useState<string | null>(null)
  const [configOpen, setConfigOpen] = useState(true)

  // Data states
  const [freeAgents, setFreeAgents] = useState<InseasonFreeAgent[]>([])
  const [recommendations, setRecommendations] = useState<SwapRecommendation[]>([])
  const [matchup, setMatchup] = useState<MatchupAnalysis | null>(null)
  const [strategy, setStrategy] = useState<SeasonStrategy | null>(null)
  const [signals, setSignals] = useState<RosterSignal[]>([])
  const [trades, setTrades] = useState<TradeProposal[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [posFilter, setPosFilter] = useState('')
  const [horizon, setHorizon] = useState<'ros' | 'week'>('ros')

  // Trade evaluator state
  const [tradeGiveIds, setTradeGiveIds] = useState('')
  const [tradeReceiveIds, setTradeReceiveIds] = useState('')
  const [tradePartnerId, setTradePartnerId] = useState('')
  const [tradeResult, setTradeResult] = useState<TradeEvalResult | null>(null)

  const isConfigured = leagueId !== '' && myTeamId !== 0

  // Load data when tab changes
  const loadTabData = useCallback(async () => {
    if (!isConfigured) return
    setLoading(true)
    setError(null)
    try {
      switch (activeTab) {
        case 'overview':
          const [stratRes, sigRes, recRes] = await Promise.all([
            getSeasonStrategy({ leagueId, season, myTeamId, numTeams }),
            getRosterSignals({ leagueId, season, myTeamId, numTeams, limit: 5 }),
            getAddDropRecommendations({ leagueId, season, myTeamId, numTeams, limit: 3 }),
          ])
          setStrategy(stratRes)
          setSignals(sigRes.signals)
          setRecommendations(recRes.recommendations)
          break
        case 'matchup':
          const mRes = await getMatchupAnalysis({ leagueId, season, matchupPeriod: 1, myTeamId })
          setMatchup(mRes)
          break
        case 'freeagents':
          const faRes = await getFreeAgentRankings({
            leagueId, season, myTeamId, numTeams,
            position: posFilter || undefined, limit: 100,
          })
          setFreeAgents(faRes.free_agents)
          break
        case 'adddrop':
          const adRes = await getAddDropRecommendations({
            leagueId, season, myTeamId, numTeams, horizon, limit: 30,
          })
          setRecommendations(adRes.recommendations)
          break
        case 'trades':
          const tRes = await findTrades({ leagueId, season, myTeamId, numTeams, limit: 30 })
          setTrades(tRes.trades)
          break
        case 'signals':
          const sRes = await getRosterSignals({ leagueId, season, myTeamId, numTeams, limit: 50 })
          setSignals(sRes.signals)
          break
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }, [activeTab, isConfigured, leagueId, season, myTeamId, numTeams, posFilter, horizon])

  useEffect(() => {
    loadTabData()
  }, [loadTabData])

  const handleSync = async () => {
    setSyncing(true)
    setError(null)
    try {
      // Call the Next.js inseason-sync route
      // For now, just call the FastAPI sync directly
      const res = await fetch(`/api/v2/inseason/sync?season=${season}`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setLastSync(data.last_ros_update || new Date().toISOString())
        await loadTabData()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const handleTradeEval = async () => {
    if (!tradeGiveIds || !tradeReceiveIds || !tradePartnerId) return
    setLoading(true)
    try {
      const result = await evaluateTrade({
        leagueId, season, myTeamId,
        partnerTeamId: parseInt(tradePartnerId),
        giveIds: tradeGiveIds.split(',').map(s => parseInt(s.trim())),
        receiveIds: tradeReceiveIds.split(',').map(s => parseInt(s.trim())),
        numTeams,
      })
      setTradeResult(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Trade eval failed')
    } finally {
      setLoading(false)
    }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'matchup', label: 'Matchup' },
    { key: 'freeagents', label: 'Free Agents' },
    { key: 'adddrop', label: 'Add/Drop' },
    { key: 'trades', label: 'Trades' },
    { key: 'signals', label: 'Signals' },
  ]

  return (
    <div className="max-w-[90rem] mx-auto px-4 sm:px-6 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">In-Season Manager</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Free agent rankings, add/drop recommendations, trade analysis
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastSync && (
            <span className="text-xs text-gray-500">
              Last sync: {new Date(lastSync).toLocaleString()}
            </span>
          )}
          <button
            onClick={handleSync}
            disabled={syncing || !isConfigured}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs font-medium rounded-md transition-colors"
          >
            {syncing ? 'Syncing...' : 'Sync Now'}
          </button>
          <button
            onClick={() => setConfigOpen(!configOpen)}
            className="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-gray-400 text-xs font-medium rounded-md transition-colors"
          >
            Config
          </button>
        </div>
      </div>

      {/* Config Panel */}
      {configOpen && (
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4 mb-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">ESPN League ID</label>
              <input
                type="text"
                value={leagueId}
                onChange={(e) => setLeagueId(e.target.value)}
                placeholder="e.g. 12345"
                className="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/50"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">My Team ID</label>
              <input
                type="number"
                value={myTeamId || ''}
                onChange={(e) => setMyTeamId(parseInt(e.target.value) || 0)}
                placeholder="e.g. 1"
                className="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/50"
              />
            </div>
            <div className="col-span-2 flex items-end">
              <p className="text-xs text-gray-600">
                {isConfigured
                  ? 'Configuration set. Click "Sync Now" to fetch latest data.'
                  : 'Enter your ESPN league ID and team ID to get started.'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-2 mb-4">
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors shrink-0 ${
              activeTab === tab.key
                ? 'bg-white/10 text-white'
                : 'text-gray-500 hover:text-gray-300 hover:bg-white/5'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500" />
        </div>
      )}

      {/* Tab Content */}
      {!loading && isConfigured && (
        <>
          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Strategy Summary */}
              {strategy && !strategy.error && (
                <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                  <h2 className="text-sm font-semibold text-white mb-3">Season Strategy</h2>
                  <div className="flex items-center gap-4 mb-3 text-xs">
                    <span className="text-gray-400">Expected Category Wins: <span className="text-white font-medium">{strategy.expected_category_wins}</span></span>
                  </div>
                  <div className="grid grid-cols-5 md:grid-cols-10 gap-2">
                    {strategy.categories.map((cat) => (
                      <div key={cat.cat_key} className="text-center">
                        <div className="text-[10px] text-gray-500 mb-1">{cat.category}</div>
                        <div className="text-sm font-medium text-white">{cat.rank}</div>
                        <div className={`inline-block px-1.5 py-0.5 rounded text-[10px] mt-1 ${strategyBadge(cat.strategy)}`}>
                          {cat.strategy}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Top Recommendations */}
              {recommendations.length > 0 && (
                <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                  <h2 className="text-sm font-semibold text-white mb-3">Top Swap Recommendations</h2>
                  <div className="space-y-2">
                    {recommendations.slice(0, 3).map((rec, i) => (
                      <div key={i} className="flex items-center gap-3 text-xs">
                        <span className="text-emerald-400 font-medium">+{rec.add_player.full_name}</span>
                        <span className={`${posColors[rec.add_player.primary_position] || 'text-gray-400'}`}>
                          {rec.add_player.primary_position}
                        </span>
                        <span className="text-gray-600">/</span>
                        <span className="text-red-400 font-medium">-{rec.drop_player.full_name}</span>
                        <span className="ml-auto text-gray-400">
                          MCW: <span className={mcwBg(rec.net_mcw)}>{rec.net_mcw > 0 ? '+' : ''}{rec.net_mcw.toFixed(3)}</span>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Top Signals */}
              {signals.length > 0 && (
                <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                  <h2 className="text-sm font-semibold text-white mb-3">Alerts</h2>
                  <div className="space-y-2">
                    {signals.slice(0, 5).map((sig, i) => (
                      <div key={i} className="flex items-center gap-3 text-xs">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                          sig.signal_type === 'add_target' ? 'bg-emerald-500/20 text-emerald-400' :
                          sig.signal_type === 'drop_candidate' ? 'bg-red-500/20 text-red-400' :
                          'bg-amber-500/20 text-amber-400'
                        }`}>{sig.action}</span>
                        <span className="text-white">{sig.full_name}</span>
                        <span className={posColors[sig.primary_position] || 'text-gray-400'}>{sig.primary_position}</span>
                        <span className="text-gray-500 ml-auto">{sig.description}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Matchup Tab */}
          {activeTab === 'matchup' && matchup && !matchup.error && (
            <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-white">Week {matchup.matchup_period} Matchup</h2>
                <span className="text-lg font-bold text-white">{matchup.projected_result}</span>
              </div>
              <div className="space-y-2">
                {matchup.categories.map((cat) => (
                  <div key={cat.category} className={`flex items-center gap-3 px-3 py-2 rounded-md ${matchupStatusColor(cat.status)}`}>
                    <span className="text-xs font-medium text-white w-12">{cat.category}</span>
                    <div className="flex-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-gray-300">{typeof cat.my_value === 'number' && cat.my_value % 1 !== 0 ? cat.my_value.toFixed(3) : cat.my_value}</span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          cat.status === 'winning' ? 'text-emerald-400' :
                          cat.status === 'losing' ? 'text-red-400' :
                          'text-amber-400'
                        }`}>{cat.status}</span>
                        <span className="text-gray-300">{typeof cat.opp_value === 'number' && cat.opp_value % 1 !== 0 ? cat.opp_value.toFixed(3) : cat.opp_value}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Free Agents Tab */}
          {activeTab === 'freeagents' && (
            <div>
              <div className="flex items-center gap-2 mb-4">
                {['', 'C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP'].map((pos) => (
                  <button
                    key={pos}
                    onClick={() => setPosFilter(pos)}
                    className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                      posFilter === pos ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    {pos || 'All'}
                  </button>
                ))}
              </div>
              <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="text-left px-3 py-2 text-gray-500 font-medium">#</th>
                      <th className="text-left px-3 py-2 text-gray-500 font-medium">Player</th>
                      <th className="text-left px-3 py-2 text-gray-500 font-medium">Pos</th>
                      <th className="text-left px-3 py-2 text-gray-500 font-medium">Team</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-medium">MCW</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-medium">Z-Score</th>
                      <th className="text-left px-3 py-2 text-gray-500 font-medium">Top Impact</th>
                    </tr>
                  </thead>
                  <tbody>
                    {freeAgents.map((fa, i) => {
                      const topCats = Object.entries(fa.category_impact)
                        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                        .slice(0, 3)
                      return (
                        <tr key={fa.mlb_id} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                          <td className="px-3 py-2 text-gray-600">{i + 1}</td>
                          <td className="px-3 py-2 text-white font-medium">{fa.full_name}</td>
                          <td className={`px-3 py-2 ${posColors[fa.primary_position] || 'text-gray-400'}`}>{fa.primary_position}</td>
                          <td className="px-3 py-2 text-gray-400">{fa.team}</td>
                          <td className={`px-3 py-2 text-right font-mono ${mcwBg(fa.mcw)}`}>{fa.mcw.toFixed(3)}</td>
                          <td className="px-3 py-2 text-right text-gray-400 font-mono">{fa.total_zscore.toFixed(1)}</td>
                          <td className="px-3 py-2">
                            <div className="flex gap-1">
                              {topCats.map(([cat, val]) => (
                                <span key={cat} className={`text-[10px] px-1 rounded ${val > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {cat} {val > 0 ? '+' : ''}{(val * 100).toFixed(0)}%
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {freeAgents.length === 0 && (
                  <div className="text-center py-8 text-gray-500 text-xs">
                    No free agent data available. Click "Sync Now" to fetch data.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Add/Drop Tab */}
          {activeTab === 'adddrop' && (
            <div>
              <div className="flex items-center gap-2 mb-4">
                <button
                  onClick={() => setHorizon('ros')}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                    horizon === 'ros' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  Season (ROS)
                </button>
                <button
                  onClick={() => setHorizon('week')}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                    horizon === 'week' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  This Week
                </button>
              </div>
              <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="text-left px-3 py-2 text-gray-500 font-medium">#</th>
                      <th className="text-left px-3 py-2 text-emerald-500 font-medium">Add</th>
                      <th className="text-left px-3 py-2 text-red-500 font-medium">Drop</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-medium">Net MCW</th>
                      <th className="text-left px-3 py-2 text-gray-500 font-medium">Category Impact</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recommendations.map((rec, i) => {
                      const topCats = Object.entries(rec.category_impact)
                        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                        .slice(0, 4)
                      return (
                        <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                          <td className="px-3 py-2 text-gray-600">{i + 1}</td>
                          <td className="px-3 py-2">
                            <span className="text-emerald-400 font-medium">{rec.add_player.full_name}</span>
                            <span className={` ml-1 ${posColors[rec.add_player.primary_position] || 'text-gray-400'}`}>
                              {rec.add_player.primary_position}
                            </span>
                          </td>
                          <td className="px-3 py-2">
                            <span className="text-red-400 font-medium">{rec.drop_player.full_name}</span>
                            <span className={` ml-1 ${posColors[rec.drop_player.primary_position] || 'text-gray-400'}`}>
                              {rec.drop_player.primary_position}
                            </span>
                          </td>
                          <td className={`px-3 py-2 text-right font-mono ${mcwBg(rec.net_mcw)}`}>
                            {rec.net_mcw > 0 ? '+' : ''}{rec.net_mcw.toFixed(3)}
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex gap-1">
                              {topCats.map(([cat, val]) => (
                                <span key={cat} className={`text-[10px] px-1 rounded ${val > 0 ? 'text-emerald-400/70' : 'text-red-400/70'}`}>
                                  {cat} {val > 0 ? '+' : ''}{val.toFixed(1)}
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {recommendations.length === 0 && (
                  <div className="text-center py-8 text-gray-500 text-xs">
                    No recommendations available. Sync data first.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Trades Tab */}
          {activeTab === 'trades' && (
            <div className="space-y-6">
              {/* Trade Evaluator */}
              <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                <h2 className="text-sm font-semibold text-white mb-3">Trade Evaluator</h2>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Give (MLB IDs, comma-separated)</label>
                    <input
                      type="text" value={tradeGiveIds} onChange={(e) => setTradeGiveIds(e.target.value)}
                      placeholder="660271"
                      className="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/50"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Receive (MLB IDs)</label>
                    <input
                      type="text" value={tradeReceiveIds} onChange={(e) => setTradeReceiveIds(e.target.value)}
                      placeholder="592450"
                      className="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/50"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Partner Team ID</label>
                    <input
                      type="text" value={tradePartnerId} onChange={(e) => setTradePartnerId(e.target.value)}
                      placeholder="3"
                      className="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/50"
                    />
                  </div>
                  <div className="flex items-end">
                    <button onClick={handleTradeEval}
                      className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded-md transition-colors">
                      Evaluate
                    </button>
                  </div>
                </div>
                {tradeResult && (
                  <div className="bg-black/20 rounded-lg p-3 mt-3">
                    <div className="grid grid-cols-2 gap-4 mb-3">
                      <div>
                        <span className="text-xs text-gray-500">Your MCW Change</span>
                        <div className={`text-lg font-bold ${tradeResult.my_mcw_change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {tradeResult.my_mcw_change >= 0 ? '+' : ''}{tradeResult.my_mcw_change.toFixed(3)}
                        </div>
                      </div>
                      <div>
                        <span className="text-xs text-gray-500">Partner MCW Change</span>
                        <div className={`text-lg font-bold ${tradeResult.partner_mcw_change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {tradeResult.partner_mcw_change >= 0 ? '+' : ''}{tradeResult.partner_mcw_change.toFixed(3)}
                        </div>
                      </div>
                    </div>
                    <div className={`text-xs px-2 py-1 rounded inline-block ${
                      tradeResult.is_positive_sum ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                    }`}>
                      {tradeResult.is_positive_sum ? 'Win-Win Trade' : 'One-Sided Trade'}
                    </div>
                  </div>
                )}
              </div>

              {/* Trade Finder */}
              <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                <h2 className="text-sm font-semibold text-white mb-3">Trade Finder (Auto-Generated)</h2>
                {trades.length > 0 ? (
                  <div className="space-y-2">
                    {trades.map((t, i) => (
                      <div key={i} className="flex items-center gap-3 text-xs py-1.5 border-b border-white/[0.03]">
                        <span className="text-gray-600 w-5">{i + 1}</span>
                        <span className="text-red-400">Give: {t.give_player.full_name} ({t.give_player.primary_position})</span>
                        <span className="text-gray-600">for</span>
                        <span className="text-emerald-400">Get: {t.receive_player.full_name} ({t.receive_player.primary_position})</span>
                        <span className="ml-auto text-gray-400">
                          You: <span className={t.my_mcw_gain >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                            {t.my_mcw_gain >= 0 ? '+' : ''}{t.my_mcw_gain.toFixed(3)}
                          </span>
                          {' / '}
                          Them: <span className={t.partner_mcw_gain >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                            {t.partner_mcw_gain >= 0 ? '+' : ''}{t.partner_mcw_gain.toFixed(3)}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-gray-500">No trade opportunities found. Sync data first.</p>
                )}
              </div>
            </div>
          )}

          {/* Signals Tab */}
          {activeTab === 'signals' && (
            <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-white/[0.06]">
                    <th className="text-left px-3 py-2 text-gray-500 font-medium">Type</th>
                    <th className="text-left px-3 py-2 text-gray-500 font-medium">Player</th>
                    <th className="text-left px-3 py-2 text-gray-500 font-medium">Pos</th>
                    <th className="text-left px-3 py-2 text-gray-500 font-medium">Severity</th>
                    <th className="text-right px-3 py-2 text-gray-500 font-medium">MCW</th>
                    <th className="text-left px-3 py-2 text-gray-500 font-medium">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.map((sig, i) => (
                    <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                      <td className="px-3 py-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                          sig.signal_type === 'add_target' ? 'bg-emerald-500/20 text-emerald-400' :
                          sig.signal_type === 'drop_candidate' ? 'bg-red-500/20 text-red-400' :
                          'bg-amber-500/20 text-amber-400'
                        }`}>{sig.action}</span>
                      </td>
                      <td className="px-3 py-2 text-white font-medium">{sig.full_name}</td>
                      <td className={`px-3 py-2 ${posColors[sig.primary_position] || 'text-gray-400'}`}>{sig.primary_position}</td>
                      <td className="px-3 py-2">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          sig.severity === 'high' ? 'bg-red-500/20 text-red-400' :
                          sig.severity === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                          'bg-white/5 text-gray-400'
                        }`}>{sig.severity}</span>
                      </td>
                      <td className={`px-3 py-2 text-right font-mono ${mcwBg(sig.mcw)}`}>{sig.mcw.toFixed(3)}</td>
                      <td className="px-3 py-2 text-gray-500">{sig.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {signals.length === 0 && (
                <div className="text-center py-8 text-gray-500 text-xs">
                  No signals detected. Sync data first.
                </div>
              )}
            </div>
          )}
        </>
      )}

      {!isConfigured && !loading && (
        <div className="text-center py-12">
          <p className="text-gray-500 text-sm">Enter your ESPN league ID and team ID above to get started.</p>
        </div>
      )}
    </div>
  )
}
