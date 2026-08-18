/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import LeagueRoster from '../../components/LeagueRoster'
import { installFetchMock } from '../../test-utils/fetch-mock'

// Mock fetch globally
const mockFetch = jest.fn()
installFetchMock(mockFetch)

describe('LeagueRoster Pitcher Stats Display', () => {
  beforeEach(() => {
    mockFetch.mockClear()
  })

  const mockLeague = {
    id: 'espn_123456_2025',
    name: 'Test Fantasy League',
    platform: 'ESPN',
    season: '2025',
    teamCount: 2
  }

  const mockTeamsResponse = {
    teams: [
      {
        id: 'team-1',
        name: 'Test Team 1',
        ownerName: 'Owner 1',
        wins: 10,
        losses: 5,
        pointsFor: 1250.5,
        pointsAgainst: 1100.2
      }
    ]
  }

  const mockRosterWithPitcher = {
    roster: [
      {
        id: 32685, // Max Fried
        fullName: 'Max Fried',
        primaryPosition: 'SP',
        position: 'SP',
        acquisitionType: 'DRAFT',
        stats: {
          // Based on Max Fried's real 2025 stats: 20 GP, 20 GS, 11 W, 3 L, 2.43 ERA, 1.01 WHIP
          // Repurposed fields: onBasePercentage=ERA, sluggingPercentage=WHIP, runs=wins, hits=losses, doubles=saves
          gamesPlayed: 20,              // Games pitched
          atBats: 20,                   // Games started (repurposed)
          runs: 11,                     // Wins (repurposed)
          hits: 3,                      // Losses (repurposed)
          doubles: 0,                   // Saves (repurposed)
          triples: 0,                   // Not used for pitchers
          homeRuns: 0,                  // Not used for pitchers
          rbi: 0,                       // Not used for pitchers
          stolenBases: 0,               // Not used for pitchers
          caughtStealing: 0,            // Not used for pitchers
          baseOnBalls: 27,              // Walks allowed
          strikeOuts: 113,              // Strikeouts
          battingAverage: 0,            // Not used for pitchers
          onBasePercentage: 2.43,       // ERA (repurposed)
          sluggingPercentage: 1.01,     // WHIP (repurposed)
          totalBases: 122.0             // Innings pitched (repurposed)
        }
      },
      {
        id: 67890,
        fullName: 'Tyler Rogers',
        primaryPosition: 'RP',
        position: 'P',
        acquisitionType: 'ADD',
        stats: {
          // Relief pitcher stats - repurposed fields: onBasePercentage=ERA, sluggingPercentage=WHIP, runs=wins, hits=losses, doubles=saves
          gamesPlayed: 45,              // Games pitched
          atBats: 0,                    // Games started (repurposed)
          runs: 3,                      // Wins (repurposed)
          hits: 2,                      // Losses (repurposed)
          doubles: 15,                  // Saves (repurposed)
          triples: 0,                   // Not used for pitchers
          homeRuns: 0,                  // Not used for pitchers
          rbi: 0,                       // Not used for pitchers
          stolenBases: 0,               // Not used for pitchers
          caughtStealing: 0,            // Not used for pitchers
          baseOnBalls: 18,              // Walks allowed
          strikeOuts: 58,               // Strikeouts
          battingAverage: 0,            // Not used for pitchers
          onBasePercentage: 3.25,       // ERA (repurposed)
          sluggingPercentage: 1.20,     // WHIP (repurposed)
          totalBases: 65.1              // Innings pitched (repurposed)
        }
      }
    ]
  }

  it('should display pitcher positions correctly as SP or RP', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithPitcher
      })

    render(<LeagueRoster league={mockLeague} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Max Fried')).toBeInTheDocument()
    })

    // Check that Max Fried shows as SP, not 1B
    const maxFriedCard = screen.getByText('Max Fried').closest('.border')
    expect(maxFriedCard).toHaveTextContent('SP • DRAFT')
    expect(maxFriedCard).not.toHaveTextContent('1B • DRAFT')

    // Check that Tyler Rogers shows as RP or P
    const tylerCard = screen.getByText('Tyler Rogers').closest('.border')
    expect(tylerCard).toHaveTextContent(/[RP|P] • ADD/)
  })

  it('should display pitching stats instead of hitting stats for pitchers', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithPitcher
      })

    render(<LeagueRoster league={mockLeague} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Max Fried')).toBeInTheDocument()
    })

    // Check that Max Fried shows pitching stats, not hitting stats
    expect(screen.getByText('2.43')).toBeInTheDocument() // ERA
    expect(screen.getAllByText('ERA').length).toBeGreaterThanOrEqual(1) // ERA label (multiple pitchers may have this)
    expect(screen.getByText('1.01')).toBeInTheDocument() // WHIP
    expect(screen.getAllByText('WHIP').length).toBeGreaterThanOrEqual(1) // WHIP label
    expect(screen.getByText('11')).toBeInTheDocument() // Wins
    expect(screen.getAllByText('W').length).toBeGreaterThanOrEqual(1) // Wins label
    expect(screen.getByText('113')).toBeInTheDocument() // Strikeouts
    // Both pitchers on this roster render a K label, so match the same way
    // the W assertion above does.
    expect(screen.getAllByText('K').length).toBeGreaterThanOrEqual(1)

    // Should NOT show hitting stats labels for pitchers
    expect(screen.queryByText('HR')).not.toBeInTheDocument()
    expect(screen.queryByText('RBI')).not.toBeInTheDocument()
    expect(screen.queryByText('AVG')).not.toBeInTheDocument()
    expect(screen.queryByText('SB')).not.toBeInTheDocument()
  })

  it('should display relief pitcher stats correctly', async () => {
    // Saves only render when the league actually scores them — the default
    // pitcher stat set is ERA/WHIP/W/K. So this test supplies a league whose
    // categories include saves (ESPN stat 83), which is what makes SV appear.
    const leagueScoringSaves = {
      ...mockLeague,
      settings: {
        scoringSettings: {
          scoringType: 'H2H_CATEGORY',
          scoringItems: [
            { statId: 47, points: 1, isReverseItem: true },  // ERA
            { statId: 41, points: 1, isReverseItem: true },  // WHIP
            { statId: 48, points: 1, isReverseItem: false }, // K
            { statId: 53, points: 1, isReverseItem: false }, // W
            { statId: 83, points: 1, isReverseItem: false }, // SV
          ],
        },
      },
    }

    installFetchMock(mockFetch, {
      '/settings': {
        json: { scoringSettings: leagueScoringSaves.settings.scoringSettings },
      },
    })
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithPitcher
      })

    render(<LeagueRoster league={leagueScoringSaves} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Tyler Rogers')).toBeInTheDocument()
    })

    // Check relief pitcher specific stats
    expect(screen.getByText('15')).toBeInTheDocument() // Saves — Tyler Rogers
    // Every pitcher on the roster renders an SV label once the league scores it.
    expect(screen.getAllByText('SV').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('3.25')).toBeInTheDocument() // ERA
    expect(screen.getByText('3')).toBeInTheDocument() // Wins — Tyler Rogers
  })

  it('should handle pitchers without stats gracefully', async () => {
    const mockRosterWithoutPitcherStats = {
      roster: [
        {
          id: 32685,
          fullName: 'Max Fried',
          primaryPosition: 'SP',
          position: 'SP',
          acquisitionType: 'DRAFT',
          stats: null // No stats available
        }
      ]
    }

    installFetchMock(mockFetch, {
      '/settings': { json: { scoringSettings: null } },
    })
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithoutPitcherStats
      })

    render(<LeagueRoster league={mockLeague} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Max Fried')).toBeInTheDocument()
    })

    // Should still show position correctly
    expect(screen.getByText('Max Fried').closest('.border')).toHaveTextContent('SP • DRAFT')

    // Should not show any stat labels when no stats available
    expect(screen.queryByText('ERA')).not.toBeInTheDocument()
    expect(screen.queryByText('WHIP')).not.toBeInTheDocument()
    expect(screen.queryByText('HR')).not.toBeInTheDocument()
    expect(screen.queryByText('RBI')).not.toBeInTheDocument()
  })
})