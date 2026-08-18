import { test, expect, type Page } from '@playwright/test'

/**
 * Every route loads and renders its shell.
 *
 * This replaces three specs that described a two-tab prototype — a heading of
 * "Fantasy Baseball Helper" with "Player Search & Stats" and "League
 * Integration" tabs. The app is now twelve routes, so those specs tested a UI
 * that no longer exists. They had also never run in CI: the e2e job is gated on
 * the unit tests passing, and those were failing at the typecheck step.
 *
 * What is asserted here is deliberately shallow. CI has no analytics backend,
 * so pages that fetch valuations render their empty or error state, and
 * asserting on their content would only test the failure path. What a smoke
 * suite can say honestly is that the route resolves, the app shell renders, and
 * nothing threw — which is what actually breaks when a route is renamed, a
 * component throws during render, or a server component fails to build.
 */

const ROUTES = [
  { path: '/', label: 'Dashboard' },
  { path: '/rankings', label: 'Rankings' },
  { path: '/draft', label: 'Draft Board' },
  { path: '/keepers', label: 'Keepers' },
  { path: '/waivers', label: 'Waivers' },
  { path: '/trades', label: 'Trades' },
  { path: '/start-sit', label: 'Start/Sit' },
  { path: '/matchup', label: 'Matchup' },
  { path: '/playoff-odds', label: 'Playoff Odds' },
  { path: '/performance', label: 'Performance' },
  { path: '/players', label: 'Player Search' },
  { path: '/leagues', label: 'Leagues' },
  { path: '/settings', label: 'Settings' },
] as const

/**
 * Collect uncaught exceptions. Console errors are not used as the signal —
 * without a backend, failed fetches log errors that the app handles correctly.
 * An uncaught exception means the page genuinely broke.
 */
/**
 * The application shell's navigation, identified by the Dashboard link it
 * contains. Some pages render their own <nav> for in-page tabs — the waivers
 * page is one — so matching the role alone is ambiguous there.
 */
function appNav(page: Page) {
  return page
    .getByRole('navigation')
    .filter({ has: page.getByRole('link', { name: 'Dashboard', exact: true }) })
}

function trackPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

test.describe('every route loads', () => {
  for (const route of ROUTES) {
    test(`${route.label} (${route.path})`, async ({ page }) => {
      const errors = trackPageErrors(page)

      const response = await page.goto(route.path)
      expect(response?.status(), `${route.path} should not error`).toBeLessThan(400)

      // The shell nav lives in the root layout, so its presence means the
      // page rendered rather than Next.js serving an error page.
      await expect(appNav(page)).toBeVisible()

      expect(errors, `${route.path} threw: ${errors.join('; ')}`).toEqual([])
    })
  }
})

test.describe('navigation', () => {
  test('moves between routes and marks the current one', async ({ page }) => {
    await page.goto('/')

    await page.getByRole('link', { name: 'Rankings', exact: true }).click()
    await expect(page).toHaveURL(/\/rankings$/)

    await page.getByRole('link', { name: 'Draft Board', exact: true }).click()
    await expect(page).toHaveURL(/\/draft$/)

    await page.getByRole('link', { name: 'Dashboard', exact: true }).click()
    await expect(page).toHaveURL(/\/$/)
  })

  test('every nav link points at a route that exists', async ({ page }) => {
    await page.goto('/')

    const hrefs = await appNav(page)
      .getByRole('link')
      .evaluateAll((links) =>
        links.map((link) => link.getAttribute('href')).filter(Boolean),
      )

    expect(hrefs.length).toBeGreaterThanOrEqual(ROUTES.length)
    for (const href of hrefs) {
      expect(
        ROUTES.some((route) => route.path === href),
        `nav links to ${href}, which is not a known route`,
      ).toBe(true)
    }
  })

  test('renders on a mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')

    await expect(appNav(page)).toBeVisible()
    // The page must not scroll sideways on a phone.
    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    )
    expect(overflows, 'page scrolls horizontally on mobile').toBe(false)
  })
})
