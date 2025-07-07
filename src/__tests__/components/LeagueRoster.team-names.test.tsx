import { render, screen, waitFor } from '@testing-library/react'
import LeagueRoster from '../../components/LeagueRoster'

// Mock fetch for team data
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('LeagueRoster - Team Names', () => {
  const mockLeague = {
    id: 'espn_123456_2025',
    name: 'Test League',
    platform: 'ESPN',
    season: '2025',
    teamCount: 3
  }

  beforeEach(() => {
    mockFetch.mockClear()
  })

  it('should display actual team names instead of "Unknown Team"', async () => {
    // Mock the teams API response with proper team data
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        teams: [
          {
            id: '1',
            name: 'The Sluggers',
            location: 'Chicago',
            ownerName: 'John Doe',
            wins: 15,
            losses: 5,
            pointsFor: 850.5,
            pointsAgainst: 720.3
          },
          {
            id: '2', 
            name: 'Home Run Heroes',
            location: 'Boston',
            ownerName: 'Jane Smith',
            wins: 12,
            losses: 8,
            pointsFor: 780.2,
            pointsAgainst: 750.1
          },
          {
            id: '3',
            name: 'Diamond Kings',
            location: 'New York',
            ownerName: 'Mike Johnson',
            wins: 10,
            losses: 10,
            pointsFor: 720.0,
            pointsAgainst: 780.5
          }
        ]
      })
    })

    render(<LeagueRoster league={mockLeague} />)

    // Wait for teams to load - check for the absence of loading spinner
    await waitFor(() => {
      expect(screen.queryByText('Teams')).toBeInTheDocument()
    }, { timeout: 1000 })

    // Also wait for loading animation to disappear
    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).not.toBeInTheDocument()
    }, { timeout: 1000 })

    // Verify actual team names are displayed (not "Unknown Team")
    expect(screen.getByText('The Sluggers')).toBeInTheDocument()
    expect(screen.getByText('Home Run Heroes')).toBeInTheDocument()
    expect(screen.getByText('Diamond Kings')).toBeInTheDocument()
    
    // Verify "Unknown Team" is not displayed
    expect(screen.queryByText('Unknown Team')).not.toBeInTheDocument()

    // Verify team details are properly displayed
    expect(screen.getByText('Manager: John Doe')).toBeInTheDocument()
    expect(screen.getByText('Manager: Jane Smith')).toBeInTheDocument()
    expect(screen.getByText('Manager: Mike Johnson')).toBeInTheDocument()

    // Verify win-loss records
    expect(screen.getByText('15-5')).toBeInTheDocument()
    expect(screen.getByText('12-8')).toBeInTheDocument()
    expect(screen.getByText('10-10')).toBeInTheDocument()
  })

  it('should handle teams with missing name data gracefully', async () => {
    // Mock API response with incomplete team data
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        teams: [
          {
            id: 'team_abc123',
            name: '', // Empty name
            location: '',
            ownerName: 'John Doe',
            wins: 15,
            losses: 5,
            pointsFor: 850.5,
            pointsAgainst: 720.3
          },
          {
            id: 'team_def456',
            name: 'Unknown Team', // Default fallback name
            location: 'Boston',
            ownerName: 'Jane Smith',
            wins: 12,
            losses: 8,
            pointsFor: 780.2,
            pointsAgainst: 750.1
          }
        ]
      })
    })

    render(<LeagueRoster league={mockLeague} />)

    // Wait for teams to load - check for the absence of loading spinner
    await waitFor(() => {
      expect(screen.queryByText('Teams')).toBeInTheDocument()
    }, { timeout: 1000 })

    // Also wait for loading animation to disappear
    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).not.toBeInTheDocument()
    }, { timeout: 1000 })

    // Should show fallback text based on team ID for teams without proper names
    expect(screen.getByText('Team 123')).toBeInTheDocument() // Last 3 chars of team_abc123
    expect(screen.getByText('Team 456')).toBeInTheDocument() // Last 3 chars of team_def456
  })
})