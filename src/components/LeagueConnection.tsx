'use client'

import { useState } from 'react'

interface LeagueConnectionProps {
  onLeagueConnected: (league: any) => void
}

export default function LeagueConnection({ onLeagueConnected }: LeagueConnectionProps) {
  const [platform, setPlatform] = useState<'ESPN' | 'YAHOO' | ''>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [step, setStep] = useState<'platform' | 'credentials' | 'league'>('platform')

  // ESPN credentials
  const [espnLeagueId, setEspnLeagueId] = useState('')
  const [espnSwid, setEspnSwid] = useState('')
  const [espnS2, setEspnS2] = useState('')
  const [espnSeason, setEspnSeason] = useState('2025')

  // Yahoo credentials
  const [yahooAccessToken, setYahooAccessToken] = useState('')
  const [yahooSeason, setYahooSeason] = useState('2025')

  const handlePlatformSelect = (selectedPlatform: 'ESPN' | 'YAHOO') => {
    setPlatform(selectedPlatform)
    setStep('credentials')
    setError(null)
  }

  const handleESPNTest = async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await fetch('/api/leagues/espn/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: espnLeagueId,
          season: espnSeason,
          swid: espnSwid,
          espn_s2: espnS2
        })
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Test failed')
      }

      // Show test results in console and alert
      console.log('ESPN API Test Results:', data)
      
      const successfulTests = data.results.filter((r: any) => r.success)
      if (successfulTests.length > 0) {
        alert(`✅ Success! Found working configuration:\n${JSON.stringify(successfulTests[0].testCase, null, 2)}\n\nCheck console for full details.`)
      } else {
        const errorMessages = data.results.map((r: any) => 
          `${r.testCase?.game}/${r.testCase?.season}: ${r.status || 'Error'} - ${r.dataPreview || r.error || 'Unknown'}`
        ).join('\n')
        setError(`All tests failed:\n${errorMessages}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test failed')
    } finally {
      setLoading(false)
    }
  }

  const handleESPNConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const response = await fetch('/api/leagues/espn/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: espnLeagueId,
          season: espnSeason,
          swid: espnSwid,
          espn_s2: espnS2
        })
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Failed to connect to ESPN league')
      }

      onLeagueConnected(data.league)
      setStep('platform')
      setPlatform('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setLoading(false)
    }
  }

  const handleYahooConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const response = await fetch('/api/leagues/yahoo/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          accessToken: yahooAccessToken,
          season: yahooSeason
        })
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Failed to connect to Yahoo leagues')
      }

      onLeagueConnected(data.leagues)
      setStep('platform')
      setPlatform('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setLoading(false)
    }
  }

  const renderPlatformSelection = () => (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Connect Your Fantasy League</h2>
      <p className="text-gray-600 mb-6">
        Choose your fantasy baseball platform to sync your league data
      </p>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <button
          onClick={() => handlePlatformSelect('ESPN')}
          className="p-6 border-2 border-gray-200 rounded-lg hover:border-red-500 hover:bg-red-50 transition-colors text-left"
        >
          <div className="flex items-center mb-3">
            <div className="w-8 h-8 bg-red-600 rounded-full flex items-center justify-center text-white font-bold mr-3">
              E
            </div>
            <h3 className="text-lg font-semibold text-gray-900">ESPN Fantasy</h3>
          </div>
          <p className="text-sm text-gray-600">
            Connect your ESPN fantasy baseball league using your league ID and authentication cookies
          </p>
        </button>

        <button
          onClick={() => handlePlatformSelect('YAHOO')}
          className="p-6 border-2 border-gray-200 rounded-lg hover:border-purple-500 hover:bg-purple-50 transition-colors text-left"
        >
          <div className="flex items-center mb-3">
            <div className="w-8 h-8 bg-purple-600 rounded-full flex items-center justify-center text-white font-bold mr-3">
              Y
            </div>
            <h3 className="text-lg font-semibold text-gray-900">Yahoo Fantasy</h3>
          </div>
          <p className="text-sm text-gray-600">
            Connect your Yahoo fantasy baseball leagues using OAuth authentication
          </p>
        </button>
      </div>
    </div>
  )

  const renderESPNForm = () => (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <div className="flex items-center mb-6">
        <button
          onClick={() => setStep('platform')}
          className="mr-4 text-gray-600 hover:text-gray-900"
        >
          ← Back
        </button>
        <h2 className="text-2xl font-bold text-gray-900">Connect ESPN League</h2>
      </div>

      <div className="mb-6 p-4 bg-blue-50 rounded-lg">
        <h3 className="font-semibold text-blue-800 mb-2">How to get your ESPN credentials:</h3>
        <ol className="text-sm text-blue-700 space-y-1">
          <li>1. Go to your ESPN fantasy league in a web browser</li>
          <li>2. Open Developer Tools (F12) → Storage/Application → Cookies</li>
          <li>3. Find cookies named "swid" and "espn_s2"</li>
          <li>4. Copy their values (without quotes) and paste below</li>
          <li>5. Your League ID is in the URL: /fba/league?leagueId=<strong>XXXXXX</strong></li>
        </ol>
      </div>

      <form onSubmit={handleESPNConnect} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            League ID
          </label>
          <input
            type="text"
            value={espnLeagueId}
            onChange={(e) => setEspnLeagueId(e.target.value)}
            placeholder="e.g., 123456"
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Season
          </label>
          <select
            value={espnSeason}
            onChange={(e) => setEspnSeason(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500"
          >
            <option value="2025">2025</option>
            <option value="2024">2024</option>
            <option value="2023">2023</option>
            <option value="2022">2022</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            SWID Cookie
          </label>
          <input
            type="text"
            value={espnSwid}
            onChange={(e) => setEspnSwid(e.target.value)}
            placeholder="e.g., {ABC123-DEF4-567G-HIJ8-KLMNOPQRSTUV}"
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            ESPN_S2 Cookie
          </label>
          <textarea
            value={espnS2}
            onChange={(e) => setEspnS2(e.target.value)}
            placeholder="Long string starting with AE..."
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500"
            required
          />
        </div>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        )}

        <div className="space-y-2">
          <button
            type="button"
            onClick={handleESPNTest}
            disabled={loading}
            className="w-full px-4 py-2 bg-yellow-600 text-white rounded-md hover:bg-yellow-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Testing...' : 'Test ESPN Connection'}
          </button>
          
          <button
            type="submit"
            disabled={loading}
            className="w-full px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Connecting...' : 'Connect ESPN League'}
          </button>
        </div>
      </form>
    </div>
  )

  const renderYahooForm = () => (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <div className="flex items-center mb-6">
        <button
          onClick={() => setStep('platform')}
          className="mr-4 text-gray-600 hover:text-gray-900"
        >
          ← Back
        </button>
        <h2 className="text-2xl font-bold text-gray-900">Connect Yahoo Leagues</h2>
      </div>

      <div className="mb-6 p-4 bg-yellow-50 rounded-lg">
        <h3 className="font-semibold text-yellow-800 mb-2">Yahoo OAuth Setup Required:</h3>
        <p className="text-sm text-yellow-700">
          Yahoo requires OAuth authentication. For now, you'll need to get an access token manually from the Yahoo Developer Console. 
          Full OAuth flow will be implemented in a future update.
        </p>
      </div>

      <form onSubmit={handleYahooConnect} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Season
          </label>
          <select
            value={yahooSeason}
            onChange={(e) => setYahooSeason(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500"
          >
            <option value="2025">2025</option>
            <option value="2024">2024</option>
            <option value="2023">2023</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Access Token
          </label>
          <textarea
            value={yahooAccessToken}
            onChange={(e) => setYahooAccessToken(e.target.value)}
            placeholder="Your Yahoo OAuth access token"
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500"
            required
          />
        </div>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Connecting...' : 'Connect Yahoo Leagues'}
        </button>
      </form>
    </div>
  )

  if (step === 'platform') {
    return renderPlatformSelection()
  }

  if (platform === 'ESPN') {
    return renderESPNForm()
  }

  if (platform === 'YAHOO') {
    return renderYahooForm()
  }

  return null
}