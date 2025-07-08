import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HomePage from '../../app/page'

// Mock the child components
jest.mock('../../components/PlayerSearch', () => {
  return function MockPlayerSearch() {
    return <div data-testid="player-search">Player Search Component</div>
  }
})

jest.mock('../../components/PlayerStats', () => {
  return function MockPlayerStats() {
    return <div data-testid="player-stats">Player Stats Component</div>
  }
})

jest.mock('../../components/LeagueConnection', () => {
  return function MockLeagueConnection({ onLeagueConnected }: { onLeagueConnected: (data: any) => void }) {
    return (
      <div data-testid="league-connection">
        League Connection Component
        <button onClick={() => onLeagueConnected({ id: 'new-league', name: 'New League', platform: 'ESPN', season: '2025', teamCount: 10 })}>
          Connect League
        </button>
      </div>
    )
  }
})

jest.mock('../../components/LeagueRoster', () => {
  return function MockLeagueRoster({ league, onBack }: { league: any; onBack: () => void }) {
    return (
      <div data-testid="league-roster">
        League Roster for {league.name}
        <button onClick={onBack}>Back</button>
      </div>
    )
  }
})

// Mock fetch
global.fetch = jest.fn()

describe('HomePage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('should load existing leagues on component mount', async () => {
    const mockLeagues = [
      {
        id: 'espn_123456_2025',
        name: 'Test League',
        platform: 'ESPN',
        season: '2025',
        teamCount: 10,
        isActive: true,
        lastSyncAt: '2025-01-01T00:00:00Z',
      },
      {
        id: 'espn_789012_2025',
        name: 'Another League',
        platform: 'ESPN',
        season: '2025',
        teamCount: 12,
        isActive: true,
        lastSyncAt: '2025-01-02T00:00:00Z',
      },
    ]

    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockLeagues,
    })

    render(<HomePage />)

    // Switch to leagues tab
    const leaguesTab = screen.getByRole('button', { name: /league integration/i })
    await userEvent.click(leaguesTab)

    // Wait for leagues to load
    await waitFor(() => {
      expect(screen.getByText('Connected Leagues')).toBeInTheDocument()
    })

    // Check that leagues are displayed
    expect(screen.getByText('Test League')).toBeInTheDocument()
    expect(screen.getByText('Another League')).toBeInTheDocument()
    expect(screen.getByText('2025 • 10 teams')).toBeInTheDocument()
    expect(screen.getByText('2025 • 12 teams')).toBeInTheDocument()

    // Verify fetch was called
    expect(fetch).toHaveBeenCalledWith('/api/leagues')
  })

  it('should handle API errors gracefully when loading leagues', async () => {
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {})

    ;(fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'))

    render(<HomePage />)

    // Switch to leagues tab
    const leaguesTab = screen.getByRole('button', { name: /league integration/i })
    await userEvent.click(leaguesTab)

    // Wait for error handling
    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Error loading existing leagues:', expect.any(Error))
    })

    // Should show connection form instead of leagues
    expect(screen.getByTestId('league-connection')).toBeInTheDocument()
    expect(screen.queryByText('Connected Leagues')).not.toBeInTheDocument()

    consoleSpy.mockRestore()
  })

  it('should handle API response errors when loading leagues', async () => {
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {})

    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 500,
    })

    render(<HomePage />)

    // Switch to leagues tab
    const leaguesTab = screen.getByRole('button', { name: /league integration/i })
    await userEvent.click(leaguesTab)

    // Wait for error handling - the component doesn't log for response errors, only network errors
    await waitFor(() => {
      expect(screen.getByTestId('league-connection')).toBeInTheDocument()
    })

    // Should show connection form instead of leagues
    expect(screen.getByTestId('league-connection')).toBeInTheDocument()
    expect(screen.queryByText('Connected Leagues')).not.toBeInTheDocument()

    consoleSpy.mockRestore()
  })

  it('should show connection form when no leagues exist', async () => {
    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    })

    render(<HomePage />)

    // Switch to leagues tab
    const leaguesTab = screen.getByRole('button', { name: /league integration/i })
    await userEvent.click(leaguesTab)

    // Should show connection form
    expect(screen.getByTestId('league-connection')).toBeInTheDocument()
    expect(screen.queryByText('Connected Leagues')).not.toBeInTheDocument()
  })

  it('should allow selecting a league and viewing its roster', async () => {
    const mockLeagues = [
      {
        id: 'espn_123456_2025',
        name: 'Test League',
        platform: 'ESPN',
        season: '2025',
        teamCount: 10,
        isActive: true,
        lastSyncAt: '2025-01-01T00:00:00Z',
      },
    ]

    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockLeagues,
    })

    render(<HomePage />)

    // Switch to leagues tab
    const leaguesTab = screen.getByRole('button', { name: /league integration/i })
    await userEvent.click(leaguesTab)

    // Wait for leagues to load
    await waitFor(() => {
      expect(screen.getByText('Test League')).toBeInTheDocument()
    })

    // Click on the league
    const leagueButton = screen.getByText('Test League')
    await userEvent.click(leagueButton)

    // Should show league roster
    expect(screen.getByTestId('league-roster')).toBeInTheDocument()
    expect(screen.getByText('League Roster for Test League')).toBeInTheDocument()

    // Should be able to go back
    const backButton = screen.getByText('Back')
    await userEvent.click(backButton)

    // Should show leagues list again
    expect(screen.getByText('Connected Leagues')).toBeInTheDocument()
  })

  it('should handle connecting a new league and add it to the list', async () => {
    const mockLeagues = [
      {
        id: 'espn_123456_2025',
        name: 'Existing League',
        platform: 'ESPN',
        season: '2025',
        teamCount: 10,
        isActive: true,
        lastSyncAt: '2025-01-01T00:00:00Z',
      },
    ]

    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockLeagues,
    })

    render(<HomePage />)

    // Switch to leagues tab
    const leaguesTab = screen.getByRole('button', { name: /league integration/i })
    await userEvent.click(leaguesTab)

    // Wait for leagues to load
    await waitFor(() => {
      expect(screen.getByText('Existing League')).toBeInTheDocument()
    })

    // Connect a new league
    const connectButton = screen.getByText('Connect League')
    await userEvent.click(connectButton)

    // Should now show both leagues
    expect(screen.getByText('Existing League')).toBeInTheDocument()
    expect(screen.getByText('New League')).toBeInTheDocument()
  })

  it('should highlight selected league', async () => {
    const mockLeagues = [
      {
        id: 'espn_123456_2025',
        name: 'Test League',
        platform: 'ESPN',
        season: '2025',
        teamCount: 10,
        isActive: true,
        lastSyncAt: '2025-01-01T00:00:00Z',
      },
    ]

    ;(fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockLeagues,
    })

    render(<HomePage />)

    // Switch to leagues tab
    const leaguesTab = screen.getByRole('button', { name: /league integration/i })
    await userEvent.click(leaguesTab)

    // Wait for leagues to load
    await waitFor(() => {
      expect(screen.getByText('Test League')).toBeInTheDocument()
    })

    // Click on the league
    const leagueButton = screen.getByText('Test League').closest('button')
    await userEvent.click(leagueButton!)

    // Should have selected styling
    expect(leagueButton).toHaveClass('border-blue-500', 'bg-blue-50')
  })
})