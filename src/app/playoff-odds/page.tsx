'use client'

import { useEffect, useState } from 'react'

interface TeamOdds {
  team_id: number
  team_name: string
  current_wins: number
  current_losses: number
  current_ties: number
  playoff_odds: number
  avg_final_wins: number
  avg_final_losses: number
  avg_final_ties: number
  avg_final_rank: number
}

interface SimResponse {
  teams: TeamOdds[]
  n_trials: number
  matched_player_count: number
  unmatched_player_names: string[]
  meta: {
    current_matchup_period: number
    final_regular_season_period: number
    playoff_slots: number
    n_trials: number
  }
}

export default function PlayoffOddsPage() {
  const [leagueId, setLeagueId] = useState<string | null>(null)
  const [myTeamId, setMyTeamId] = useState<number | null>(null)
  const [nTrials, setNTrials] = useState(5000)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<SimResponse | null>(null)

  useEffect(() => {
    setLeagueId(localStorage.getItem('matchup_league'))
    const tid = localStorage.getItem('matchup_team')
    setMyTeamId(tid ? parseInt(tid) : null)
  }, [])

  const run = async () => {
    if (!leagueId) {
      setError('Select a league in Settings first.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/playoff-odds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ leagueId, nTrials }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error || `HTTP ${res.status}`)
      }
      const json = (await res.json()) as SimResponse
      setData(json)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-[#0d1117] text-gray-300">
      <div className="max-w-5xl mx-auto px-4 py-6">
        <h1 className="text-xl font-bold text-white mb-2">Playoff Odds</h1>
        <p className="text-sm text-gray-400 mb-5">
          Monte Carlo simulation of the remaining regular season. Top{' '}
          {data?.meta?.playoff_slots ?? 6} teams make the playoffs.
        </p>

        <div className="flex flex-wrap items-center gap-3 mb-6">
          <label className="text-sm text-gray-400">Trials:</label>
          <input
            type="number"
            value={nTrials}
            onChange={e => setNTrials(parseInt(e.target.value) || 1000)}
            min={100}
            max={50000}
            step={500}
            className="bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white w-24"
          />
          <button
            onClick={run}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-4 py-1.5 rounded-md text-sm font-medium transition-colors"
          >
            {loading ? 'Simulating\u2026' : 'Run simulation'}
          </button>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mb-4 text-red-400 text-sm">
            {error}
          </div>
        )}

        {data && (
          <>
            <div className="text-xs text-gray-500 mb-3">
              {data.n_trials} trials &middot; {data.matched_player_count} players matched
              {data.unmatched_player_names.length > 0 &&
                ` \u00b7 ${data.unmatched_player_names.length} unmatched`}
            </div>
            <div className="bg-[#1e293b] rounded-lg overflow-hidden border border-white/[0.06]">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/[0.06] text-xs text-gray-500 uppercase tracking-wide">
                    <th className="text-left px-3 py-2 w-8">#</th>
                    <th className="text-left px-3 py-2">Team</th>
                    <th className="text-right px-3 py-2">Current</th>
                    <th className="text-right px-3 py-2">Proj. Final</th>
                    <th className="text-right px-3 py-2">Avg Rank</th>
                    <th className="text-right px-3 py-2">Playoff %</th>
                  </tr>
                </thead>
                <tbody>
                  {data.teams.map((t, i) => {
                    const isMe = t.team_id === myTeamId
                    const inPlayoffs = i < (data.meta?.playoff_slots ?? 6)
                    return (
                      <tr
                        key={t.team_id}
                        className={`border-b border-white/[0.04] hover:bg-white/[0.02] ${
                          isMe ? 'bg-purple-500/10' : ''
                        }`}
                      >
                        <td className="px-3 py-2 text-gray-500 font-mono">{i + 1}</td>
                        <td className="px-3 py-2">
                          <span className={isMe ? 'text-purple-300 font-semibold' : 'text-white'}>
                            {t.team_name}
                          </span>
                          {isMe && <span className="text-purple-400 text-xs ml-1.5">(you)</span>}
                        </td>
                        <td className="text-right px-3 py-2 text-gray-300 font-mono">
                          {t.current_wins}-{t.current_losses}-{t.current_ties}
                        </td>
                        <td className="text-right px-3 py-2 text-gray-400 font-mono">
                          {t.avg_final_wins.toFixed(1)}-
                          {t.avg_final_losses.toFixed(1)}-
                          {t.avg_final_ties.toFixed(1)}
                        </td>
                        <td className="text-right px-3 py-2 text-gray-400 font-mono">
                          {t.avg_final_rank.toFixed(2)}
                        </td>
                        <td
                          className={`text-right px-3 py-2 font-mono font-bold ${
                            inPlayoffs ? 'text-emerald-400' : 'text-gray-500'
                          }`}
                        >
                          {(t.playoff_odds * 100).toFixed(1)}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </main>
  )
}
