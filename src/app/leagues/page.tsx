'use client'

import { useState, useEffect } from 'react'
import LeagueConnection from '@/components/LeagueConnection'
import LeagueRoster from '@/components/LeagueRoster'

interface League {
  id: string
  name: string
  platform: string
  season: string
  teamCount: number
}

export default function LeaguesPage() {
  const [connectedLeagues, setConnectedLeagues] = useState<League[]>([])
  const [selectedLeague, setSelectedLeague] = useState<League | null>(null)

  useEffect(() => {
    const loadExistingLeagues = async () => {
      try {
        const response = await fetch('/api/leagues')
        if (response.ok) {
          const leagues = await response.json()
          setConnectedLeagues(leagues)
        }
      } catch (error) {
        console.error('Error loading existing leagues:', error)
      }
    }
    loadExistingLeagues()
  }, [])

  const handleLeagueConnected = (leagueData: League | League[]) => {
    if (Array.isArray(leagueData)) {
      setConnectedLeagues((prev) => [...prev, ...leagueData])
    } else {
      setConnectedLeagues((prev) => [...prev, leagueData])
    }
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-6">League Integration</h1>

        {connectedLeagues.length > 0 && (
          <div className="mb-8">
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-xl font-semibold text-gray-800 mb-4">Connected Leagues</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {connectedLeagues.map((league) => (
                  <button
                    key={league.id}
                    onClick={() => setSelectedLeague(league)}
                    className={`p-4 border-2 rounded-lg text-left transition-colors ${
                      selectedLeague?.id === league.id
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center mb-2">
                      <div
                        className={`w-3 h-3 rounded-full mr-2 ${
                          league.platform === 'ESPN' ? 'bg-red-500' : 'bg-purple-500'
                        }`}
                      />
                      <span className="text-sm font-medium text-gray-600">{league.platform}</span>
                    </div>
                    <h3 className="font-semibold text-gray-900 mb-1">{league.name}</h3>
                    <p className="text-sm text-gray-600">
                      {league.season} &middot; {league.teamCount} teams
                    </p>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {selectedLeague ? (
          <LeagueRoster league={selectedLeague} onBack={() => setSelectedLeague(null)} />
        ) : (
          <LeagueConnection onLeagueConnected={handleLeagueConnected} />
        )}
      </div>
    </main>
  )
}
