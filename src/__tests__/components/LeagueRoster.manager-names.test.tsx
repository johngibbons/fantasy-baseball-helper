import { render, screen, waitFor } from '@testing-library/react'
import LeagueRoster from '../../components/LeagueRoster'

// Mock fetch for team data
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('LeagueRoster - Manager Names', () => {
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

  it('should display readable manager names instead of IDs', async () => {
    // Mock the teams API response with proper manager data
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        teams: [
          {
            id: 'team1',
            name: 'Team COUG',
            ownerName: 'John Smith', // Should display this readable name
            wins: 15,
            losses: 5,
            pointsFor: 850.5,
            pointsAgainst: 720.3
          },
          {
            id: 'team2', 
            name: 'Team BP',
            ownerName: 'Sarah Johnson', // Should display this readable name
            wins: 12,
            losses: 8,
            pointsFor: 780.2,
            pointsAgainst: 750.1
          },
          {
            id: 'team3',
            name: 'Team SHC',
            ownerName: 'Mike Williams', // Should display this readable name
            wins: 10,
            losses: 10,
            pointsFor: 720.0,
            pointsAgainst: 780.5
          }
        ]
      })
    })

    render(<LeagueRoster league={mockLeague} />)

    // Wait for teams to load
    await waitFor(() => {
      expect(screen.queryByText('Teams')).toBeInTheDocument()
    }, { timeout: 1000 })

    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).not.toBeInTheDocument()
    }, { timeout: 1000 })

    // Verify readable manager names are displayed
    expect(screen.getByText('Manager: John Smith')).toBeInTheDocument()
    expect(screen.getByText('Manager: Sarah Johnson')).toBeInTheDocument()
    expect(screen.getByText('Manager: Mike Williams')).toBeInTheDocument()
    
    // Verify cryptic IDs are NOT displayed
    expect(screen.queryByText(/Manager: \([A-Z0-9]{8}-[A-Z0-9]{4}-[A-Z0-9]{4}/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Manager: \{[A-Z0-9]{8}-[A-Z0-9]{4}-[A-Z0-9]{4}/)).not.toBeInTheDocument()
  })

  it('should handle teams with missing manager data gracefully', async () => {
    // Mock API response with incomplete manager data
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        teams: [
          {
            id: 'team1',
            name: 'Team ALPHA',
            ownerName: null, // No manager data
            wins: 15,
            losses: 5,
            pointsFor: 850.5,
            pointsAgainst: 720.3
          },
          {
            id: 'team2',
            name: 'Team BETA',
            ownerName: '', // Empty manager data
            wins: 12,
            losses: 8,
            pointsFor: 780.2,
            pointsAgainst: 750.1
          },
          {
            id: 'team3',
            name: 'Team GAMMA',
            ownerName: '{B66FE9C4-3CB2-4C57-BE09-A289E0A112DA}', // Still has ID format
            wins: 10,
            losses: 10,
            pointsFor: 720.0,
            pointsAgainst: 780.5
          }
        ]
      })
    })

    render(<LeagueRoster league={mockLeague} />)

    // Wait for teams to load
    await waitFor(() => {
      expect(screen.queryByText('Teams')).toBeInTheDocument()
    }, { timeout: 1000 })

    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).not.toBeInTheDocument()
    }, { timeout: 1000 })

    // For teams without manager data, should not show manager line at all
    // or show a friendly fallback
    expect(screen.queryByText('Manager: null')).not.toBeInTheDocument()
    expect(screen.queryByText('Manager:')).not.toBeInTheDocument()
    
    // Should not display cryptic IDs
    expect(screen.queryByText('Manager: {B66FE9C4-3CB2-4C57-BE09-A289E0A112DA}')).not.toBeInTheDocument()
  })

  it('should display team owner names when available', async () => {
    // Test with mixed data - some teams have good names, others need cleaning
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        teams: [
          {
            id: 'team1',
            name: 'Team LIONS',
            ownerName: 'Alex Thompson', // Good name
            wins: 15,
            losses: 5,
            pointsFor: 850.5,
            pointsAgainst: 720.3
          },
          {
            id: 'team2',
            name: 'Team TIGERS',
            ownerName: '  Jordan Lee  ', // Name with whitespace
            wins: 12,
            losses: 8,
            pointsFor: 780.2,
            pointsAgainst: 750.1
          }
        ]
      })
    })

    render(<LeagueRoster league={mockLeague} />)

    // Wait for teams to load
    await waitFor(() => {
      expect(screen.queryByText('Teams')).toBeInTheDocument()
    }, { timeout: 1000 })

    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).not.toBeInTheDocument()
    }, { timeout: 1000 })

    // Should display clean manager names
    expect(screen.getByText('Manager: Alex Thompson')).toBeInTheDocument()
    expect(screen.getByText('Manager: Jordan Lee')).toBeInTheDocument() // Trimmed whitespace
  })
})