'use client'

import { Suspense, useState, useEffect } from 'react'
import Link from 'next/link'
import { useSearchParams, useRouter, usePathname } from 'next/navigation'
import ProjectionsTab from './_components/ProjectionsTab'
import HotTab from './_components/HotTab'
import StealthTab from './_components/StealthTab'

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

const STORAGE_KEY = 'waiver_settings'

function loadSettings(): { leagueId: string; teamId: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const s = JSON.parse(raw)
    if (s.leagueId && s.teamId) return { leagueId: s.leagueId, teamId: s.teamId }
    return null
  } catch { return null }
}

function saveSettings(leagueId: string, teamId: string) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ leagueId, teamId }))
}

type TabKey = 'projections' | 'hot' | 'stealth'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'projections', label: 'Projections-Based' },
  { key: 'hot', label: 'Hot + Sustainable' },
  { key: 'stealth', label: 'Stealth Breakouts' },
]

function WaiversShell() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const tabParam = searchParams.get('tab')
  const tab: TabKey =
    tabParam === 'hot' || tabParam === 'stealth' || tabParam === 'projections'
      ? (tabParam as TabKey)
      : 'projections'

  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState<string>('')
  const [selectedTeam, setSelectedTeam] = useState<string>('')
  const [credentialsOk, setCredentialsOk] = useState<boolean | null>(null)

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
        }
      })
      .catch(() => {})
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
    if (!selectedLeague) { setCredentialsOk(null); return }
    fetch(`/api/leagues/${selectedLeague}/credentials`)
      .then((r) => r.ok ? r.json() : { has_credentials: false })
      .then((data) => setCredentialsOk(data.has_credentials === true))
      .catch(() => setCredentialsOk(false))
  }, [selectedLeague])

  // Persist league/team to localStorage when both selected
  useEffect(() => {
    if (selectedLeague && selectedTeam) {
      saveSettings(selectedLeague, selectedTeam)
    }
  }, [selectedLeague, selectedTeam])

  const setTab = (next: TabKey) => {
    const params = new URLSearchParams(Array.from(searchParams.entries()))
    if (next === 'projections') {
      params.delete('tab')
    } else {
      params.set('tab', next)
    }
    const qs = params.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname)
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center gap-4">
        <h1 className="text-xl font-semibold">Waiver Wire</h1>
        <Link href="/" className="text-sm text-gray-400 hover:text-gray-200">← Home</Link>
      </header>

      <div className="px-6 py-3 border-b border-gray-800 flex flex-col sm:flex-row gap-3 sm:items-center">
        <div>
          <label className="block text-xs text-gray-500 mb-1">League</label>
          <select
            value={selectedLeague}
            onChange={(e) => {
              const id = e.target.value
              setSelectedLeague(id)
              setSelectedTeam('')
            }}
            className="bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
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
            className="bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
          >
            <option value="">Select team...</option>
            {teams.map((t) => (
              <option key={t.externalId} value={t.externalId}>
                {t.name}{t.ownerName ? ` (${t.ownerName})` : ''}
              </option>
            ))}
          </select>
        </div>
        {selectedLeague && credentialsOk === true && (
          <span className="text-xs text-emerald-400 sm:pb-1.5 sm:self-end">ESPN: Connected</span>
        )}
      </div>

      <nav className="px-6 border-b border-gray-800 flex gap-1">
        {TABS.map(({ key, label }) => {
          const active = tab === key
          return (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                active
                  ? 'border-blue-500 text-white'
                  : 'border-transparent text-gray-400 hover:text-gray-200'
              }`}
            >
              {label}
            </button>
          )
        })}
      </nav>

      <div className="p-6">
        {tab === 'projections' && (
          <ProjectionsTab
            selectedLeague={selectedLeague}
            selectedTeam={selectedTeam}
            credentialsOk={credentialsOk}
          />
        )}
        {tab === 'hot' && (
          <HotTab
            selectedLeague={selectedLeague}
            selectedTeam={selectedTeam}
            credentialsOk={credentialsOk}
          />
        )}
        {tab === 'stealth' && (
          <StealthTab
            selectedLeague={selectedLeague}
            selectedTeam={selectedTeam}
            credentialsOk={credentialsOk}
          />
        )}
      </div>
    </div>
  )
}

export default function WaiversPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-950" />}>
      <WaiversShell />
    </Suspense>
  )
}
