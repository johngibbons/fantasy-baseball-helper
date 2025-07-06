'use client'

import { useState, useEffect } from 'react'
import { MLBPlayer } from '@/lib/mlb-api'

interface PlayerStatsProps {
  player: MLBPlayer
}

interface PlayerStats {
  id: number
  playerId: number
  season: string
  gamesPlayed: number | null
  atBats: number | null
  runs: number | null
  hits: number | null
  doubles: number | null
  triples: number | null
  homeRuns: number | null
  rbi: number | null
  stolenBases: number | null
  caughtStealing: number | null
  baseOnBalls: number | null
  strikeOuts: number | null
  battingAverage: number | null
  onBasePercentage: number | null
  sluggingPercentage: number | null
  onBasePlusSlugging: number | null
  totalBases: number | null
  hitByPitch: number | null
  intentionalWalks: number | null
  groundIntoDoublePlay: number | null
  leftOnBase: number | null
  plateAppearances: number | null
  babip: number | null
}

export default function PlayerStats({ player }: PlayerStatsProps) {
  const [stats, setStats] = useState<PlayerStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [season, setSeason] = useState('2024')

  useEffect(() => {
    const fetchStats = async () => {
      setLoading(true)
      setError(null)

      try {
        const response = await fetch(`/api/players/${player.id}/stats?season=${season}`)
        const data = await response.json()

        if (!response.ok) {
          throw new Error(data.error || 'Failed to fetch stats')
        }

        setStats(data.stats)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred')
      } finally {
        setLoading(false)
      }
    }

    fetchStats()
  }, [player.id, season])

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-lg p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-200 rounded w-3/4 mb-4"></div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-16 bg-gray-200 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow-lg p-6">
        <div className="text-center">
          <p className="text-red-600 mb-4">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            Try Again
          </button>
        </div>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="bg-white rounded-lg shadow-lg p-6">
        <p className="text-center text-gray-600">No stats available for {player.fullName} in {season}</p>
      </div>
    )
  }

  const formatStat = (value: number | null, decimals: number = 0): string => {
    if (value === null || value === undefined) return 'N/A'
    return decimals > 0 ? value.toFixed(decimals) : value.toString()
  }

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{player.fullName}</h2>
          <p className="text-gray-600">{player.primaryPosition?.name} • #{player.primaryNumber}</p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="season" className="text-sm font-medium text-gray-700">
            Season:
          </label>
          <select
            id="season"
            value={season}
            onChange={(e) => setSeason(e.target.value)}
            className="px-3 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="2024">2024</option>
            <option value="2023">2023</option>
            <option value="2022">2022</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.gamesPlayed)}</p>
          <p className="text-sm text-gray-600">Games</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.battingAverage, 3)}</p>
          <p className="text-sm text-gray-600">AVG</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.homeRuns)}</p>
          <p className="text-sm text-gray-600">HR</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.rbi)}</p>
          <p className="text-sm text-gray-600">RBI</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.runs)}</p>
          <p className="text-sm text-gray-600">Runs</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.stolenBases)}</p>
          <p className="text-sm text-gray-600">SB</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.onBasePercentage, 3)}</p>
          <p className="text-sm text-gray-600">OBP</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.sluggingPercentage, 3)}</p>
          <p className="text-sm text-gray-600">SLG</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.onBasePlusSlugging, 3)}</p>
          <p className="text-sm text-gray-600">OPS</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.hits)}</p>
          <p className="text-sm text-gray-600">Hits</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.doubles)}</p>
          <p className="text-sm text-gray-600">2B</p>
        </div>
        
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <p className="text-2xl font-bold text-gray-900">{formatStat(stats.triples)}</p>
          <p className="text-sm text-gray-600">3B</p>
        </div>
      </div>

      <div className="mt-6 pt-4 border-t border-gray-200">
        <h3 className="text-lg font-semibold text-gray-800 mb-2">Additional Stats</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-gray-600">At Bats:</span>
            <span className="ml-2 font-medium">{formatStat(stats.atBats)}</span>
          </div>
          <div>
            <span className="text-gray-600">Strikeouts:</span>
            <span className="ml-2 font-medium">{formatStat(stats.strikeOuts)}</span>
          </div>
          <div>
            <span className="text-gray-600">Walks:</span>
            <span className="ml-2 font-medium">{formatStat(stats.baseOnBalls)}</span>
          </div>
          <div>
            <span className="text-gray-600">BABIP:</span>
            <span className="ml-2 font-medium">{formatStat(stats.babip, 3)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}