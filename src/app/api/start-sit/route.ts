import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { getMatchupDateRange, getMatchupEndDateForDate, toLocalDateStr } from '@/lib/matchup-schedule'
import { getTeamGamesInRange } from '@/lib/mlb-schedule'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// ESPN stat ID -> category name mapping
// Verified from league scoring settings (statIds in scoringItems)
const ESPN_STAT_MAP: Record<string, string> = {
  '20': 'R',
  '8': 'TB',
  '21': 'RBI',
  '23': 'SB',
  '17': 'OBP',
  '48': 'K',
  '63': 'QS',
  '47': 'ERA',
  '41': 'WHIP',
  '83': 'SVHD',
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { leagueId, teamId, season = '2026' } = body

    if (!leagueId || !teamId) {
      return NextResponse.json(
        { error: 'Missing required fields: leagueId, teamId' },
        { status: 400 },
      )
    }

    // Look up credentials from DB
    const league = await prisma.league.findUnique({ where: { id: leagueId } })
    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const leagueSettings = league.settings as any
    const credentials = leagueSettings?.credentials
    if (!credentials?.espn_s2 || !credentials?.swid) {
      return NextResponse.json(
        { error: 'ESPN credentials not configured. Set them up in Settings.' },
        { status: 400 },
      )
    }

    const espnSettings = { swid: credentials.swid, espn_s2: credentials.espn_s2 }

    // Fetch league info to get currentMatchupPeriod
    const leagueData = await ESPNApi.getLeague(league.externalId, season, espnSettings)
    const matchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1

    // Fetch roster and matchup scoreboard in parallel
    const [rosters, scoreboard] = await Promise.all([
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getMatchupScoreboard(league.externalId, season, espnSettings, matchupPeriod),
    ])

    const myTeamId = parseInt(teamId)

    // Find user's matchup
    const myMatchup = scoreboard.schedule.find(
      (m) => m.home.teamId === myTeamId || m.away.teamId === myTeamId
    )

    if (!myMatchup) {
      return NextResponse.json(
        { error: 'Could not find your matchup for this week' },
        { status: 404 },
      )
    }

    const isHome = myMatchup.home.teamId === myTeamId
    const mySide = isHome ? myMatchup.home : myMatchup.away
    const theirSide = isHome ? myMatchup.away : myMatchup.home

    // Extract category totals from scoreByStat
    const myStats = mySide.cumulativeScore?.scoreByStat || {}
    const theirStats = theirSide.cumulativeScore?.scoreByStat || {}

    // Helper to sanitize ESPN scores (Infinity/NaN from 0 IP → default)
    const sanitize = (val: number | undefined, fallback: number = 0): number => {
      const v = val ?? fallback
      return Number.isFinite(v) ? v : fallback
    }

    const matchupCategories: Record<string, { yours: number; theirs: number }> = {}
    for (const [statId, catName] of Object.entries(ESPN_STAT_MAP)) {
      // ERA/WHIP default to 0 when no IP (will be handled by low-IP override in engine)
      const fallback = 0
      matchupCategories[catName] = {
        yours: sanitize(myStats[statId]?.score, fallback),
        theirs: sanitize(theirStats[statId]?.score, fallback),
      }
    }

    // IP from stat ID 34 (confirmed via league statQualificationMinimum)
    const teamIp = {
      yours: myStats['34']?.score ?? 0,
      theirs: theirStats['34']?.score ?? 0,
    }
    console.log('Team IP:', teamIp)

    // Identify pitchers who may start: SP by position, SP-eligible, or
    // any pitcher ESPN has tagged as Probable Pitcher (PP).
    const myRosterEntries = rosters[myTeamId] || []
    const hasPP = (entry: typeof myRosterEntries[0]) =>
      entry.player?.starterStatusByProGame &&
      Object.values(entry.player.starterStatusByProGame).some((s) => s === 'PROBABLE')
    const isSP = (entry: typeof myRosterEntries[0]) =>
      entry.player?.defaultPositionId === 1 ||
      entry.player?.eligibleSlots?.includes(14) ||
      hasPP(entry)

    const spNames = myRosterEntries
      .filter(isSP)
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Get opponent SP names from their roster
    const oppRosterEntries = rosters[theirSide.teamId] || []
    const oppSpNames = oppRosterEntries
      .filter(isSP)
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Collect all rostered player names across the league for streamer filtering
    const allRosteredNames: string[] = []
    for (const teamRoster of Object.values(rosters)) {
      for (const entry of teamRoster) {
        if (entry.player?.fullName) {
          allRosteredNames.push(entry.player.fullName)
        }
      }
    }

    // Get opponent team name
    const teams = await ESPNApi.getTeams(league.externalId, season, espnSettings)
    const opponentTeam = teams.find((t) => t.id === theirSide.teamId)
    const opponentName = opponentTeam
      ? [opponentTeam.location, opponentTeam.nickname].filter(Boolean).join(' ')
      : `Team ${theirSide.teamId}`

    const today = new Date()
    // Use local timezone for date strings (toISOString() is UTC and shifts dates in US evenings)
    const todayStr = toLocalDateStr(today)

    // Use hardcoded league schedule (same as matchup page)
    const { endDate } = getMatchupDateRange(matchupPeriod, today)
    const endDateStr = endDate

    // Days remaining = dates from today through endDate that still have unstarted
    // games. Today is included in the morning before first pitch; it falls off
    // once games go live or final.
    const rangeStart = todayStr <= endDateStr ? todayStr : endDateStr
    let daysRemaining: number
    try {
      const schedule = await getTeamGamesInRange(rangeStart, endDateStr)
      daysRemaining = schedule.datesWithUnstartedGames.length
    } catch (e) {
      console.warn('Failed to fetch MLB schedule for days_remaining; falling back to date math:', e)
      const { daysRemaining: fallback } = getMatchupDateRange(matchupPeriod, today)
      daysRemaining = fallback
    }

    // Streaming targets tomorrow (waiver claims process overnight)
    const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1)
    const tomorrowStr = toLocalDateStr(tomorrow)
    // If tomorrow is in a different matchup period, use that period's end date
    const streamingEndDate = getMatchupEndDateForDate(tomorrowStr) || endDateStr

    // Resolve ESPN PP (Probable Pitcher) tags to dates.
    // ESPN's starterStatusByProGame maps game event IDs → "PROBABLE".
    // We fetch the ESPN scoreboard to map those game IDs to actual dates.
    let espnStartsByDate: Record<string, string[]> | null = null
    try {
      // Collect all game IDs from both rosters' starterStatusByProGame
      const allGameIds = new Set<string>()
      for (const entry of [...myRosterEntries, ...oppRosterEntries]) {
        if (isSP(entry) && entry.player?.starterStatusByProGame) {
          for (const gameId of Object.keys(entry.player.starterStatusByProGame)) {
            allGameIds.add(gameId)
          }
        }
      }

      if (allGameIds.size > 0) {
        // Fetch game ID → date mapping from ESPN public scoreboard
        const gameIdToDate = await ESPNApi.getGameIdToDateMap(todayStr, endDateStr)
        console.log(`ESPN PP: resolved ${Object.keys(gameIdToDate).length} game IDs to dates`)

        // Build espnStartsByDate: date → list of pitcher names with PP on that date
        espnStartsByDate = {}
        for (const entry of [...myRosterEntries, ...oppRosterEntries]) {
          if (!isSP(entry) || !entry.player?.starterStatusByProGame) continue
          const name = entry.player.fullName || ''
          if (!name) continue

          for (const [gameId, status] of Object.entries(entry.player.starterStatusByProGame)) {
            if (status !== 'PROBABLE') continue
            const date = gameIdToDate[gameId]
            if (!date) continue
            // Only include dates within the matchup period
            if (date < todayStr || date > endDateStr) continue
            if (!espnStartsByDate[date]) espnStartsByDate[date] = []
            espnStartsByDate[date].push(name)
          }
        }
        console.log('ESPN PP starts by date:', JSON.stringify(espnStartsByDate))
      }
    } catch (e) {
      console.warn('Failed to resolve ESPN PP data, falling back to PitcherList only:', e)
    }

    // Call Python backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/start-sit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roster_pitcher_names: spNames,
        opponent_pitcher_names: oppSpNames,
        matchup_categories: matchupCategories,
        team_ip: teamIp,
        days_remaining: daysRemaining,
        opponent_name: opponentName,
        today_date: todayStr,
        matchup_end_date: endDateStr,
        all_rostered_names: allRosteredNames,
        streaming_target_date: tomorrowStr,
        streaming_end_date: streamingEndDate,
        espn_starts_by_date: espnStartsByDate,
      }),
    })

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text()
      console.error('Backend error:', errorText)
      return NextResponse.json(
        { error: `Backend error: ${backendResponse.status}` },
        { status: 502 },
      )
    }

    const result = await backendResponse.json()
    return NextResponse.json(result)
  } catch (error: any) {
    console.error('Start/sit error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute recommendations' },
      { status: 500 },
    )
  }
}
