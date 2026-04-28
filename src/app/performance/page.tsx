'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
import Link from 'next/link'

interface League {
  id: string
  name: string
  platform: string
  season: string
}

interface Team {
  id: string
  externalId: string
  name: string
  ownerName?: string
}

interface CategoryStat {
  proj_total: number | null
  proj_to_date: number | null
  actual: number | null
  delta_volume: number | null
  proj_rate: number | null
  actual_rate: number | null
  delta_rate: number | null
}

interface PerfRow {
  mlb_id: number
  name: string
  team: string | null
  primary_position: string | null
  eligible_positions: string | null
  player_type: 'hitter' | 'pitcher'
  overall_rank: number | null
  position_rank: number | null
  proj_pa?: number
  actual_pa?: number
  actual_g?: number
  actual_avg?: number | null
  actual_hr?: number
  expected_pa_to_date?: number
  proj_ip?: number
  actual_ip?: number
  actual_gs?: number
  expected_ip_to_date?: number
  categories: Record<string, CategoryStat>
}

interface PerfResponse {
  hitters: PerfRow[]
  pitchers: PerfRow[]
  season_elapsed_fraction: number
  season_elapsed_days: number
  season_total_days: number
  my_team_mlb_ids: number[]
  season: number
}

const HITTER_CATS = ['r', 'tb', 'rbi', 'sb', 'obp'] as const
const PITCHER_CATS = ['k', 'qs', 'era', 'whip', 'svhd'] as const

const CAT_LABEL: Record<string, string> = {
  r: 'R', tb: 'TB', rbi: 'RBI', sb: 'SB', obp: 'OBP',
  k: 'K', qs: 'QS', era: 'ERA', whip: 'WHIP', svhd: 'SVHD',
}

// Categories where lower is better (ERA, WHIP)
const INVERTED = new Set(['era', 'whip'])
// Categories with no meaningful volume framing — only show rate.
const RATE_ONLY = new Set(['obp', 'era', 'whip'])

const POSITIONS_HITTER = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH']
const POSITIONS_PITCHER = ['All', 'SP', 'RP']

const posColors: Record<string, string> = {
  C: 'text-blue-400', '1B': 'text-amber-400', '2B': 'text-orange-400', '3B': 'text-purple-400',
  SS: 'text-red-400', OF: 'text-emerald-400', LF: 'text-emerald-400', CF: 'text-teal-400',
  RF: 'text-emerald-400', DH: 'text-gray-400', SP: 'text-sky-400', RP: 'text-pink-400',
  P: 'text-teal-400',
}

const STORAGE_KEY = 'matchup_league'
const TEAM_KEY = 'matchup_team'

function deltaColor(cat: string, delta: number | null): string {
  if (delta === null || Number.isNaN(delta)) return 'text-gray-600'
  const isGood = INVERTED.has(cat) ? delta < 0 : delta > 0
  const mag = Math.abs(delta)
  if (mag < 0.0005) return 'text-gray-500'
  if (isGood) {
    return mag > 5 ? 'text-emerald-300 font-semibold' : 'text-emerald-400'
  }
  return mag > 5 ? 'text-red-300 font-semibold' : 'text-red-400'
}

function fmtVol(cat: string, v: number | null): string {
  if (v === null || Number.isNaN(v)) return '—'
  if (cat === 'obp' || cat === 'era' || cat === 'whip') return ''  // no volume for rate-only
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(1)}`
}

function fmtRate(cat: string, v: number | null): string {
  if (v === null || Number.isNaN(v)) return '—'
  const sign = v > 0 ? '+' : ''
  if (cat === 'obp' || cat === 'era' || cat === 'whip') return `${sign}${v.toFixed(3)}`
  if (cat === 'k') return `${sign}${v.toFixed(2)}`  // K/9
  return `${sign}${v.toFixed(3)}`
}

function actualLabel(cat: string, row: PerfRow): string {
  const c = row.categories[cat]
  if (!c) return '—'
  if (cat === 'obp') {
    const v = c.actual
    return v === null || v === undefined ? '—' : v.toFixed(3)
  }
  if (cat === 'era' || cat === 'whip') {
    const v = c.actual
    return v === null || v === undefined ? '—' : (cat === 'era' ? v.toFixed(2) : v.toFixed(2))
  }
  const v = c.actual
  return v === null || v === undefined ? '0' : `${v}`
}

function expectedLabel(cat: string, row: PerfRow): string {
  const c = row.categories[cat]
  if (!c) return '—'
  if (cat === 'obp' || cat === 'era' || cat === 'whip') {
    const v = c.proj_rate ?? c.proj_total
    return v === null || v === undefined ? '—' : (cat === 'era' || cat === 'whip' ? Number(v).toFixed(2) : Number(v).toFixed(3))
  }
  const v = c.proj_to_date
  return v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}`
}

function PerformanceTable({
  rows,
  cats,
  framing,
  sortCat,
  sortDir,
  onSortChange,
  myTeamSet,
  highlightMyTeam,
  positionFilter,
  showLimit,
  isPitcher,
}: {
  rows: PerfRow[]
  cats: readonly string[]
  framing: 'volume' | 'rate'
  sortCat: string
  sortDir: 'asc' | 'desc'
  onSortChange: (cat: string) => void
  myTeamSet: Set<number>
  highlightMyTeam: boolean
  positionFilter: string
  showLimit: number
  isPitcher: boolean
}) {
  const filtered = useMemo(() => {
    const base = rows.filter((r) => {
      if (positionFilter === 'All') return true
      const pos = r.primary_position || ''
      const elig = r.eligible_positions || ''
      if (positionFilter === 'OF') {
        return ['OF', 'LF', 'CF', 'RF'].includes(pos) || elig.split('/').some((p) => ['OF', 'LF', 'CF', 'RF'].includes(p))
      }
      return pos === positionFilter || elig.split('/').includes(positionFilter)
    })
    return base
  }, [rows, positionFilter])

  const sorted = useMemo(() => {
    const arr = [...filtered]
    if (sortCat === 'rank') {
      arr.sort((a, b) => {
        const ra = a.overall_rank ?? 99999
        const rb = b.overall_rank ?? 99999
        return sortDir === 'asc' ? ra - rb : rb - ra
      })
      return arr
    }
    arr.sort((a, b) => {
      const ca = a.categories[sortCat]
      const cb = b.categories[sortCat]
      const va = framing === 'volume' ? ca?.delta_volume : ca?.delta_rate
      const vb = framing === 'volume' ? cb?.delta_volume : cb?.delta_rate
      const av = va === null || va === undefined ? (sortDir === 'asc' ? Infinity : -Infinity) : va
      const bv = vb === null || vb === undefined ? (sortDir === 'asc' ? Infinity : -Infinity) : vb
      return sortDir === 'asc' ? av - bv : bv - av
    })
    return arr
  }, [filtered, sortCat, sortDir, framing])

  const visible = sorted.slice(0, showLimit)

  const arrow = (cat: string) => {
    if (sortCat !== cat) return ''
    return sortDir === 'asc' ? ' ▲' : ' ▼'
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-[#0d1117] sticky top-0">
          <tr className="text-gray-400 border-b border-white/10">
            <th className="px-2 py-2 text-left font-medium w-8">#</th>
            <th className="px-2 py-2 text-left font-medium">Player</th>
            <th className="px-2 py-2 text-left font-medium w-12">Pos</th>
            <th className="px-2 py-2 text-left font-medium w-12">Tm</th>
            <th
              className="px-2 py-2 text-right font-medium cursor-pointer hover:text-white whitespace-nowrap"
              onClick={() => onSortChange('rank')}
            >
              Rank{arrow('rank')}
            </th>
            <th className="px-2 py-2 text-right font-medium whitespace-nowrap">
              {isPitcher ? 'IP' : 'PA'} (act/exp)
            </th>
            {cats.map((cat) => (
              <th
                key={cat}
                className="px-2 py-2 text-right font-medium cursor-pointer hover:text-white whitespace-nowrap"
                onClick={() => onSortChange(cat)}
                title={`Sort by Δ${framing === 'volume' ? 'Volume' : 'Rate'} ${CAT_LABEL[cat]}`}
              >
                {CAT_LABEL[cat]}{arrow(cat)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 && (
            <tr>
              <td colSpan={6 + cats.length} className="px-2 py-6 text-center text-gray-500">
                No players match your filters.
              </td>
            </tr>
          )}
          {visible.map((row, i) => {
            const isMine = myTeamSet.has(row.mlb_id)
            const rowBg = highlightMyTeam && isMine
              ? 'bg-blue-500/10'
              : i % 2 === 1 ? 'bg-[#0f172a]/40' : ''
            const pos = row.primary_position || '—'
            const posClass = posColors[pos] || 'text-gray-400'
            const paAct = isPitcher ? row.actual_ip ?? 0 : row.actual_pa ?? 0
            const paExp = isPitcher ? (row.expected_ip_to_date ?? 0) : (row.expected_pa_to_date ?? 0)
            return (
              <tr key={row.mlb_id} className={`border-b border-white/[0.04] ${rowBg}`}>
                <td className="px-2 py-1.5 text-gray-600">{i + 1}</td>
                <td className="px-2 py-1.5">
                  <Link href={`/player/${row.mlb_id}`} className="text-white hover:text-blue-400">
                    {row.name}
                  </Link>
                  {isMine && (
                    <span className="ml-1.5 px-1 py-0.5 text-[10px] bg-blue-500/30 text-blue-200 rounded">
                      mine
                    </span>
                  )}
                </td>
                <td className={`px-2 py-1.5 ${posClass} font-medium`}>{pos}</td>
                <td className="px-2 py-1.5 text-gray-500">{row.team || '—'}</td>
                <td className="px-2 py-1.5 text-right text-gray-400">{row.overall_rank ?? '—'}</td>
                <td className="px-2 py-1.5 text-right text-gray-400 whitespace-nowrap">
                  <span className="text-gray-300">{Number(paAct).toFixed(isPitcher ? 1 : 0)}</span>
                  <span className="text-gray-600"> / {Number(paExp).toFixed(isPitcher ? 1 : 0)}</span>
                </td>
                {cats.map((cat) => {
                  const c = row.categories[cat]
                  const dVol = c?.delta_volume ?? null
                  const dRate = c?.delta_rate ?? null
                  const showVol = !RATE_ONLY.has(cat)
                  return (
                    <td
                      key={cat}
                      className="px-2 py-1.5 text-right whitespace-nowrap"
                      title={`${CAT_LABEL[cat]}: actual ${actualLabel(cat, row)} vs expected ${expectedLabel(cat, row)}`}
                    >
                      {showVol && (
                        <div className={deltaColor(cat, dVol)}>{fmtVol(cat, dVol)}</div>
                      )}
                      <div className={`${deltaColor(cat, dRate)} ${showVol ? 'text-[10px]' : ''}`}>
                        {fmtRate(cat, dRate)}
                      </div>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
      {sorted.length > showLimit && (
        <div className="px-2 py-2 text-xs text-gray-500 text-center">
          Showing {showLimit} of {sorted.length}. Use position filter or &ldquo;Show all&rdquo; to expand.
        </div>
      )}
    </div>
  )
}

export default function PerformancePage() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState<string>('')
  const [selectedTeam, setSelectedTeam] = useState<string>('')
  const [data, setData] = useState<PerfResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null)

  const [myTeamOnly, setMyTeamOnly] = useState(false)
  const [framing, setFraming] = useState<'volume' | 'rate'>('volume')
  const [posFilterH, setPosFilterH] = useState('All')
  const [posFilterP, setPosFilterP] = useState('All')
  const [sortCatH, setSortCatH] = useState<string>('r')
  const [sortDirH, setSortDirH] = useState<'asc' | 'desc'>('asc')
  const [sortCatP, setSortCatP] = useState<string>('era')
  const [sortDirP, setSortDirP] = useState<'asc' | 'desc'>('desc')  // most over-performing ERA = lowest delta
  const [showAll, setShowAll] = useState(false)

  // Load leagues + restore settings
  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        setLeagues(data)
        const savedLeague = localStorage.getItem(STORAGE_KEY) || ''
        const savedTeam = localStorage.getItem(TEAM_KEY) || ''
        if (savedLeague) setSelectedLeague(savedLeague)
        if (savedTeam) setSelectedTeam(savedTeam)
      })
      .catch(() => {})
  }, [])

  // Load teams when league changes
  useEffect(() => {
    if (!selectedLeague) {
      setTeams([])
      return
    }
    fetch(`/api/leagues/${selectedLeague}/teams`)
      .then((r) => (r.ok ? r.json() : { teams: [] }))
      .then((d) => setTeams(d.teams || []))
      .catch(() => {})
  }, [selectedLeague])

  const autoFetched = useRef(false)
  useEffect(() => {
    if (!autoFetched.current && leagues.length > 0) {
      autoFetched.current = true
      handleFetch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagues])

  // Re-fetch when league/team changes (so my-team set updates)
  useEffect(() => {
    if (autoFetched.current) handleFetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLeague, selectedTeam])

  const handleFetch = async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/performance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          season: 2026,
          leagueId: selectedLeague || undefined,
          teamId: selectedTeam || undefined,
        }),
      })
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}))
        throw new Error(j.error || `Error ${resp.status}`)
      }
      const json = await resp.json()
      setData(json)
    } catch (err: any) {
      setError(err.message || 'Failed to load performance')
    } finally {
      setLoading(false)
    }
  }

  const handleRefreshActuals = async () => {
    setRefreshing(true)
    setRefreshStatus('Starting...')
    try {
      const resp = await fetch('/api/performance/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ season: 2026 }),
      })
      if (!resp.ok) {
        const t = await resp.text()
        throw new Error(t || `Error ${resp.status}`)
      }
      const startData = await resp.json()
      if (startData.started === false && startData.reason === 'already_running') {
        setRefreshStatus('Already running...')
      }

      // Poll status until done.
      let last: any = null
      while (true) {
        await new Promise((r) => setTimeout(r, 2000))
        const sResp = await fetch('/api/performance/refresh-status', { cache: 'no-store' })
        if (!sResp.ok) {
          throw new Error(`Status check failed: ${sResp.status}`)
        }
        const s = await sResp.json()
        last = s
        if (s.status === 'running') {
          const pct = s.total ? Math.round((s.done / s.total) * 100) : 0
          setRefreshStatus(`Refreshing... ${s.done}/${s.total} (${pct}%)`)
          continue
        }
        if (s.status === 'completed') {
          setRefreshStatus(
            `Refreshed at ${new Date().toLocaleTimeString()} — ${s.done} updated, ${s.errors} errors`,
          )
          break
        }
        if (s.status === 'failed') {
          throw new Error(s.error_message || 'Refresh failed')
        }
        // Idle (rare race) — assume done.
        break
      }

      await handleFetch()
    } catch (err: any) {
      setRefreshStatus(`Failed: ${err.message}`)
    } finally {
      setRefreshing(false)
    }
  }

  const myTeamSet = useMemo(
    () => new Set(data?.my_team_mlb_ids ?? []),
    [data?.my_team_mlb_ids],
  )

  const filterToMyTeam = (rows: PerfRow[]) =>
    myTeamOnly && myTeamSet.size > 0 ? rows.filter((r) => myTeamSet.has(r.mlb_id)) : rows

  const hitterRows = useMemo(
    () => (data ? filterToMyTeam(data.hitters) : []),
    [data, myTeamOnly, myTeamSet],
  )
  const pitcherRows = useMemo(
    () => (data ? filterToMyTeam(data.pitchers) : []),
    [data, myTeamOnly, myTeamSet],
  )

  const elapsedPct = data ? (data.season_elapsed_fraction * 100).toFixed(0) : '—'
  const showLimit = showAll ? 9999 : 50

  const onSortHitter = (cat: string) => {
    if (sortCatH === cat) {
      setSortDirH(sortDirH === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCatH(cat)
      setSortDirH('asc')  // default ascending = most negative delta first (under-performers)
    }
  }
  const onSortPitcher = (cat: string) => {
    if (sortCatP === cat) {
      setSortDirP(sortDirP === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCatP(cat)
      // For ERA/WHIP, ascending = best (lowest delta). For counting stats, ascending = worst.
      setSortDirP(INVERTED.has(cat) ? 'asc' : 'asc')
    }
  }

  return (
    <main className="min-h-screen bg-[#0d1117] text-gray-300">
      <div className="max-w-[110rem] mx-auto px-4 sm:px-6 py-6">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-bold text-white">Performance vs. Projection</h1>
          {data && (
            <div className="text-xs text-gray-500">
              Season {data.season}: day {data.season_elapsed_days} of {data.season_total_days} ({elapsedPct}% elapsed)
            </div>
          )}
        </div>

        {/* Config panel */}
        <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-4 mb-4">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">League</label>
              <select
                value={selectedLeague}
                onChange={(e) => {
                  const id = e.target.value
                  setSelectedLeague(id)
                  setSelectedTeam('')
                  if (id) localStorage.setItem(STORAGE_KEY, id)
                  else localStorage.removeItem(STORAGE_KEY)
                  localStorage.removeItem(TEAM_KEY)
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
                onChange={(e) => {
                  const id = e.target.value
                  setSelectedTeam(id)
                  if (id) localStorage.setItem(TEAM_KEY, id)
                  else localStorage.removeItem(TEAM_KEY)
                }}
                className="bg-[#0d1117] border border-white/10 rounded px-2 py-1.5 text-sm text-white"
                disabled={!selectedLeague}
              >
                <option value="">Select team...</option>
                {teams.map((t) => (
                  <option key={t.externalId} value={t.externalId}>
                    {t.name}{t.ownerName ? ` (${t.ownerName})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2 pb-1.5">
              <label className="flex items-center gap-1.5 text-xs text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={myTeamOnly}
                  onChange={(e) => setMyTeamOnly(e.target.checked)}
                  disabled={myTeamSet.size === 0}
                />
                My team only
                {myTeamSet.size > 0 && <span className="text-gray-500">({myTeamSet.size})</span>}
              </label>
            </div>
            <div className="flex items-center gap-1 pb-0.5">
              <span className="text-xs text-gray-500 mr-1">Δ framing:</span>
              <button
                onClick={() => setFraming('volume')}
                className={`px-2 py-1 text-xs rounded ${framing === 'volume' ? 'bg-blue-600 text-white' : 'bg-[#0d1117] border border-white/10 text-gray-400 hover:text-white'}`}
                title="actual − (proj × season-elapsed)"
              >
                Volume
              </button>
              <button
                onClick={() => setFraming('rate')}
                className={`px-2 py-1 text-xs rounded ${framing === 'rate' ? 'bg-blue-600 text-white' : 'bg-[#0d1117] border border-white/10 text-gray-400 hover:text-white'}`}
                title="per-PA / per-IP rate of actual − projected"
              >
                Rate
              </button>
            </div>
            <div className="flex items-center gap-2 pb-0.5 ml-auto">
              <button
                onClick={() => setShowAll(!showAll)}
                className="px-3 py-1.5 bg-[#0d1117] border border-white/10 text-gray-300 text-xs font-medium rounded hover:border-white/20 hover:text-white"
              >
                {showAll ? 'Show top 50' : 'Show all'}
              </button>
              <button
                onClick={handleRefreshActuals}
                disabled={refreshing}
                className="px-3 py-1.5 bg-[#0d1117] border border-white/10 text-gray-300 text-xs font-medium rounded hover:border-white/20 hover:text-white disabled:opacity-40"
                title="Re-fetch season-to-date stats from MLB Stats API"
              >
                {refreshing ? 'Refreshing...' : 'Refresh actuals'}
              </button>
              {refreshStatus && (
                <span className={`text-[11px] ${refreshStatus.startsWith('Failed') ? 'text-red-400' : 'text-emerald-400'}`}>
                  {refreshStatus}
                </span>
              )}
            </div>
          </div>
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-500/30 rounded-lg p-3 mb-4 text-sm text-red-400">
            {error}
          </div>
        )}

        {loading && !data && (
          <div className="bg-[#161b22] border border-white/[0.06] rounded-lg p-6 text-center text-sm text-gray-400">
            Loading performance data...
          </div>
        )}

        {data && (
          <>
            {/* Hitters */}
            <section className="bg-[#161b22] border border-white/[0.06] rounded-lg mb-4">
              <div className="px-4 py-3 border-b border-white/[0.06] flex items-center gap-3 flex-wrap">
                <h2 className="text-sm font-semibold text-white">
                  Hitters
                  <span className="ml-2 text-xs text-gray-500 font-normal">
                    ({hitterRows.length} {myTeamOnly ? 'on my team' : 'ranked'})
                  </span>
                </h2>
                <div className="flex items-center gap-1 ml-auto">
                  {POSITIONS_HITTER.map((p) => (
                    <button
                      key={p}
                      onClick={() => setPosFilterH(p)}
                      className={`px-2 py-0.5 text-xs rounded ${posFilterH === p ? 'bg-blue-600 text-white' : 'bg-[#0d1117] border border-white/10 text-gray-400 hover:text-white'}`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
              <PerformanceTable
                rows={hitterRows}
                cats={HITTER_CATS}
                framing={framing}
                sortCat={sortCatH}
                sortDir={sortDirH}
                onSortChange={onSortHitter}
                myTeamSet={myTeamSet}
                highlightMyTeam={!myTeamOnly}
                positionFilter={posFilterH}
                showLimit={showLimit}
                isPitcher={false}
              />
            </section>

            {/* Pitchers */}
            <section className="bg-[#161b22] border border-white/[0.06] rounded-lg">
              <div className="px-4 py-3 border-b border-white/[0.06] flex items-center gap-3 flex-wrap">
                <h2 className="text-sm font-semibold text-white">
                  Pitchers
                  <span className="ml-2 text-xs text-gray-500 font-normal">
                    ({pitcherRows.length} {myTeamOnly ? 'on my team' : 'ranked'})
                  </span>
                </h2>
                <div className="flex items-center gap-1 ml-auto">
                  {POSITIONS_PITCHER.map((p) => (
                    <button
                      key={p}
                      onClick={() => setPosFilterP(p)}
                      className={`px-2 py-0.5 text-xs rounded ${posFilterP === p ? 'bg-blue-600 text-white' : 'bg-[#0d1117] border border-white/10 text-gray-400 hover:text-white'}`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
              <PerformanceTable
                rows={pitcherRows}
                cats={PITCHER_CATS}
                framing={framing}
                sortCat={sortCatP}
                sortDir={sortDirP}
                onSortChange={onSortPitcher}
                myTeamSet={myTeamSet}
                highlightMyTeam={!myTeamOnly}
                positionFilter={posFilterP}
                showLimit={showLimit}
                isPitcher={true}
              />
            </section>

            <div className="mt-4 text-xs text-gray-500 leading-relaxed">
              <strong className="text-gray-400">Volume Δ</strong> = actual − (full-season projection × {elapsedPct}% season elapsed). Captures injury/missed time + slumps.{' '}
              <strong className="text-gray-400">Rate Δ</strong> = actual per-PA (hitters) / per-IP (pitchers, K/9) − projected. Captures pure quality.
              For OBP / ERA / WHIP, only the rate Δ is shown (volume framing isn&apos;t meaningful for rate stats).
              Hover any number for actual vs. expected values.
            </div>
          </>
        )}
      </div>
    </main>
  )
}
