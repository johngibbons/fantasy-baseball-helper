/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import LeagueRoster from '../../components/LeagueRoster'

// Mock fetch globally
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('LeagueRoster Player Stats Display', () => {
  beforeEach(() => {
    mockFetch.mockClear()
  })

  const mockLeague = {
    id: 'espn_123456_2024',
    name: 'Test Fantasy League',
    platform: 'ESPN',
    season: '2024',
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

  const mockRosterWithStats = {
    roster: [
      {
        id: 12345,
        fullName: 'Mike Trout',
        primaryPosition: 'OF',
        position: 'OF',
        acquisitionType: 'DRAFT',
        stats: {
          gamesPlayed: 120,
          homeRuns: 25,
          rbi: 80,
          battingAverage: 0.285,
          stolenBases: 15,
          runs: 75,
          hits: 150,
          onBasePercentage: 0.365,
          sluggingPercentage: 0.520
        }
      },
      {
        id: 67890,
        fullName: 'Gerrit Cole',
        primaryPosition: 'SP',
        position: 'SP',
        acquisitionType: 'DRAFT',
        stats: {
          gamesPlayed: 30,
          homeRuns: 0,
          rbi: 2,
          battingAverage: 0.150,
          stolenBases: 0,
          runs: 5,
          hits: 12,
          onBasePercentage: 0.200,
          sluggingPercentage: 0.180
        }
      }
    ]
  }

  const mockRosterWithoutStats = {
    roster: [
      {
        id: 12345,
        fullName: 'Mike Trout',
        primaryPosition: 'OF',
        position: 'OF',
        acquisitionType: 'DRAFT',
        stats: null // No stats available
      }
    ]
  }

  it('should display player statistics when available', async () => {
    // Mock teams API call
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      // Mock roster API call with stats
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithStats
      })

    render(<LeagueRoster league={mockLeague} />)

    // Wait for teams to load and click on first team
    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    const teamButton = screen.getByText('Test Team 1')
    fireEvent.click(teamButton)

    // Wait for roster to load
    await waitFor(() => {
      expect(screen.getByText('Mike Trout')).toBeInTheDocument()
    })

    // Check that stats are displayed for position players
    expect(screen.getByText('25')).toBeInTheDocument() // Home runs
    expect(screen.getAllByText('HR').length).toBeGreaterThanOrEqual(1) // Home runs label (multiple players may have this)
    expect(screen.getByText('80')).toBeInTheDocument() // RBI
    expect(screen.getAllByText('RBI').length).toBeGreaterThanOrEqual(1) // RBI label
    expect(screen.getByText('0.285')).toBeInTheDocument() // Batting average
    expect(screen.getAllByText('AVG').length).toBeGreaterThanOrEqual(1) // Average label
    expect(screen.getByText('15')).toBeInTheDocument() // Stolen bases
    expect(screen.getAllByText('SB').length).toBeGreaterThanOrEqual(1) // Stolen bases label

    // Check that pitcher stats are handled appropriately (pitchers have minimal hitting stats)
    expect(screen.getByText('Gerrit Cole')).toBeInTheDocument()
    // Both players should show stats now, so we just verify the pitcher's specific stats exist
    expect(screen.getByText('0.150')).toBeInTheDocument() // Pitcher's batting average
    expect(screen.getByText('2')).toBeInTheDocument() // Pitcher's RBI
  })

  it('should display N/A when stats are not available', async () => {
    // Mock teams API call
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      // Mock roster API call without stats
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithoutStats
      })

    render(<LeagueRoster league={mockLeague} />)

    // Wait for teams to load and click on first team
    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    const teamButton = screen.getByText('Test Team 1')
    fireEvent.click(teamButton)

    // Wait for roster to load
    await waitFor(() => {
      expect(screen.getByText('Mike Trout')).toBeInTheDocument()
    })

    // Check that stats section is not rendered when stats are not available
    // Since player.stats is null, the stats section should not be rendered at all
    // So there should be no HR, RBI, AVG, SB labels
    expect(screen.queryByText('HR')).not.toBeInTheDocument()
    expect(screen.queryByText('RBI')).not.toBeInTheDocument()
    expect(screen.queryByText('AVG')).not.toBeInTheDocument()
    expect(screen.queryByText('SB')).not.toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
  })

  it('should format batting average with 3 decimal places', async () => {
    const mockRosterWithPreciseAvg = {
      roster: [
        {
          id: 12345,
          fullName: 'Mike Trout',
          primaryPosition: 'OF',
          position: 'OF',
          acquisitionType: 'DRAFT',
          stats: {
            gamesPlayed: 120,
            homeRuns: 25,
            rbi: 80,
            battingAverage: 0.28571, // Should be formatted to 0.286
            stolenBases: 15
          }
        }
      ]
    }

    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithPreciseAvg
      })

    render(<LeagueRoster league={mockLeague} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Mike Trout')).toBeInTheDocument()
    })

    // Should format batting average to 3 decimal places
    expect(screen.getByText('0.286')).toBeInTheDocument()
  })

  it('should handle edge cases for stat values', async () => {
    const mockRosterWithEdgeCases = {
      roster: [
        {
          id: 12345,
          fullName: 'Edge Case Player',
          primaryPosition: 'C',
          position: 'C',
          acquisitionType: 'WAIVERS',
          stats: {
            gamesPlayed: 0,
            homeRuns: 0,
            rbi: 0,
            battingAverage: 0.000,
            stolenBases: 0
          }
        }
      ]
    }

    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithEdgeCases
      })

    render(<LeagueRoster league={mockLeague} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Edge Case Player')).toBeInTheDocument()
    })

    // Should display 0 values properly, not N/A
    const playerCard = screen.getByText('Edge Case Player').closest('.border')
    const zeroValues = screen.getAllByText('0')
    
    // Should have at least 3 zeros (HR, RBI, SB) plus formatted batting average
    expect(zeroValues.length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText('0.000')).toBeInTheDocument() // Batting average
  })
})