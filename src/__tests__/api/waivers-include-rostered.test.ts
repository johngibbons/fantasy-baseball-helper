/**
 * @jest-environment node
 */
import { NextRequest } from 'next/server'
import { POST } from '../../app/api/waivers/recommendations/route'
import { prisma } from '../../lib/prisma'
import { ESPNApi } from '../../lib/espn-api'

jest.mock('../../lib/prisma', () => ({
  prisma: { league: { findUnique: jest.fn() } },
}))
jest.mock('../../lib/espn-api')

const mockPrisma = prisma as any
const mockESPNApi = ESPNApi as jest.Mocked<typeof ESPNApi>

/** Captures the body forwarded to the Python backend. */
let backendBody: any

function makeRequest(body: Record<string, unknown>) {
  return new NextRequest('http://localhost/api/waivers/recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

const player = (id: number, fullName: string, defaultPositionId: number, eligibleSlots: number[]) => ({
  playerId: id,
  lineupSlotId: 0,
  acquisitionType: 'DRAFT',
  player: { id, fullName, defaultPositionId, eligibleSlots },
})

describe('/api/waivers/recommendations — includeRostered', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    backendBody = undefined

    mockPrisma.league.findUnique.mockResolvedValue({
      id: 'espn_1_2026',
      externalId: '1',
      season: '2026',
      platform: 'ESPN',
      settings: { credentials: { swid: '{S}', espn_s2: 'S2' } },
    })

    mockESPNApi.getRosters.mockResolvedValue({
      // My team
      8: [player(1, 'My Guy', 3, [1]), { ...player(2, 'My IL Guy', 3, [1]), lineupSlotId: 17 }],
      // Opponents — one active, one on IL (IL must be excluded from candidates)
      5: [player(10, 'Trade Target', 5, [3]), { ...player(11, 'Injured Target', 5, [3]), lineupSlotId: 17 }],
      9: [player(20, 'Other Target', 8, [5])],
    } as any)

    mockESPNApi.getFreeAgents.mockResolvedValue([
      { id: 30, fullName: 'Free Agent', defaultPositionId: 3, eligibleSlots: [1] },
    ] as any)

    mockESPNApi.getLeagueTeamsAndFaab.mockResolvedValue({
      teams: [
        { id: 8, abbrev: 'ME', location: 'My', nickname: 'Team' },
        { id: 5, abbrev: 'JAMC', location: 'Last Place', nickname: 'Champs' },
        { id: 9, abbrev: 'RJB', location: '', nickname: '' },
      ],
      faabByTeamId: { 8: 44 },
    } as any)

    global.fetch = jest.fn(async (_url: any, init: any) => {
      backendBody = JSON.parse(init.body)
      return {
        ok: true,
        json: async () => ({
          baseline_expected_wins: 6.0,
          recommendations: [],
          // Backend resolves names -> mlb ids; drives the owner map
          name_to_mlb_id: { 'Trade Target': 1010, 'Other Target': 2020, 'Free Agent': 3030 },
        }),
      }
    }) as any
  })

  it('sends no rostered candidates by default', async () => {
    const res = await POST(makeRequest({ leagueId: 'espn_1_2026', teamId: '8' }))
    const data = await res.json()

    expect(res.status).toBe(200)
    expect(backendBody.rostered_candidates).toEqual([])
    expect(data.rostered_candidate_count).toBe(0)
    expect(data.owner_by_mlb_id).toEqual({})
  })

  it('sends other teams’ active players as candidates when enabled', async () => {
    await POST(makeRequest({ leagueId: 'espn_1_2026', teamId: '8', includeRostered: true }))

    const names = backendBody.rostered_candidates.map((p: any) => p.name)
    expect(names).toEqual(expect.arrayContaining(['Trade Target', 'Other Target']))
    // My own players are never candidates
    expect(names).not.toContain('My Guy')
    // IL-slotted opponents are filtered out
    expect(names).not.toContain('Injured Target')
  })

  it('maps candidates to their owning team name, keyed by mlb_id', async () => {
    const res = await POST(makeRequest({ leagueId: 'espn_1_2026', teamId: '8', includeRostered: true }))
    const data = await res.json()

    expect(data.owner_by_mlb_id[1010]).toBe('Last Place Champs')
    // Falls back to abbrev when location/nickname are empty
    expect(data.owner_by_mlb_id[2020]).toBe('RJB')
    // Free agents are not owned
    expect(data.owner_by_mlb_id[3030]).toBeUndefined()
    expect(data.include_rostered).toBe(true)
  })

  it('still sends opponents as league context in both modes', async () => {
    await POST(makeRequest({ leagueId: 'espn_1_2026', teamId: '8', includeRostered: true }))
    // Opponent rosters drive the win-probability baseline and must stay intact
    expect(backendBody.other_team_rosters).toHaveLength(2)
    const contextNames = backendBody.other_team_rosters.flatMap((t: any) =>
      t.players.map((p: any) => p.name),
    )
    expect(contextNames).toContain('Injured Target')
  })
})
