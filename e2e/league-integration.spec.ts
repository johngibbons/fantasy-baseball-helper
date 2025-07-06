import { test, expect } from '@playwright/test'

test.describe('League Integration Flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('should navigate to league integration and show ESPN form', async ({ page }) => {
    // Navigate to League Integration tab
    await page.click('text=League Integration')
    
    // Verify page content
    await expect(page.locator('text=Connect Your Fantasy League')).toBeVisible()
    await expect(page.locator('button:has-text("ESPN Fantasy")')).toBeVisible()
    await expect(page.locator('button:has-text("Yahoo Fantasy")')).toBeVisible()
    
    // Click ESPN Fantasy
    await page.click('button:has-text("ESPN Fantasy")')
    
    // Verify ESPN form appears
    await expect(page.locator('text=ESPN Fantasy Baseball Connection')).toBeVisible()
    await expect(page.locator('input[placeholder*="League ID"]')).toBeVisible()
    await expect(page.locator('input[placeholder*="SWID"]')).toBeVisible()
    await expect(page.locator('input[placeholder*="ESPN_S2"]')).toBeVisible()
    await expect(page.locator('button:has-text("Connect League")')).toBeVisible()
  })

  test('should show Yahoo coming soon message', async ({ page }) => {
    await page.click('text=League Integration')
    await page.click('button:has-text("Yahoo Fantasy")')
    
    await expect(page.locator('text=Yahoo Fantasy Sports API integration coming soon')).toBeVisible()
  })

  test('should validate ESPN form inputs', async ({ page }) => {
    await page.click('text=League Integration')
    await page.click('button:has-text("ESPN Fantasy")')
    
    // Try to submit empty form
    await page.click('button:has-text("Connect League")')
    
    await expect(page.locator('text=All fields are required')).toBeVisible()
  })

  test('should handle successful ESPN league connection', async ({ page }) => {
    // Mock successful API response
    await page.route('/api/leagues/espn/connect', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          message: 'League connected successfully',
          league: {
            id: '1',
            name: 'Test League',
            provider: 'ESPN'
          }
        })
      })
    })

    await page.click('text=League Integration')
    await page.click('button:has-text("ESPN Fantasy")')
    
    // Fill form
    await page.fill('input[placeholder*="League ID"]', '123456')
    await page.fill('input[placeholder*="SWID"]', 'test_swid')
    await page.fill('input[placeholder*="ESPN_S2"]', 'test_espn_s2')
    
    await page.click('button:has-text("Connect League")')
    
    await expect(page.locator('text=League connected successfully')).toBeVisible()
  })

  test('should handle ESPN connection errors', async ({ page }) => {
    // Mock error response
    await page.route('/api/leagues/espn/connect', route => {
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({
          error: 'Invalid credentials'
        })
      })
    })

    await page.click('text=League Integration')
    await page.click('button:has-text("ESPN Fantasy")')
    
    await page.fill('input[placeholder*="League ID"]', '123456')
    await page.fill('input[placeholder*="SWID"]', 'invalid_swid')
    await page.fill('input[placeholder*="ESPN_S2"]', 'invalid_espn_s2')
    
    await page.click('button:has-text("Connect League")')
    
    await expect(page.locator('text=Error: Invalid credentials')).toBeVisible()
  })

  test('should show loading state during connection', async ({ page }) => {
    // Mock delayed response
    await page.route('/api/leagues/espn/connect', route => {
      setTimeout(() => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            message: 'League connected successfully',
            league: { id: '1', name: 'Test League', provider: 'ESPN' }
          })
        })
      }, 1000)
    })

    await page.click('text=League Integration')
    await page.click('button:has-text("ESPN Fantasy")')
    
    await page.fill('input[placeholder*="League ID"]', '123456')
    await page.fill('input[placeholder*="SWID"]', 'test_swid')
    await page.fill('input[placeholder*="ESPN_S2"]', 'test_espn_s2')
    
    await page.click('button:has-text("Connect League")')
    
    await expect(page.locator('text=Connecting...')).toBeVisible()
  })
})