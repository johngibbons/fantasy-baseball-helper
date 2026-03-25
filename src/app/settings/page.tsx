'use client'

import { useState, useEffect } from 'react'

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

interface CredentialStatus {
  has_credentials: boolean
  default_team_id: string | null
}

export default function SettingsPage() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState<string>('')
  const [espnS2, setEspnS2] = useState('')
  const [swid, setSwid] = useState('')
  const [defaultTeamId, setDefaultTeamId] = useState('')
  const [credentialStatus, setCredentialStatus] = useState<CredentialStatus | null>(null)
  const [saving, setSaving] = useState(false)
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [leaguesLoading, setLeaguesLoading] = useState(true)
  const [teamsLoading, setTeamsLoading] = useState(false)

  // Load leagues on mount
  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => r.ok ? r.json() : [])
      .then((data) => setLeagues(data))
      .catch(() => setLeagues([]))
      .finally(() => setLeaguesLoading(false))
  }, [])

  // Load teams and credential status when league changes
  useEffect(() => {
    if (!selectedLeague) {
      setTeams([])
      setCredentialStatus(null)
      setDefaultTeamId('')
      return
    }

    setTeamsLoading(true)
    setCredentialStatus(null)
    setStatusMsg(null)

    Promise.all([
      fetch(`/api/leagues/${selectedLeague}/teams`)
        .then((r) => r.ok ? r.json() : { teams: [] })
        .then((data) => data.teams || []),
      fetch(`/api/leagues/${selectedLeague}/credentials`)
        .then((r) => r.ok ? r.json() : null)
        .catch(() => null),
    ]).then(([teamsData, credData]) => {
      setTeams(teamsData)
      if (credData) {
        setCredentialStatus(credData)
        setDefaultTeamId(credData.default_team_id ?? '')
      }
    }).finally(() => setTeamsLoading(false))
  }, [selectedLeague])

  const handleSave = async () => {
    if (!selectedLeague) {
      setStatusMsg({ type: 'error', text: 'Please select a league.' })
      return
    }
    if (!espnS2.trim() || !swid.trim()) {
      setStatusMsg({ type: 'error', text: 'ESPN S2 and SWID are required.' })
      return
    }

    setSaving(true)
    setStatusMsg(null)

    try {
      const body: Record<string, string> = {
        espn_s2: espnS2.trim(),
        swid: swid.trim(),
      }
      if (defaultTeamId) {
        body.default_team_id = defaultTeamId
      }

      const resp = await fetch(`/api/leagues/${selectedLeague}/credentials`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!resp.ok) {
        const data = await resp.json()
        throw new Error(data.error || `Error ${resp.status}`)
      }

      setCredentialStatus({ has_credentials: true, default_team_id: defaultTeamId || null })
      setEspnS2('')
      setSwid('')
      setStatusMsg({ type: 'success', text: 'Credentials saved successfully.' })
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.message || 'Failed to save credentials.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="min-h-screen bg-[#0d1117] text-gray-300">
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
        <h1 className="text-xl font-bold text-white mb-1">Settings</h1>
        <p className="text-sm text-gray-500 mb-6">Configure ESPN credentials for your leagues.</p>

        <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-6 space-y-5">

          {/* League selector */}
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">League</label>
            <select
              value={selectedLeague}
              onChange={(e) => { setSelectedLeague(e.target.value); setEspnS2(''); setSwid('') }}
              className="w-full bg-[#0d1117] border border-white/10 rounded px-3 py-2 text-sm text-gray-300"
            >
              <option value="">
                {leaguesLoading ? 'Loading leagues...' : 'Select a league...'}
              </option>
              {leagues.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} ({l.season})
                </option>
              ))}
            </select>
          </div>

          {/* Credential status badge */}
          {selectedLeague && !teamsLoading && credentialStatus !== null && (
            <div className={`text-xs px-3 py-2 rounded border ${
              credentialStatus.has_credentials
                ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
                : 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20'
            }`}>
              {credentialStatus.has_credentials
                ? 'Credentials configured for this league.'
                : 'No credentials set for this league.'}
            </div>
          )}

          {/* ESPN S2 Token */}
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">ESPN S2 Token</label>
            <input
              type="text"
              value={espnS2}
              onChange={(e) => setEspnS2(e.target.value)}
              placeholder={credentialStatus?.has_credentials ? 'Enter new value to update...' : 'Paste espn_s2 cookie value...'}
              className="w-full bg-[#0d1117] border border-white/10 rounded px-3 py-2 text-sm text-gray-300 font-mono placeholder:font-sans placeholder:text-gray-600"
            />
          </div>

          {/* SWID */}
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">SWID</label>
            <input
              type="text"
              value={swid}
              onChange={(e) => setSwid(e.target.value)}
              placeholder={credentialStatus?.has_credentials ? 'Enter new value to update...' : 'Paste SWID cookie value (e.g. {GUID})...'}
              className="w-full bg-[#0d1117] border border-white/10 rounded px-3 py-2 text-sm text-gray-300 font-mono placeholder:font-sans placeholder:text-gray-600"
            />
          </div>

          {/* Default Team */}
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">
              Default Team <span className="text-gray-600">(optional)</span>
            </label>
            <select
              value={defaultTeamId}
              onChange={(e) => setDefaultTeamId(e.target.value)}
              disabled={!selectedLeague || teamsLoading}
              className="w-full bg-[#0d1117] border border-white/10 rounded px-3 py-2 text-sm text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <option value="">
                {teamsLoading ? 'Loading teams...' : 'No default team'}
              </option>
              {teams.map((t) => (
                <option key={t.externalId} value={t.externalId}>
                  {t.name}{t.ownerName ? ` (${t.ownerName})` : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Help text */}
          <div className="bg-[#0d1117] border border-white/[0.06] rounded px-4 py-3 text-xs text-gray-500 leading-relaxed">
            <span className="text-gray-400 font-medium">How to find your ESPN credentials: </span>
            Log into ESPN Fantasy, open browser DevTools (F12), go to Application &gt; Cookies, find the{' '}
            <code className="text-gray-300 bg-white/5 px-1 py-0.5 rounded">espn_s2</code> and{' '}
            <code className="text-gray-300 bg-white/5 px-1 py-0.5 rounded">SWID</code> values and paste them above.
          </div>

          {/* Save button and status */}
          <div className="flex items-center gap-4 pt-1">
            <button
              onClick={handleSave}
              disabled={saving || !selectedLeague}
              className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            {statusMsg && (
              <span className={`text-sm ${statusMsg.type === 'success' ? 'text-emerald-400' : 'text-red-400'}`}>
                {statusMsg.text}
              </span>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}
