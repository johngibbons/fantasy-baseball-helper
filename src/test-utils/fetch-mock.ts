/**
 * Fetch mocking for components that make a concurrent request alongside the
 * one under test.
 *
 * `LeagueRoster` calls `fetchLeagueSettings()` and `fetchTeams()` from the same
 * effect, so the two are in flight together with no defined order. Tests that
 * queued responses with `mockResolvedValueOnce` assumed a single request:
 * whichever call landed first consumed the queued response and the other
 * received `undefined`, surfacing as "Cannot read properties of undefined
 * (reading 'json')" thrown from inside a catch block, several layers away from
 * the cause. Six suites failed this way.
 *
 * Ordered queues are still the right tool for genuinely sequential requests —
 * a roster is only fetched after the user picks a team. What they cannot model
 * is a concurrent request. So this helper answers the incidental URLs by
 * pattern and passes everything else through to the queue, which keeps the
 * existing sequential expectations meaningful.
 */

export interface MockResponse {
  ok?: boolean
  status?: number
  json?: unknown
}

/** Requests a component makes on its own that most tests do not assert on. */
export const INCIDENTAL_ROUTES: Record<string, MockResponse> = {
  // LeagueRoster loads scoring settings concurrently with teams.
  '/settings': { json: { scoringSettings: null } },
}

function toResponse(spec: MockResponse) {
  const status = spec.status ?? (spec.ok === false ? 500 : 200)
  return {
    ok: spec.ok ?? status < 400,
    status,
    json: async () => spec.json ?? {},
    text: async () => JSON.stringify(spec.json ?? {}),
  }
}

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.toString()
  return (input as Request)?.url ?? String(input)
}

/**
 * Install `global.fetch` so that incidental URLs are answered directly and
 * every other request falls through to `queue` — a `jest.fn()` the test drives
 * with `mockResolvedValueOnce` as before.
 *
 * ```ts
 * const mockFetch = jest.fn()
 * installFetchMock(mockFetch)
 * mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ teams }) })
 * ```
 *
 * A request that reaches the queue when it is empty throws with its URL, so
 * the next time production code adds a call the failure names itself instead
 * of surfacing as an undefined dereference.
 */
export function installFetchMock(
  queue: jest.Mock,
  routes: Record<string, MockResponse> = INCIDENTAL_ROUTES,
): void {
  global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input)

    for (const [pattern, spec] of Object.entries(routes)) {
      if (url.includes(pattern)) return toResponse(spec)
    }

    const result = await queue(input, init)
    if (result === undefined) {
      throw new Error(
        `fetch(${url}) had no queued response.\n` +
          `The component made more requests than the test queued. Add another ` +
          `mockResolvedValueOnce, or add the URL to the routes argument if it ` +
          `is incidental to what this test asserts.`,
      )
    }
    return result
  }) as unknown as typeof global.fetch
}
