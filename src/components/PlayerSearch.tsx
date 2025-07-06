'use client'

import { useState } from 'react'
import { MLBPlayer } from '@/lib/mlb-api'

interface PlayerSearchProps {
  onPlayerSelect: (player: MLBPlayer) => void
}

export default function PlayerSearch({ onPlayerSelect }: PlayerSearchProps) {
  const [searchTerm, setSearchTerm] = useState('')
  const [players, setPlayers] = useState<MLBPlayer[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!searchTerm.trim()) return

    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/players/search?name=${encodeURIComponent(searchTerm)}`)
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Failed to search players')
      }

      setPlayers(data.players)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="w-full max-w-2xl mx-auto">
      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex gap-2">
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search for a player (e.g., Mike Trout)"
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={loading}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>
      </form>

      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-700">{error}</p>
        </div>
      )}

      {players.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-lg font-semibold text-gray-800">Search Results:</h3>
          <div className="grid gap-2">
            {players.map((player) => (
              <button
                key={player.id}
                onClick={() => onPlayerSelect(player)}
                className="p-4 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 text-left transition-colors"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <h4 className="font-semibold text-gray-900">{player.fullName}</h4>
                    <p className="text-sm text-gray-600">
                      {player.primaryPosition?.name} • #{player.primaryNumber}
                    </p>
                    <p className="text-xs text-gray-500">
                      {player.birthCity}, {player.birthStateProvince} • Age {player.currentAge}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-medium text-gray-700">
                      {player.batSide?.code}/{player.pitchHand?.code}
                    </p>
                    <p className="text-xs text-gray-500">
                      {player.height} • {player.weight} lbs
                    </p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}