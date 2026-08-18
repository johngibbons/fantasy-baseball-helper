/**
 * Tests for the dashboard at src/app/page.tsx.
 *
 * This file previously tested a league-connection UI — loading leagues,
 * showing a connection form, selecting a league to view its roster. None of
 * that lives here any more; the home page was rebuilt as a valuations
 * dashboard and league management moved to /leagues, where
 * LeagueConnection.test.tsx and the LeagueRoster suites cover it. Those tests
 * were asserting against a page that no longer exists, so they are replaced
 * with coverage of what this page actually does.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Dashboard from '../../app/page'
import { getStatsSummary, StatsSummary } from '../../lib/valuations-api'

jest.mock('../../lib/valuations-api', () => ({
  getStatsSummary: jest.fn(),
}))

const mockGetStatsSummary = getStatsSummary as jest.MockedFunction<
  typeof getStatsSummary
>

const summary: StatsSummary = {
  total_players: 1356,
  total_hitters: 660,
  total_pitchers: 696,
  top_5: [
    {
      mlb_id: 669373,
      full_name: 'Tarik Skubal',
      primary_position: 'SP',
      team: 'DET',
      overall_rank: 1,
      total_zscore: 2.32,
      player_type: 'pitcher',
    },
  ],
}

describe('Dashboard', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    global.fetch = jest.fn()
  })

  it('shows a loading state until the summary resolves', async () => {
    let resolve: (value: StatsSummary) => void = () => {}
    mockGetStatsSummary.mockReturnValue(
      new Promise<StatsSummary>((r) => { resolve = r }),
    )

    render(<Dashboard />)
    expect(screen.getByText('Loading data...')).toBeInTheDocument()

    resolve(summary)
    await waitFor(() => {
      expect(screen.queryByText('Loading data...')).not.toBeInTheDocument()
    })
  })

  it('renders the ranked player counts once loaded', async () => {
    mockGetStatsSummary.mockResolvedValue(summary)

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText('1356')).toBeInTheDocument()
    })
    expect(screen.getByText('Total Ranked')).toBeInTheDocument()
    expect(screen.getByText('660')).toBeInTheDocument()
    expect(screen.getByText('696')).toBeInTheDocument()
  })

  it('explains how to start the backend when the summary fails', async () => {
    mockGetStatsSummary.mockRejectedValue(new Error('fetch failed'))

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText('Backend not connected')).toBeInTheDocument()
    })
    // The page shows the commands to run, which is the actionable part.
    expect(screen.getByText(/uvicorn backend.api.main:app/)).toBeInTheDocument()
  })

  it('refreshes projections and reports how many players were updated', async () => {
    mockGetStatsSummary.mockResolvedValue(summary)
    ;(global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ total_players: 1400, sources: ['ATC', 'Steamer'] }),
    })

    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /refresh projections/i }))
        .toBeInTheDocument()
    })

    await userEvent.click(
      screen.getByRole('button', { name: /refresh projections/i }),
    )

    await waitFor(() => {
      expect(screen.getByText('Updated: 1400 players (ATC, Steamer)'))
        .toBeInTheDocument()
    })
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/refresh-projections?season=2026',
      expect.objectContaining({ method: 'POST' }),
    )
    // A successful refresh reloads the summary.
    expect(mockGetStatsSummary).toHaveBeenCalledTimes(2)
  })

  it('surfaces the reason a refresh failed', async () => {
    mockGetStatsSummary.mockResolvedValue(summary)
    ;(global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({ detail: 'FanGraphs API error' }),
    })

    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /refresh projections/i }))
        .toBeInTheDocument()
    })

    await userEvent.click(
      screen.getByRole('button', { name: /refresh projections/i }),
    )

    await waitFor(() => {
      expect(screen.getByText('Failed: FanGraphs API error')).toBeInTheDocument()
    })
  })

  it('does not offer a refresh while the backend is unreachable', async () => {
    mockGetStatsSummary.mockRejectedValue(new Error('fetch failed'))

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText('Backend not connected')).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('button', { name: /refresh projections/i }),
    ).not.toBeInTheDocument()
  })
})
