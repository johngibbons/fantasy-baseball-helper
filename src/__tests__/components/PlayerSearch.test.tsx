import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PlayerSearch from '../../components/PlayerSearch'

// Mock the fetch function
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('PlayerSearch', () => {
  const mockOnPlayerSelect = jest.fn()

  beforeEach(() => {
    mockFetch.mockClear()
    mockOnPlayerSelect.mockClear()
  })

  it('renders search input and button', () => {
    render(<PlayerSearch onPlayerSelect={mockOnPlayerSelect} />)
    
    expect(screen.getByPlaceholderText('Search for a player (e.g., Mike Trout)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument()
  })

  it('handles search input change', async () => {
    const user = userEvent.setup()
    render(<PlayerSearch onPlayerSelect={mockOnPlayerSelect} />)
    
    const searchInput = screen.getByPlaceholderText('Search for a player (e.g., Mike Trout)')
    await user.type(searchInput, 'Mike Trout')
    
    expect(searchInput).toHaveValue('Mike Trout')
  })

  it('performs search and displays results', async () => {
    const user = userEvent.setup()
    const mockPlayers = [
      {
        id: 545361,
        fullName: 'Mike Trout',
        firstName: 'Mike',
        lastName: 'Trout',
        primaryPosition: { name: 'Outfield', abbreviation: 'OF' },
        primaryNumber: '27',
        birthCity: 'Vineland',
        birthStateProvince: 'NJ',
        currentAge: 32,
        batSide: { code: 'R' },
        pitchHand: { code: 'R' },
        height: "6' 2\"",
        weight: 235,
        active: true
      }
    ]

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ players: mockPlayers })
    })

    render(<PlayerSearch onPlayerSelect={mockOnPlayerSelect} />)
    
    const searchInput = screen.getByPlaceholderText('Search for a player (e.g., Mike Trout)')
    const searchButton = screen.getByRole('button', { name: 'Search' })
    
    await user.type(searchInput, 'Mike Trout')
    await user.click(searchButton)

    await waitFor(() => {
      expect(screen.getByText('Mike Trout')).toBeInTheDocument()
      expect(screen.getByText('Search Results:')).toBeInTheDocument()
    })

    expect(mockFetch).toHaveBeenCalledWith('/api/players/search?name=Mike%20Trout')
  })

  it('handles player selection', async () => {
    const user = userEvent.setup()
    const mockPlayers = [
      {
        id: 545361,
        fullName: 'Mike Trout',
        firstName: 'Mike',
        lastName: 'Trout',
        primaryPosition: { name: 'Outfield', abbreviation: 'OF' },
        primaryNumber: '27',
        birthCity: 'Vineland',
        birthStateProvince: 'NJ',
        currentAge: 32,
        batSide: { code: 'R' },
        pitchHand: { code: 'R' },
        height: "6' 2\"",
        weight: 235,
        active: true
      }
    ]

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ players: mockPlayers })
    })

    render(<PlayerSearch onPlayerSelect={mockOnPlayerSelect} />)
    
    const searchInput = screen.getByPlaceholderText('Search for a player (e.g., Mike Trout)')
    const searchButton = screen.getByRole('button', { name: 'Search' })
    
    await user.type(searchInput, 'Mike Trout')
    await user.click(searchButton)

    await waitFor(() => {
      expect(screen.getByText('Mike Trout')).toBeInTheDocument()
    })

    const playerButton = screen.getByRole('button', { name: /Mike Trout/ })
    await user.click(playerButton)

    expect(mockOnPlayerSelect).toHaveBeenCalledWith(mockPlayers[0])
  })

  it('displays loading state during search', async () => {
    const user = userEvent.setup()
    
    mockFetch.mockImplementationOnce(() => new Promise(resolve => setTimeout(() => resolve({
      ok: true,
      json: async () => ({ players: [] })
    }), 100)))

    render(<PlayerSearch onPlayerSelect={mockOnPlayerSelect} />)
    
    const searchInput = screen.getByPlaceholderText('Search for a player (e.g., Mike Trout)')
    const searchButton = screen.getByRole('button', { name: 'Search' })
    
    await user.type(searchInput, 'Mike Trout')
    await user.click(searchButton)

    expect(screen.getByText('Searching...')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.queryByText('Searching...')).not.toBeInTheDocument()
    })
  })

  it('displays error message on search failure', async () => {
    const user = userEvent.setup()
    
    mockFetch.mockRejectedValueOnce(new Error('Network error'))

    render(<PlayerSearch onPlayerSelect={mockOnPlayerSelect} />)
    
    const searchInput = screen.getByPlaceholderText('Search for a player (e.g., Mike Trout)')
    const searchButton = screen.getByRole('button', { name: 'Search' })
    
    await user.type(searchInput, 'Mike Trout')
    await user.click(searchButton)

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument()
    })
  })

  it('displays error from API response', async () => {
    const user = userEvent.setup()
    
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ error: 'API Error' })
    })

    render(<PlayerSearch onPlayerSelect={mockOnPlayerSelect} />)
    
    const searchInput = screen.getByPlaceholderText('Search for a player (e.g., Mike Trout)')
    const searchButton = screen.getByRole('button', { name: 'Search' })
    
    await user.type(searchInput, 'Test Player')
    await user.click(searchButton)

    await waitFor(() => {
      expect(screen.getByText('API Error')).toBeInTheDocument()
    })
  })

  it('does not search with empty input', async () => {
    const user = userEvent.setup()

    render(<PlayerSearch onPlayerSelect={mockOnPlayerSelect} />)
    
    const searchButton = screen.getByRole('button', { name: 'Search' })
    await user.click(searchButton)

    expect(mockFetch).not.toHaveBeenCalled()
  })
})