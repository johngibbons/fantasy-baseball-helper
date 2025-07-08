import { render, screen, waitFor } from '@testing-library/react'
import LeagueRoster from '../../components/LeagueRoster'

// Mock fetch
global.fetch = jest.fn()

const mockLeague = {
  id: 'espn_123456_2025',
  name: 'JUICED',
  platform: 'ESPN',
  season: '2025',
  teamCount: 10
}

describe('LeagueRoster - Manager Names from Real Data', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('should display actual manager names when ESPN provides readable names', async () => {
    // Mock API response with some valid manager names (rare but possible)
    const mockApiResponse = {
      teams: [
        {
          id: '1',
          name: 'Team COUG',
          ownerName: 'John Smith', // Valid readable name
          wins: 8,
          losses: 4,
          pointsFor: 84.50,
          pointsAgainst: 75.20
        },
        {
          id: '2', 
          name: 'Team BP',
          ownerName: 'Sarah Johnson', // Valid readable name
          wins: 7,
          losses: 5,
          pointsFor: 83.52,
          pointsAgainst: 68.30
        }
      ]
    }

    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockApiResponse
    })

    const mockOnBack = jest.fn()
    render(<LeagueRoster league={mockLeague} onBack={mockOnBack} />)

    // Wait for teams to load
    await waitFor(() => {
      expect(screen.getByText('Team COUG')).toBeInTheDocument()
    })

    // Check that actual manager names are displayed
    expect(screen.getByText(/John Smith/)).toBeInTheDocument()
    expect(screen.getByText(/Sarah Johnson/)).toBeInTheDocument()

    // Ensure no fallback text is shown when valid names exist
    expect(screen.queryByText('Unknown Manager')).not.toBeInTheDocument()
  })

  it('should display "Unknown Manager" for teams with missing manager names from ESPN data', async () => {
    // Mock API response with real persisted data structure (ESPN often provides IDs, not names)
    const mockApiResponse = {
      teams: [
        {
          id: '1',
          name: 'Team COUG',
          ownerName: null, // ESPN often doesn't provide readable names
          wins: 8,
          losses: 4,
          pointsFor: 84.50,
          pointsAgainst: 75.20
        },
        {
          id: '2', 
          name: 'Team BP',
          ownerName: '', // Or provides empty strings
          wins: 7,
          losses: 5,
          pointsFor: 83.52,
          pointsAgainst: 68.30
        },
        {
          id: '3',
          name: 'Team SHC', 
          ownerName: null, // Most teams have no readable manager name
          wins: 7,
          losses: 5,
          pointsFor: 82.52,
          pointsAgainst: 71.45
        }
      ]
    }

    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockApiResponse
    })

    const mockOnBack = jest.fn()
    render(<LeagueRoster league={mockLeague} onBack={mockOnBack} />)

    // Wait for teams to load
    await waitFor(() => {
      expect(screen.getByText('Team COUG')).toBeInTheDocument()
    })

    // Check that "Unknown Manager" is displayed for all teams with missing names
    const unknownManagerElements = screen.getAllByText(/Unknown Manager/)
    expect(unknownManagerElements).toHaveLength(3) // All 3 teams should show "Unknown Manager"

    // Ensure no IDs or "null" text is displayed
    expect(screen.queryByText(/^[A-Z0-9]{8,}$/)).not.toBeInTheDocument() // No long ID strings
    expect(screen.queryByText('null')).not.toBeInTheDocument()
    expect(screen.queryByText('undefined')).not.toBeInTheDocument()
  })

  it('should handle teams with missing manager names gracefully', async () => {
    const mockApiResponse = {
      teams: [
        {
          id: '1',
          name: 'Team COUG',
          ownerName: null, // Missing manager name
          wins: 8,
          losses: 4,
          pointsFor: 84.50,
          pointsAgainst: 75.20
        },
        {
          id: '2',
          name: 'Team BP', 
          ownerName: 'Sarah Johnson', // Valid manager name
          wins: 7,
          losses: 5,
          pointsFor: 83.52,
          pointsAgainst: 68.30
        }
      ]
    }

    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockApiResponse
    })

    const mockOnBack = jest.fn()
    render(<LeagueRoster league={mockLeague} onBack={mockOnBack} />)

    await waitFor(() => {
      expect(screen.getByText('Team COUG')).toBeInTheDocument()
    })

    // Should show valid manager name
    expect(screen.getByText(/Sarah Johnson/)).toBeInTheDocument()
    
    // Should show fallback for missing manager name (not "null" text)
    expect(screen.getByText(/Unknown Manager/)).toBeInTheDocument()
    expect(screen.queryByText('null')).not.toBeInTheDocument()
  })
})