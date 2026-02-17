'use client'

import { useState } from 'react'
import PlayerSearch from '@/components/PlayerSearch'
import PlayerStats from '@/components/PlayerStats'
import { MLBPlayer } from '@/lib/mlb-api'

export default function PlayersPage() {
  const [selectedPlayer, setSelectedPlayer] = useState<MLBPlayer | null>(null)

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-6">Player Search</h1>

        <div className="mb-8">
          <PlayerSearch onPlayerSelect={setSelectedPlayer} />
        </div>

        {selectedPlayer ? (
          <div className="mb-8">
            <PlayerStats player={selectedPlayer} />
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow p-8 text-center">
            <h2 className="text-xl font-semibold text-gray-800 mb-2">
              Search for MLB players
            </h2>
            <p className="text-gray-600">
              View comprehensive stats from the MLB Stats API
            </p>
          </div>
        )}
      </div>
    </main>
  )
}
