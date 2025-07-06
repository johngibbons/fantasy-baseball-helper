import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LeagueConnection from '../../components/LeagueConnection'

// Mock fetch
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('LeagueConnection', () => {
  const mockOnLeagueConnected = jest.fn()

  beforeEach(() => {
    mockFetch.mockClear()
    mockOnLeagueConnected.mockClear()
  })

  it('renders provider selection buttons', () => {
    render(<LeagueConnection onLeagueConnected={mockOnLeagueConnected} />)
    
    expect(screen.getByText('Connect Your Fantasy League')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ESPN Fantasy/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Yahoo Fantasy/ })).toBeInTheDocument()
  })

  it('shows ESPN connection form when ESPN is selected', async () => {
    const user = userEvent.setup()
    render(<LeagueConnection onLeagueConnected={mockOnLeagueConnected} />)
    
    const espnButton = screen.getByRole('button', { name: /ESPN Fantasy/ })
    await user.click(espnButton)

    expect(screen.getByPlaceholderText('e.g., 123456')).toBeInTheDocument()
    expect(screen.getByDisplayValue('2025')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/ABC123-DEF4/)).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Long string starting with AE...')).toBeInTheDocument()
  })

  it('shows Yahoo connection form when Yahoo is selected', async () => {
    const user = userEvent.setup()
    render(<LeagueConnection onLeagueConnected={mockOnLeagueConnected} />)
    
    const yahooButton = screen.getByRole('button', { name: /Yahoo Fantasy/ })
    await user.click(yahooButton)

    expect(screen.getByPlaceholderText('Your Yahoo OAuth access token')).toBeInTheDocument()
    expect(screen.getByDisplayValue('2025')).toBeInTheDocument()
  })

  it('handles ESPN connection test', async () => {
    const user = userEvent.setup()
    
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true })
    })

    render(<LeagueConnection onLeagueConnected={mockOnLeagueConnected} />)
    
    const espnButton = screen.getByRole('button', { name: /ESPN Fantasy/ })
    await user.click(espnButton)

    const leagueIdInput = screen.getByPlaceholderText('e.g., 123456')
    const swidInput = screen.getByPlaceholderText(/ABC123-DEF4/)
    const espnS2Input = screen.getByPlaceholderText('Long string starting with AE...')

    await user.type(leagueIdInput, '123456')
    await user.type(swidInput, 'test_swid')
    await user.type(espnS2Input, 'test_espn_s2')

    const testButton = screen.getByRole('button', { name: 'Test ESPN Connection' })
    await user.click(testButton)

    expect(mockFetch).toHaveBeenCalledWith('/api/leagues/espn/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        leagueId: '123456',
        season: '2025',
        swid: 'test_swid',
        espn_s2: 'test_espn_s2'
      })
    })
  })

  it('handles ESPN connection errors', async () => {
    const user = userEvent.setup()
    
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ error: 'Invalid credentials' })
    })

    render(<LeagueConnection onLeagueConnected={mockOnLeagueConnected} />)
    
    const espnButton = screen.getByRole('button', { name: /ESPN Fantasy/ })
    await user.click(espnButton)

    const leagueIdInput = screen.getByPlaceholderText('e.g., 123456')
    const swidInput = screen.getByPlaceholderText(/ABC123-DEF4/)
    const espnS2Input = screen.getByPlaceholderText('Long string starting with AE...')

    await user.type(leagueIdInput, '123456')
    await user.type(swidInput, 'invalid_swid')
    await user.type(espnS2Input, 'invalid_espn_s2')

    const testButton = screen.getByRole('button', { name: 'Test ESPN Connection' })
    await user.click(testButton)

    await waitFor(() => {
      expect(screen.getByText(/Invalid credentials/)).toBeInTheDocument()
    })
  })

  it('shows loading state during connection test', async () => {
    const user = userEvent.setup()
    
    mockFetch.mockImplementationOnce(() => new Promise(resolve => setTimeout(() => resolve({
      ok: true,
      json: async () => ({ success: true })
    }), 100)))

    render(<LeagueConnection onLeagueConnected={mockOnLeagueConnected} />)
    
    const espnButton = screen.getByRole('button', { name: /ESPN Fantasy/ })
    await user.click(espnButton)

    const leagueIdInput = screen.getByPlaceholderText('e.g., 123456')
    const swidInput = screen.getByPlaceholderText(/ABC123-DEF4/)
    const espnS2Input = screen.getByPlaceholderText('Long string starting with AE...')

    await user.type(leagueIdInput, '123456')
    await user.type(swidInput, 'test_swid')
    await user.type(espnS2Input, 'test_espn_s2')

    const testButton = screen.getByRole('button', { name: 'Test ESPN Connection' })
    await user.click(testButton)

    expect(screen.getByRole('button', { name: 'Testing...' })).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Testing...' })).not.toBeInTheDocument()
    })
  })

  it('can navigate back to platform selection', async () => {
    const user = userEvent.setup()
    render(<LeagueConnection onLeagueConnected={mockOnLeagueConnected} />)
    
    const espnButton = screen.getByRole('button', { name: /ESPN Fantasy/ })
    await user.click(espnButton)

    expect(screen.getByPlaceholderText('e.g., 123456')).toBeInTheDocument()

    const backButton = screen.getByRole('button', { name: /Back/ })
    await user.click(backButton)

    expect(screen.getByText('Connect Your Fantasy League')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ESPN Fantasy/ })).toBeInTheDocument()
  })
})