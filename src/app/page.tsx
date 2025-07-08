'use client'

import { useState, useEffect } from 'react'
import PlayerSearch from '@/components/PlayerSearch'
import PlayerStats from '@/components/PlayerStats'
import LeagueConnection from '@/components/LeagueConnection'
import LeagueRoster from '@/components/LeagueRoster'
import { MLBPlayer } from '@/lib/mlb-api'

interface League {
  id: string
  name: string
  platform: string
  season: string
  teamCount: number
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<'players' | 'leagues'>('players')
  const [selectedPlayer, setSelectedPlayer] = useState<MLBPlayer | null>(null)
  const [connectedLeagues, setConnectedLeagues] = useState<League[]>([])
  const [selectedLeague, setSelectedLeague] = useState<League | null>(null)

  // Load existing leagues on component mount
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

  const handleLeagueConnected = (leagueData: any) => {
    if (Array.isArray(leagueData)) {
      // Yahoo returns multiple leagues
      setConnectedLeagues(prev => [...prev, ...leagueData])
    } else {
      // ESPN returns single league
      setConnectedLeagues(prev => [...prev, leagueData])
    }
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="container mx-auto px-4 py-8">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">
            Fantasy Baseball Helper ⚾
          </h1>
          <p className="text-lg text-gray-600">
            Your complete fantasy baseball analytics platform
          </p>
        </div>

        {/* Tab Navigation */}
        <div className="max-w-6xl mx-auto mb-8">
          <div className="bg-white rounded-lg shadow-sm p-1 flex">
            <button
              onClick={() => setActiveTab('players')}
              className={`flex-1 py-3 px-4 rounded-md font-medium transition-colors ${
                activeTab === 'players' 
                  ? 'bg-blue-600 text-white' 
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              Player Search & Stats
            </button>
            <button
              onClick={() => setActiveTab('leagues')}
              className={`flex-1 py-3 px-4 rounded-md font-medium transition-colors ${
                activeTab === 'leagues' 
                  ? 'bg-blue-600 text-white' 
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              League Integration
            </button>
          </div>
        </div>

        <div className="max-w-6xl mx-auto">
          {activeTab === 'players' && (
            <>
              <div className="mb-8">
                <PlayerSearch onPlayerSelect={setSelectedPlayer} />
              </div>

              {selectedPlayer ? (
                <div className="mb-8">
                  <PlayerStats player={selectedPlayer} />
                </div>
              ) : (
                <div className="bg-white rounded-lg shadow-lg p-8 text-center">
                  <h2 className="text-2xl font-semibold text-gray-800 mb-4">
                    MLB Data Integration Complete! 🎉
                  </h2>
                  <p className="text-gray-600 mb-6">
                    Search for MLB players and view their comprehensive stats and analytics.
                  </p>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-left">
                    <div className="bg-green-50 p-4 rounded-lg">
                      <h3 className="font-semibold text-green-800 mb-2">✅ Player Features:</h3>
                      <ul className="text-sm text-green-700 space-y-1">
                        <li>• MLB Stats API integration</li>
                        <li>• Real-time player search</li>
                        <li>• Multi-season statistics</li>
                        <li>• Advanced metrics (OPS, BABIP)</li>
                        <li>• Database caching</li>
                      </ul>
                    </div>
                    <div className="bg-blue-50 p-4 rounded-lg">
                      <h3 className="font-semibold text-blue-800 mb-2">🚀 Try searching:</h3>
                      <ul className="text-sm text-blue-700 space-y-1">
                        <li>• &quot;Mike Trout&quot; - Angels superstar</li>
                        <li>• &quot;Aaron Judge&quot; - Yankees slugger</li>
                        <li>• &quot;Mookie Betts&quot; - Dodgers star</li>
                        <li>• &quot;Francisco Lindor&quot; - Mets SS</li>
                        <li>• Any active MLB player</li>
                      </ul>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {activeTab === 'leagues' && (
            <>
              {connectedLeagues.length > 0 && (
                <div className="mb-8">
                  <div className="bg-white rounded-lg shadow-lg p-6">
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
                            <div className={`w-3 h-3 rounded-full mr-2 ${
                              league.platform === 'ESPN' ? 'bg-red-500' : 'bg-purple-500'
                            }`}></div>
                            <span className="text-sm font-medium text-gray-600">{league.platform}</span>
                          </div>
                          <h3 className="font-semibold text-gray-900 mb-1">{league.name}</h3>
                          <p className="text-sm text-gray-600">{league.season} • {league.teamCount} teams</p>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {selectedLeague ? (
                <LeagueRoster 
                  league={selectedLeague} 
                  onBack={() => setSelectedLeague(null)}
                />
              ) : (
                <LeagueConnection onLeagueConnected={handleLeagueConnected} />
              )}
            </>
          )}
        </div>
      </div>
    </main>
  )
}