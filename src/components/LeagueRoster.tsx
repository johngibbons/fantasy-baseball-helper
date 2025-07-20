'use client'

import { useState, useEffect, useCallback } from 'react'

interface League {
  id: string
  name: string
  platform: string
  season: string
  teamCount: number
}

interface Team {
  id: string
  name: string
  ownerName: string | null
  wins: number | null
  losses: number | null
  pointsFor: number | null
  pointsAgainst: number | null
}

interface RosterPlayer {
  id: number
  fullName: string
  primaryPosition: string | null
  position: string
  acquisitionType: string | null
  stats?: {
    gamesPlayed: number | null
    homeRuns: number | null
    rbi: number | null
    battingAverage: number | null
    stolenBases: number | null
  }
}

interface LeagueRosterProps {
  league: League
  onBack?: () => void
}

// Helper function to clean up manager names that might be IDs
function cleanManagerName(ownerName: string | null): string | null {
  if (!ownerName) return null
  
  const trimmed = ownerName.trim()
  
  // Check if it looks like a GUID/ID (common patterns)
  const isGuidPattern = /^[\{\(]?[A-F0-9]{8}[-]?[A-F0-9]{4}[-]?[A-F0-9]{4}[-]?[A-F0-9]{4}[-]?[A-F0-9]{12}[\}\)]?$/i
  const isShortIdPattern = /^[A-Z0-9]{8,}$/i
  
  if (isGuidPattern.test(trimmed) || isShortIdPattern.test(trimmed)) {
    // This looks like an ID, not a readable name
    return null
  }
  
  // Check for other non-readable patterns
  if (trimmed.length < 2 || trimmed.includes('$') || trimmed.includes('#')) {
    return null
  }
  
  // If it passes our checks, return the cleaned name
  return trimmed
}

export default function LeagueRoster({ league, onBack }: LeagueRosterProps) {
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null)
  const [roster, setRoster] = useState<RosterPlayer[]>([])
  const [loading, setLoading] = useState(true)
  const [rosterLoading, setRosterLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [showSyncModal, setShowSyncModal] = useState(false)
  const [syncCredentials, setSyncCredentials] = useState({ swid: '', espn_s2: '' })

  const fetchTeams = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      console.log('Fetching teams for league:', league.id)
      
      const response = await fetch(`/api/leagues/${league.id}/teams`)
      const data = await response.json()

      console.log('Teams API response:', { ok: response.ok, status: response.status, data })

      if (!response.ok) {
        throw new Error(data.error || `Failed to fetch teams: ${response.status}`)
      }

      setTeams(data.teams || [])
    } catch (err) {
      console.error('Error fetching teams:', err)
      setError(err instanceof Error ? err.message : 'An error occurred while fetching teams')
    } finally {
      setLoading(false)
    }
  }, [league.id])

  useEffect(() => {
    fetchTeams()
  }, [fetchTeams])

  const fetchRoster = async (team: Team) => {
    try {
      setRosterLoading(true)
      setSelectedTeam(team)
      
      const response = await fetch(`/api/leagues/${league.id}/teams/${team.id}/roster`)
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Failed to fetch roster')
      }

      setRoster(data.roster)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setRosterLoading(false)
    }
  }

  const syncRoster = async () => {
    try {
      console.log('🔄 Starting sync process...')
      console.log('League ID:', league.id)
      console.log('Credentials provided:', { 
        swid: syncCredentials.swid ? 'Present' : 'Missing', 
        espn_s2: syncCredentials.espn_s2 ? 'Present' : 'Missing' 
      })
      
      setSyncing(true)
      setError(null)
      
      console.log('Making sync API request...')
      const response = await fetch(`/api/leagues/${league.id}/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(syncCredentials)
      })
      
      console.log('Sync API response status:', response.status)

      const data = await response.json()
      console.log('Sync API response data:', data)

      if (!response.ok) {
        console.error('Sync API error:', data.error)
        throw new Error(data.error || 'Failed to sync roster data')
      }

      console.log('✅ Sync successful! Refreshing data...')
      
      // Refresh teams and rosters after successful sync
      await fetchTeams()
      if (selectedTeam) {
        await fetchRoster(selectedTeam)
      }

      setShowSyncModal(false)
      setSyncCredentials({ swid: '', espn_s2: '' })
      
      // Show success message briefly
      const successMessage = `Successfully synced ${data.playersProcessed} players!`
      console.log(successMessage)
      setError(null)
      
    } catch (err) {
      console.error('❌ Error syncing roster:', err)
      setError(err instanceof Error ? err.message : 'An error occurred while syncing')
    } finally {
      setSyncing(false)
    }
  }

  const formatStat = (value: number | null, decimals: number = 0): string => {
    if (value === null || value === undefined) return 'N/A'
    return decimals > 0 ? value.toFixed(decimals) : value.toString()
  }

  const getPositionColor = (position: string): string => {
    const colorMap: { [key: string]: string } = {
      'C': 'bg-blue-100 text-blue-800',
      '1B': 'bg-green-100 text-green-800',
      '2B': 'bg-yellow-100 text-yellow-800',
      '3B': 'bg-purple-100 text-purple-800',
      'SS': 'bg-red-100 text-red-800',
      'OF': 'bg-indigo-100 text-indigo-800',
      'UTIL': 'bg-gray-100 text-gray-800',
      'SP': 'bg-orange-100 text-orange-800',
      'RP': 'bg-pink-100 text-pink-800',
      'P': 'bg-teal-100 text-teal-800',
      'BENCH': 'bg-gray-100 text-gray-600'
    }
    return colorMap[position] || 'bg-gray-100 text-gray-800'
  }

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-lg p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-200 rounded w-1/4 mb-4"></div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-24 bg-gray-200 rounded"></div>
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
          <div className="text-red-600 mb-4">
            <h3 className="font-semibold mb-2">Error Loading League Data</h3>
            <p className="text-sm">{error}</p>
          </div>
          <div className="space-x-4">
            <button
              onClick={fetchTeams}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              Try Again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700"
            >
              Refresh Page
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-2xl font-bold text-gray-900">{league.name}</h2>
          <div className="flex gap-2">
            {league.platform === 'ESPN' && (
              <button
                onClick={() => {
                  console.log('🔵 Sync button clicked!')
                  console.log('Current showSyncModal state:', showSyncModal)
                  setShowSyncModal(true)
                  console.log('Set showSyncModal to true')
                }}
                disabled={syncing}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {syncing ? 'Syncing...' : 'Sync Rosters'}
              </button>
            )}
            {onBack && (
              <button
                onClick={onBack}
                className="px-4 py-2 text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                ← Back to Leagues
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4 text-sm text-gray-600">
          <span className="flex items-center">
            <div className={`w-3 h-3 rounded-full mr-2 ${league.platform === 'ESPN' ? 'bg-red-500' : 'bg-purple-500'}`}></div>
            {league.platform}
          </span>
          <span>{league.season} Season</span>
          <span>{league.teamCount} Teams</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Teams List */}
        <div>
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Teams</h3>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {teams.map((team) => (
              <button
                key={team.id}
                onClick={() => fetchRoster(team)}
                className={`w-full p-4 text-left border rounded-lg transition-colors hover:bg-gray-50 ${
                  selectedTeam?.id === team.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200'
                }`}
              >
                <div className="flex justify-between items-start">
                  <div>
                    <h4 className="font-semibold text-gray-900">
                      {team.name && team.name.trim() && team.name !== 'Unknown Team' 
                        ? team.name 
                        : `Team ${team.id.slice(-3)}`}
                    </h4>
                    <p className="text-sm text-gray-600">
                      Manager: {cleanManagerName(team.ownerName) || 'Unknown Manager'}
                    </p>
                  </div>
                  <div className="text-right text-sm">
                    {team.wins !== null && team.losses !== null && (
                      <p className="text-gray-700">{team.wins}-{team.losses}</p>
                    )}
                    {team.pointsFor !== null && (
                      <p className="text-gray-500">{team.pointsFor.toFixed(1)} pts</p>
                    )}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Roster Display */}
        <div>
          {selectedTeam ? (
            <>
              <h3 className="text-lg font-semibold text-gray-800 mb-4">
                {selectedTeam.name} Roster
              </h3>
              {rosterLoading ? (
                <div className="animate-pulse space-y-2">
                  {[...Array(8)].map((_, i) => (
                    <div key={i} className="h-16 bg-gray-200 rounded"></div>
                  ))}
                </div>
              ) : (
                <div className="space-y-2 max-h-96 overflow-y-auto">
                  {roster.length > 0 ? (
                    roster.map((player) => (
                      <div key={`${player.id}-${player.position}`} className="border border-gray-200 rounded-lg p-3">
                        <div className="flex justify-between items-start mb-2">
                          <div>
                            <h4 className="font-semibold text-gray-900">{player.fullName}</h4>
                            <p className="text-sm text-gray-600">
                              {player.primaryPosition} • {player.acquisitionType || 'Unknown'}
                            </p>
                          </div>
                          <span className={`px-2 py-1 rounded-full text-xs font-medium ${getPositionColor(player.position)}`}>
                            {player.position}
                          </span>
                        </div>
                        
                        {player.stats && (
                          <div className="grid grid-cols-4 gap-2 text-xs text-gray-600">
                            <div className="text-center">
                              <p className="font-medium">{formatStat(player.stats.homeRuns)}</p>
                              <p>HR</p>
                            </div>
                            <div className="text-center">
                              <p className="font-medium">{formatStat(player.stats.rbi)}</p>
                              <p>RBI</p>
                            </div>
                            <div className="text-center">
                              <p className="font-medium">{formatStat(player.stats.battingAverage, 3)}</p>
                              <p>AVG</p>
                            </div>
                            <div className="text-center">
                              <p className="font-medium">{formatStat(player.stats.stolenBases)}</p>
                              <p>SB</p>
                            </div>
                          </div>
                        )}
                      </div>
                    ))
                  ) : (
                    <p className="text-gray-500 text-center py-8">
                      No roster data available for this team
                    </p>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <p>Select a team to view their roster</p>
            </div>
          )}
        </div>
      </div>

      {/* Sync Modal */}
      {showSyncModal && (
        <div 
          style={{ 
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            zIndex: 99999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          onClick={() => {
            console.log('Modal backdrop clicked')
            setShowSyncModal(false)
          }}
        >
          <div 
            style={{
              backgroundColor: 'white',
              padding: '20px',
              borderRadius: '8px',
              maxWidth: '400px',
              width: '100%',
              margin: '20px'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              Sync ESPN Roster Data
            </h3>
            <p className="text-sm text-gray-600 mb-4">
              Enter your ESPN credentials to sync the latest roster data from your league.
            </p>
            
            <div className="space-y-4">
              <div>
                <label htmlFor="swid" className="block text-sm font-medium text-gray-700 mb-1">
                  ESPN SWID
                </label>
                <input
                  id="swid"
                  type="text"
                  value={syncCredentials.swid}
                  onChange={(e) => setSyncCredentials(prev => ({ ...prev, swid: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Enter your SWID"
                />
              </div>
              
              <div>
                <label htmlFor="espn_s2" className="block text-sm font-medium text-gray-700 mb-1">
                  ESPN S2
                </label>
                <input
                  id="espn_s2"
                  type="password"
                  value={syncCredentials.espn_s2}
                  onChange={(e) => setSyncCredentials(prev => ({ ...prev, espn_s2: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Enter your ESPN S2 cookie"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setShowSyncModal(false)
                  setSyncCredentials({ swid: '', espn_s2: '' })
                }}
                disabled={syncing}
                className="px-4 py-2 text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  console.log('🟢 Modal sync button clicked!')
                  syncRoster()
                }}
                disabled={syncing || !syncCredentials.swid || !syncCredentials.espn_s2}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {syncing ? 'Syncing...' : 'Sync Rosters'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}