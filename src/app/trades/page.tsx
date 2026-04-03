'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
import Link from 'next/link'

interface League {
  id: string
  name: string
  platform: string
  season: string
  externalId?: string
}

interface Team {
  id: string
  externalId: string
  name: string
  ownerName?: string
}

interface TradePlayerInfo {
  mlb_id: number
  name: string
  position: string
  total_zscore: number
  weight: number          // current weight on source team (1.0=starter, 0.25=bench hitter)
  incoming_weight: number // projected weight on destination team
}

interface DraftPickAdjustment {
  round: number
  giving_team: string
  zscore_value: number
}

interface TradeSuggestion {
  partner_team_id: number
  partner_team_name: string
  my_players_out: TradePlayerInfo[]
  their_players_out: TradePlayerInfo[]
  draft_pick_adjustment: DraftPickAdjustment | null
  my_delta_wins: number
  their_delta_wins: number
  fairness_score: number
  acceptance_probability: number
  my_category_impact: Record<string, number>
  their_category_impact: Record<string, number>
  trade_type: string
}

interface TradeResults {
  baseline_expected_wins: number
  baseline_category_probs: Record<string, number>
  suggestions: TradeSuggestion[]
  computation_stats: {
    trades_evaluated: number
    trades_pruned: number
    suggestions_found: number
    opponent_teams: number
  }
  my_team_name: string
  team_names: Record<number, string>
}

const CATS = ['R', 'TB', 'RBI', 'SB', 'OBP', 'K', 'QS', 'ERA', 'WHIP', 'SVHD']
const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH', 'SP', 'RP']
const TRADE_TYPES = ['1-for-1', '2-for-1', '2-for-2']

const posColors: Record<string, string> = {
  C: 'text-blue-400', '1B': 'text-amber-400', '2B': 'text-orange-400', '3B': 'text-purple-400',
  SS: 'text-red-400', OF: 'text-emerald-400', LF: 'text-emerald-400', CF: 'text-teal-400',
  RF: 'text-emerald-400', DH: 'text-gray-400', SP: 'text-sky-400', RP: 'text-pink-400',
  P: 'text-teal-400',
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

function acceptColor(p: number): string {
  if (p >= 0.6) return 'text-emerald-400'
  if (p >= 0.4) return 'text-yellow-400'
  return 'text-red-400'
}

function roleTag(weight: number): { label: string; color: string } {
  if (weight >= 1.0) return { label: 'Starter', color: 'text-emerald-400/60' }
  return { label: 'Bench', color: 'text-yellow-400/60' }
}

function effectiveZscore(zscore: number, weight: number): string {
  if (weight >= 1.0) return `z${zscore.toFixed(1)}`
  const effective = zscore * weight
  return `z${effective.toFixed(1)} (bench)`
}

const STORAGE_KEY = 'trade_settings'

interface TradeSettings {
  leagueId: string
  teamId: string
  max_trade_size: number
  fairness_threshold: number
  include_draft_picks: boolean
}

function loadSettings(): TradeSettings | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const s = JSON.parse(raw)
    if (s.leagueId && s.teamId) return s
    return null
  } catch { return null }
}

function saveSettings(s: TradeSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
}

type TabView = 'best' | 'by-partner' | 'by-player'

export default function TradesPage() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState('')
  const [selectedTeam, setSelectedTeam] = useState('')
  const [hasCredentials, setHasCredentials] = useState<boolean | null>(null)
  const [maxTradeSize, setMaxTradeSize] = useState(2)
  const [fairnessThreshold, setFairnessThreshold] = useState(0.5)
  const [includeDraftPicks, setIncludeDraftPicks] = useState(false)
  const [editing, setEditing] = useState(false)
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<TradeResults | null>(null)
  const [activeTab, setActiveTab] = useState<TabView>('best')
  const [posFilter, setPosFilter] = useState('All')
  const [tradeTypeFilter, setTradeTypeFilter] = useState<Set<string>>(new Set(TRADE_TYPES))
  const [minAcceptance, setMinAcceptance] = useState(0)
  const [expandedTrade, setExpandedTrade] = useState<number | null>(null)

  // Load leagues and stored settings
  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        setLeagues(data)
        const saved = loadSettings()
        if (saved) {
          setSelectedLeague(saved.leagueId)
          setSelectedTeam(saved.teamId)
          setMaxTradeSize(saved.max_trade_size ?? 2)
          setFairnessThreshold(saved.fairness_threshold ?? 0.5)
          setIncludeDraftPicks(saved.include_draft_picks ?? false)
          setSettingsLoaded(true)
        } else {
          setEditing(true)
        }
      })
      .catch(() => { setEditing(true) })
  }, [])

  // Load teams when league changes
  useEffect(() => {
    if (!selectedLeague) return
    fetch(`/api/leagues/${selectedLeague}/teams`)
      .then((r) => r.ok ? r.json() : { teams: [] })
      .then((data) => setTeams(data.teams || []))
      .catch(() => {})
  }, [selectedLeague])

  // Check credentials when league changes
  useEffect(() => {
    if (!selectedLeague) { setHasCredentials(null); return }
    fetch(`/api/leagues/${selectedLeague}/credentials`)
      .then((r) => r.ok ? r.json() : { has_credentials: false })
      .then((data) => setHasCredentials(!!data.has_credentials))
      .catch(() => setHasCredentials(false))
  }, [selectedLeague])

  // Auto-fetch when settings restored
  const autoFetched = useRef(false)
  useEffect(() => {
    if (settingsLoaded && !autoFetched.current && selectedLeague && selectedTeam && hasCredentials) {
      autoFetched.current = true
      handleFetchSuggestions()
    }
  }, [settingsLoaded, selectedLeague, selectedTeam, hasCredentials])

  const hasAllSettings = !!(selectedLeague && selectedTeam && hasCredentials)

  const handleSaveSettings = () => {
    if (selectedLeague && selectedTeam) {
      saveSettings({
        leagueId: selectedLeague, teamId: selectedTeam,
        max_trade_size: maxTradeSize,
        fairness_threshold: fairnessThreshold,
        include_draft_picks: includeDraftPicks,
      })
      setEditing(false)
      setSettingsLoaded(true)
    }
  }

  const leagueName = leagues.find((l) => l.id === selectedLeague)?.name
  const teamName = teams.find((t) => t.externalId === selectedTeam)?.name

  const handleFetchSuggestions = async () => {
    if (!selectedLeague || !selectedTeam) {
      setError('Please select a league and team')
      return
    }
    if (!hasCredentials) {
      setError('ESPN credentials not configured. Set them up in Settings.')
      return
    }

    setLoading(true)
    setError(null)
    setResults(null)

    try {
      const response = await fetch('/api/trades/suggestions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: selectedLeague,
          teamId: selectedTeam,
          max_trade_size: maxTradeSize,
          fairness_threshold: fairnessThreshold,
          include_draft_picks: includeDraftPicks,
        }),
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || `Error ${response.status}`)
      }

      const data = await response.json()
      setResults(data)
    } catch (err: any) {
      setError(err.message || 'Failed to fetch trade suggestions')
    } finally {
      setLoading(false)
    }
  }

  // Filtered suggestions
  const filteredSuggestions = useMemo(() => {
    if (!results) return []
    return results.suggestions.filter((s) => {
      if (!tradeTypeFilter.has(s.trade_type)) return false
      if (s.acceptance_probability < minAcceptance) return false
      if (posFilter !== 'All') {
        const allPositions = [...s.their_players_out, ...s.my_players_out].map((p) => p.position)
        const match = posFilter === 'OF'
          ? allPositions.some((p) => ['OF', 'LF', 'CF', 'RF'].includes(p))
          : allPositions.includes(posFilter)
        if (!match) return false
      }
      return true
    })
  }, [results, tradeTypeFilter, minAcceptance, posFilter])

  // Group by partner
  const byPartner = useMemo(() => {
    const groups = new Map<number, TradeSuggestion[]>()
    for (const s of filteredSuggestions) {
      const list = groups.get(s.partner_team_id) || []
      list.push(s)
      groups.set(s.partner_team_id, list)
    }
    return Array.from(groups.entries())
      .map(([teamId, trades]) => ({ teamId, teamName: trades[0].partner_team_name, trades: trades.slice(0, 5) }))
      .sort((a, b) => (b.trades[0]?.my_delta_wins ?? 0) - (a.trades[0]?.my_delta_wins ?? 0))
  }, [filteredSuggestions])

  // Group by my player
  const byMyPlayer = useMemo(() => {
    const groups = new Map<number, TradeSuggestion[]>()
    for (const s of filteredSuggestions) {
      for (const p of s.my_players_out) {
        const list = groups.get(p.mlb_id) || []
        list.push(s)
        groups.set(p.mlb_id, list)
      }
    }
    return Array.from(groups.entries())
      .map(([mlbId, trades]) => ({
        mlbId,
        playerName: trades[0].my_players_out.find((p) => p.mlb_id === mlbId)?.name || '',
        position: trades[0].my_players_out.find((p) => p.mlb_id === mlbId)?.position || '',
        trades: trades.sort((a, b) => b.my_delta_wins - a.my_delta_wins).slice(0, 5),
      }))
      .sort((a, b) => b.trades.length - a.trades.length)
  }, [filteredSuggestions])

  const toggleTradeType = (tt: string) => {
    setTradeTypeFilter((prev) => {
      const next = new Set(prev)
      if (next.has(tt)) next.delete(tt)
      else next.add(tt)
      return next
    })
  }

  const renderTradeCard = (s: TradeSuggestion, idx: number) => {
    const isExpanded = expandedTrade === idx
    return (
      <div
        key={idx}
        className="bg-[#161b22] border border-white/[0.06] rounded-lg overflow-hidden"
      >
        <div
          className="p-3 cursor-pointer hover:bg-white/[0.02]"
          onClick={() => setExpandedTrade(isExpanded ? null : idx)}
        >
          <div className="flex items-center justify-between gap-4">
            {/* Left: players I send */}
            <div className="flex-1 min-w-0">
              <div className="text-[10px] text-red-400/60 uppercase tracking-wider mb-1">I Send</div>
              {s.my_players_out.map((p) => (
                <div key={p.mlb_id} className="flex items-center gap-1.5">
                  <Link
                    href={`/player/${p.mlb_id}`}
                    className="text-sm text-white font-medium hover:underline hover:text-blue-300 truncate"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {p.name}
                  </Link>
                  <span className={`text-xs ${posColors[p.position] || 'text-gray-400'}`}>{p.position}</span>
                  <span className={`text-[10px] ${roleTag(p.weight).color} font-medium`}>{roleTag(p.weight).label}</span>
                  <span className="text-[10px] text-gray-600 font-mono">{effectiveZscore(p.total_zscore, p.weight)}</span>
                  {p.incoming_weight !== p.weight && (
                    <span className="text-[10px] text-gray-500 font-mono">→ {p.incoming_weight >= 1 ? 'Starter' : 'Bench'}</span>
                  )}
                </div>
              ))}
            </div>

            {/* Arrow */}
            <div className="text-gray-600 text-lg shrink-0">&#8644;</div>

            {/* Right: players I receive */}
            <div className="flex-1 min-w-0">
              <div className="text-[10px] text-emerald-400/60 uppercase tracking-wider mb-1">I Receive</div>
              {s.their_players_out.map((p) => (
                <div key={p.mlb_id} className="flex items-center gap-1.5">
                  <Link
                    href={`/player/${p.mlb_id}`}
                    className="text-sm text-white font-medium hover:underline hover:text-blue-300 truncate"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {p.name}
                  </Link>
                  <span className={`text-xs ${posColors[p.position] || 'text-gray-400'}`}>{p.position}</span>
                  <span className={`text-[10px] ${roleTag(p.weight).color} font-medium`}>{roleTag(p.weight).label}</span>
                  <span className="text-[10px] text-gray-600 font-mono">{effectiveZscore(p.total_zscore, p.weight)}</span>
                  {p.incoming_weight !== p.weight && (
                    <span className={`text-[10px] font-mono ${p.incoming_weight >= 1 ? 'text-emerald-400/60' : 'text-yellow-400/60'}`}>
                      → {p.incoming_weight >= 1 ? 'Starter' : 'Bench'}
                    </span>
                  )}
                </div>
              ))}
            </div>

            {/* Draft pick badge */}
            {s.draft_pick_adjustment && (
              <div className="shrink-0 px-2 py-0.5 bg-amber-500/10 border border-amber-500/20 rounded text-[10px] text-amber-400">
                +Rd {s.draft_pick_adjustment.round} pick ({s.draft_pick_adjustment.giving_team === 'me' ? 'I give' : 'they give'})
              </div>
            )}

            {/* Stats */}
            <div className="shrink-0 text-right space-y-0.5">
              <div className={`text-sm font-mono font-bold ${s.my_delta_wins > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {fmtDelta(s.my_delta_wins)} wins
              </div>
              <div className="text-[10px] text-gray-500">
                Partner: {fmtDelta(s.their_delta_wins)}
              </div>
              <div className={`text-[10px] font-mono ${acceptColor(s.acceptance_probability)}`}>
                {(s.acceptance_probability * 100).toFixed(0)}% accept
              </div>
            </div>

            {/* Partner name + type */}
            <div className="shrink-0 text-right min-w-[7rem]">
              <div className="text-xs text-gray-400 truncate">{s.partner_team_name}</div>
              <div className="text-[10px] text-gray-600">{s.trade_type}</div>
            </div>
          </div>
        </div>

        {/* Expanded: category impact */}
        {isExpanded && (
          <div className="border-t border-white/[0.06] p-3">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-[10px] text-gray-500 mb-1">My Category Impact</div>
                <div className="flex gap-1.5 flex-wrap">
                  {CATS.map((cat) => {
                    const v = s.my_category_impact[cat] ?? 0
                    return (
                      <div key={cat} className="text-center min-w-[2.5rem]">
                        <div className="text-[9px] text-gray-600">{cat}</div>
                        <div className={`text-xs font-mono ${impactColor(v)}`}>
                          {Math.abs(v) < 0.001 ? '-' : fmtCatImpact(v)}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-gray-500 mb-1">Partner Category Impact</div>
                <div className="flex gap-1.5 flex-wrap">
                  {CATS.map((cat) => {
                    const v = s.their_category_impact[cat] ?? 0
                    return (
                      <div key={cat} className="text-center min-w-[2.5rem]">
                        <div className="text-[9px] text-gray-600">{cat}</div>
                        <div className={`text-xs font-mono ${impactColor(v)}`}>
                          {Math.abs(v) < 0.001 ? '-' : fmtCatImpact(v)}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <main className="min-h-screen bg-[#0d1117] text-gray-300">
      <div className="max-w-[90rem] mx-auto px-4 sm:px-6 py-6">
        <h1 className="text-xl font-bold text-white mb-4">Trade Suggestions</h1>

        {/* Config panel */}
        <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-4 mb-4">
          {settingsLoaded && !editing ? (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4 text-sm">
                <span className="text-gray-500">League:</span>
                <span className="text-white">{leagueName || selectedLeague}</span>
                <span className="text-gray-500">Team:</span>
                <span className="text-white">{teamName || `#${selectedTeam}`}</span>
                <span className="text-gray-500">ESPN:</span>
                {hasCredentials
                  ? <span className="text-emerald-400 text-xs">Connected</span>
                  : <Link href="/settings" className="text-yellow-400 text-xs hover:underline">Not configured — set up in Settings</Link>
                }
                <span className="text-gray-500">Max:</span>
                <span className="text-white text-xs">{maxTradeSize === 1 ? '1-for-1 only' : 'Up to 2-for-2'}</span>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setEditing(true)}
                  className="px-3 py-1 text-xs text-gray-400 hover:text-white border border-white/10 rounded hover:border-white/20"
                >
                  Edit
                </button>
                <button
                  onClick={handleFetchSuggestions}
                  disabled={loading}
                  className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {loading ? 'Analyzing...' : 'Refresh Suggestions'}
                </button>
                {loading && <span className="text-xs text-gray-500">Evaluating trades across all teams...</span>}
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">League</label>
                  <select
                    value={selectedLeague}
                    onChange={(e) => { setSelectedLeague(e.target.value); setSelectedTeam('') }}
                    className="w-full bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
                  >
                    <option value="">Select league...</option>
                    {leagues.map((l) => (
                      <option key={l.id} value={l.id}>{l.name} ({l.season})</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">My Team</label>
                  <select
                    value={selectedTeam}
                    onChange={(e) => setSelectedTeam(e.target.value)}
                    className="w-full bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
                  >
                    <option value="">Select team...</option>
                    {teams.map((t) => (
                      <option key={t.externalId} value={t.externalId}>
                        {t.name}{t.ownerName ? ` (${t.ownerName})` : ''}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {selectedLeague && hasCredentials === false && (
                <div className="mt-2 text-xs text-yellow-400">
                  ESPN credentials not configured for this league.{' '}
                  <Link href="/settings" className="underline hover:text-yellow-300">Set them up in Settings.</Link>
                </div>
              )}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Max Trade Size</label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setMaxTradeSize(1)}
                      className={`px-3 py-1 text-xs rounded ${maxTradeSize === 1 ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                    >
                      1-for-1 only
                    </button>
                    <button
                      onClick={() => setMaxTradeSize(2)}
                      className={`px-3 py-1 text-xs rounded ${maxTradeSize === 2 ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                    >
                      Up to 2-for-2
                    </button>
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    Fairness Threshold: {fairnessThreshold.toFixed(1)}
                  </label>
                  <input
                    type="range"
                    min={0.1}
                    max={1.0}
                    step={0.1}
                    value={fairnessThreshold}
                    onChange={(e) => setFairnessThreshold(parseFloat(e.target.value))}
                    className="w-full accent-blue-500"
                  />
                  <div className="flex justify-between text-[10px] text-gray-600">
                    <span>Strict</span>
                    <span>Loose</span>
                  </div>
                </div>
                <div className="flex items-center gap-2 pt-4">
                  <input
                    type="checkbox"
                    id="draft-picks"
                    checked={includeDraftPicks}
                    onChange={(e) => setIncludeDraftPicks(e.target.checked)}
                    className="accent-blue-500"
                  />
                  <label htmlFor="draft-picks" className="text-xs text-gray-400">Include draft pick compensation</label>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-3">
                <button
                  onClick={() => { handleSaveSettings(); handleFetchSuggestions() }}
                  disabled={loading || !selectedLeague || !selectedTeam || !hasCredentials}
                  className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {loading ? 'Analyzing...' : 'Save & Get Suggestions'}
                </button>
                {settingsLoaded && (
                  <button
                    onClick={() => setEditing(false)}
                    className="px-3 py-1.5 text-sm text-gray-400 hover:text-white"
                  >
                    Cancel
                  </button>
                )}
                {loading && <span className="text-xs text-gray-500">Evaluating trades across all teams...</span>}
              </div>
            </>
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
                <div className="text-xs text-gray-500">Trades Found</div>
                <div className="text-lg font-bold text-emerald-400">
                  {results.suggestions.length}
                </div>
              </div>
              <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3">
                <div className="text-xs text-gray-500">Trades Evaluated</div>
                <div className="text-lg font-bold text-white">{results.computation_stats.trades_evaluated.toLocaleString()}</div>
              </div>
              <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-3">
                <div className="text-xs text-gray-500">Opponent Teams</div>
                <div className="text-lg font-bold text-white">{results.computation_stats.opponent_teams}</div>
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

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3 mb-3">
              {/* Position filter */}
              <div className="flex gap-1">
                {POSITIONS.map((pos) => (
                  <button
                    key={pos}
                    onClick={() => setPosFilter(pos)}
                    className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                      posFilter === pos ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    {pos}
                  </button>
                ))}
              </div>

              <div className="w-px h-4 bg-white/10" />

              {/* Trade type filter */}
              <div className="flex gap-1">
                {TRADE_TYPES.map((tt) => (
                  <button
                    key={tt}
                    onClick={() => toggleTradeType(tt)}
                    className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                      tradeTypeFilter.has(tt) ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    {tt}
                  </button>
                ))}
              </div>

              <div className="w-px h-4 bg-white/10" />

              {/* Min acceptance */}
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-gray-500">Min Accept:</span>
                <select
                  value={minAcceptance}
                  onChange={(e) => setMinAcceptance(parseFloat(e.target.value))}
                  className="bg-[#0d1117] border border-white/10 rounded px-1.5 py-0.5 text-xs text-white"
                >
                  <option value={0}>Any</option>
                  <option value={0.3}>30%+</option>
                  <option value={0.5}>50%+</option>
                  <option value={0.7}>70%+</option>
                </select>
              </div>
            </div>

            {/* Tab navigation */}
            <div className="flex gap-1 mb-3">
              {([
                ['best', 'Best Trades'],
                ['by-partner', 'By Partner'],
                ['by-player', 'By My Player'],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                    activeTab === key
                      ? 'bg-white/10 text-white'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Best Trades view */}
            {activeTab === 'best' && (
              <div className="space-y-2">
                {filteredSuggestions.length === 0 ? (
                  <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-8 text-center text-gray-500">
                    No trades match your filters
                  </div>
                ) : (
                  filteredSuggestions.map((s, i) => renderTradeCard(s, i))
                )}
              </div>
            )}

            {/* By Partner view */}
            {activeTab === 'by-partner' && (
              <div className="space-y-3">
                {byPartner.length === 0 ? (
                  <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-8 text-center text-gray-500">
                    No trades match your filters
                  </div>
                ) : (
                  byPartner.map(({ teamId, teamName, trades }) => (
                    <div key={teamId}>
                      <div className="text-xs text-gray-400 font-medium mb-1.5 px-1">
                        {teamName}
                        <span className="text-gray-600 ml-2">{trades.length} trade{trades.length !== 1 ? 's' : ''}</span>
                      </div>
                      <div className="space-y-1.5">
                        {trades.map((s, i) => renderTradeCard(s, teamId * 1000 + i))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* By My Player view */}
            {activeTab === 'by-player' && (
              <div className="space-y-3">
                {byMyPlayer.length === 0 ? (
                  <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-8 text-center text-gray-500">
                    No trades match your filters
                  </div>
                ) : (
                  byMyPlayer.map(({ mlbId, playerName, position, trades }) => (
                    <div key={mlbId}>
                      <div className="text-xs font-medium mb-1.5 px-1 flex items-center gap-1.5">
                        <Link href={`/player/${mlbId}`} className="text-white hover:underline hover:text-blue-300">
                          {playerName}
                        </Link>
                        <span className={`${posColors[position] || 'text-gray-400'}`}>{position}</span>
                        <span className="text-gray-600">{trades.length} trade{trades.length !== 1 ? 's' : ''}</span>
                      </div>
                      <div className="space-y-1.5">
                        {trades.map((s, i) => renderTradeCard(s, mlbId * 1000 + i))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </>
        )}

        {!results && !loading && !error && (
          <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-8 text-center text-gray-500">
            <p className="mb-2">Select your league and team above to get started. Suggestions load automatically.</p>
            <p className="text-xs">Analyzes all possible trades to find mutually beneficial deals ranked by expected wins improvement.</p>
          </div>
        )}
      </div>
    </main>
  )
}
