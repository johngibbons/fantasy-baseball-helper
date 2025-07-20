/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import LeagueRoster from '../../components/LeagueRoster'

// Mock fetch globally
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('LeagueRoster League-Specific Stats Display', () => {
  beforeEach(() => {
    mockFetch.mockClear()
  })

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
        fullName: 'Juan Soto',
        primaryPosition: 'OF',
        position: 'OF',
        acquisitionType: 'DRAFT',
        stats: {
          gamesPlayed: 120,
          atBats: 450,
          runs: 70,        // statId: 20 (points: 1)
          hits: 130,
          doubles: 25,
          triples: 3,
          homeRuns: 24,
          rbi: 57,         // statId: 21 (points: 1)
          stolenBases: 12, // statId: 23 (points: 1)
          caughtStealing: 3,
          baseOnBalls: 80, // statId: 8 (points: 1)
          strikeOuts: 110,
          battingAverage: 0.257, // statId: 17 (points: 1) 
          onBasePercentage: 0.365,
          sluggingPercentage: 0.520,
          totalBases: 234
        }
      },
      {
        id: 32685,
        fullName: 'Max Fried',
        primaryPosition: 'SP',
        position: 'SP',
        acquisitionType: 'DRAFT',
        stats: {
          gamesPlayed: 20,
          atBats: 20,       // Games started
          runs: 11,         // Wins - statId: 63 (points: 1)
          hits: 3,          // Losses
          doubles: 0,       // Saves - statId: 83 (points: 1)
          triples: 0,
          homeRuns: 0,
          rbi: 0,
          stolenBases: 0,
          caughtStealing: 0,
          baseOnBalls: 27,
          strikeOuts: 113,  // statId: 48 (points: 1)
          battingAverage: 0,
          onBasePercentage: 2.43,  // ERA - statId: 47 (points: 1, isReverseItem: true)
          sluggingPercentage: 1.01, // WHIP - statId: 41 (points: 1, isReverseItem: true)
          totalBases: 122   // Innings pitched - statId: 34
        }
      }
    ]
  }

  // Mock league settings based on real ESPN scoring settings
  const mockLeagueWithCategoryScoring = {
    id: 'espn_123456_2025',
    name: 'Test Category League',
    platform: 'ESPN',
    season: '2025',
    teamCount: 2,
    settings: {
      scoringSettings: {
        scoringType: 'H2H_CATEGORY',
        scoringItems: [
          { statId: 20, points: 1, isReverseItem: false }, // Runs
          { statId: 21, points: 1, isReverseItem: false }, // RBI
          { statId: 23, points: 1, isReverseItem: false }, // Stolen Bases
          { statId: 8, points: 1, isReverseItem: false },  // Walks (hitters)
          { statId: 17, points: 1, isReverseItem: false }, // Batting Average
          { statId: 47, points: 1, isReverseItem: true },  // ERA (lower is better)
          { statId: 41, points: 1, isReverseItem: true },  // WHIP (lower is better)
          { statId: 63, points: 1, isReverseItem: false }, // Wins
          { statId: 48, points: 1, isReverseItem: false }, // Strikeouts (pitchers)
          { statId: 83, points: 1, isReverseItem: false }  // Saves
        ]
      }
    }
  }

  const mockLeagueWithPointsScoring = {
    id: 'espn_123456_2025',
    name: 'Test Points League',
    platform: 'ESPN',
    season: '2025',
    teamCount: 2,
    settings: {
      scoringSettings: {
        scoringType: 'H2H_POINTS',
        scoringItems: [
          { statId: 20, points: 1, isReverseItem: false }, // Runs (1 pt each)
          { statId: 21, points: 2, isReverseItem: false }, // RBI (2 pts each)
          { statId: 5, points: 4, isReverseItem: false },  // Home Runs (4 pts each)
          { statId: 23, points: 2, isReverseItem: false }, // Stolen Bases (2 pts each)
          { statId: 10, points: -1, isReverseItem: false }, // Strikeouts (-1 pt each)
          { statId: 63, points: 5, isReverseItem: false }, // Wins (5 pts each)
          { statId: 48, points: 1, isReverseItem: false }, // Strikeouts (1 pt each)
          { statId: 47, points: -1, isReverseItem: false }, // ERA (-1 pt per point)
        ]
      }
    }
  }

  it('should display only stats that are scored in category leagues', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ scoringSettings: mockLeagueWithCategoryScoring.settings.scoringSettings })
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithStats
      })

    render(<LeagueRoster league={mockLeagueWithCategoryScoring} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Juan Soto')).toBeInTheDocument()
    })

    // For position players, should show league-scored stats: R, RBI, SB, BB, AVG
    // Should NOT show HR (not in scoring settings)
    expect(screen.getByText('70')).toBeInTheDocument() // Runs
    expect(screen.getByText('R')).toBeInTheDocument() // Runs label
    expect(screen.getByText('57')).toBeInTheDocument() // RBI
    expect(screen.getByText('RBI')).toBeInTheDocument() // RBI label
    expect(screen.getByText('12')).toBeInTheDocument() // Stolen Bases
    expect(screen.getByText('SB')).toBeInTheDocument() // SB label
    expect(screen.getByText('80')).toBeInTheDocument() // Walks
    expect(screen.getByText('BB')).toBeInTheDocument() // Walks label
    expect(screen.getByText('0.257')).toBeInTheDocument() // Batting Average
    expect(screen.getByText('AVG')).toBeInTheDocument() // AVG label

    // Should NOT show HR since it's not in the scoring settings
    expect(screen.queryByText('HR')).not.toBeInTheDocument()

    // For pitchers, should show league-scored stats: ERA, WHIP, W, K, SV
    expect(screen.getByText('Max Fried')).toBeInTheDocument()
    expect(screen.getByText('2.43')).toBeInTheDocument() // ERA
    expect(screen.getByText('ERA')).toBeInTheDocument() // ERA label
    expect(screen.getByText('1.01')).toBeInTheDocument() // WHIP
    expect(screen.getByText('WHIP')).toBeInTheDocument() // WHIP label
    expect(screen.getByText('11')).toBeInTheDocument() // Wins
    expect(screen.getByText('W')).toBeInTheDocument() // Wins label
    expect(screen.getByText('113')).toBeInTheDocument() // Strikeouts
    expect(screen.getByText('K')).toBeInTheDocument() // Strikeouts label
  })

  it('should display point values for stats in points leagues', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ scoringSettings: mockLeagueWithPointsScoring.settings.scoringSettings })
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithStats
      })

    render(<LeagueRoster league={mockLeagueWithPointsScoring} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Juan Soto')).toBeInTheDocument()
    })

    // Should show stats with their point values
    expect(screen.getByText('70')).toBeInTheDocument() // Runs value
    expect(screen.getByText('R (1)')).toBeInTheDocument() // Runs with point value
    expect(screen.getByText('57')).toBeInTheDocument() // RBI value
    expect(screen.getByText('RBI (2)')).toBeInTheDocument() // RBI with point value
    expect(screen.getByText('12')).toBeInTheDocument() // SB value
    expect(screen.getByText('SB (2)')).toBeInTheDocument() // SB with point value

    // For pitchers
    expect(screen.getByText('11')).toBeInTheDocument() // Wins value
    expect(screen.getByText('W (5)')).toBeInTheDocument() // Wins with point value
  })

  it('should handle leagues without scoring settings gracefully', async () => {
    const mockLeagueWithoutSettings = {
      id: 'espn_123456_2025',
      name: 'Test League No Settings',
      platform: 'ESPN',
      season: '2025',
      teamCount: 2
      // No settings property
    }

    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ scoringSettings: null })
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithStats
      })

    render(<LeagueRoster league={mockLeagueWithoutSettings} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Juan Soto')).toBeInTheDocument()
    })

    // Should fall back to default stats display
    expect(screen.getByText('24')).toBeInTheDocument() // Home runs (default)
    expect(screen.getByText('HR')).toBeInTheDocument() // HR label
    expect(screen.getByText('57')).toBeInTheDocument() // RBI
    expect(screen.getByText('RBI')).toBeInTheDocument() // RBI label
  })

  it('should show different stat layouts for category vs points leagues', async () => {
    // Category leagues should show more stats (up to 5-6 categories)
    // Points leagues should show fewer, high-impact stats (3-4 stats)
    
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ scoringSettings: mockLeagueWithCategoryScoring.settings.scoringSettings })
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockTeamsResponse
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockRosterWithStats
      })

    render(<LeagueRoster league={mockLeagueWithCategoryScoring} />)

    await waitFor(() => {
      expect(screen.getByText('Test Team 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Test Team 1'))

    await waitFor(() => {
      expect(screen.getByText('Juan Soto')).toBeInTheDocument()
    })

    // Category league should show all 5 hitting categories
    const statGrids = screen.getAllByText('Juan Soto')[0].closest('.border')?.querySelectorAll('.grid > div')
    expect(statGrids?.length).toBe(5) // R, RBI, SB, BB, AVG
  })
})