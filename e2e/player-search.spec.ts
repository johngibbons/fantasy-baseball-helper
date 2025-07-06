import { test, expect } from '@playwright/test'

test.describe('Player Search Flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('should search for a player and view stats', async ({ page }) => {
    // Navigate to Player Search tab
    await page.click('text=Player Search & Stats')
    
    // Search for Mike Trout
    await page.fill('input[placeholder*="Search for a player"]', 'Mike Trout')
    await page.click('button:has-text("Search")')
    
    // Wait for search results
    await expect(page.locator('text=Mike Trout')).toBeVisible()
    await expect(page.locator('text=Outfield')).toBeVisible()
    
    // Click on Mike Trout to select him
    await page.click('button:has-text("Mike Trout")')
    
    // Verify player stats are displayed
    await expect(page.locator('text=Player Statistics')).toBeVisible()
    await expect(page.locator('text=Mike Trout')).toBeVisible()
    
    // Test season selector
    await page.selectOption('select', '2023')
    await expect(page.locator('text=2023')).toBeVisible()
  })

  test('should handle search with no results', async ({ page }) => {
    await page.click('text=Player Search & Stats')
    
    await page.fill('input[placeholder*="Search for a player"]', 'NonexistentPlayer12345')
    await page.click('button:has-text("Search")')
    
    await expect(page.locator('text=No players found')).toBeVisible()
  })

  test('should handle search errors gracefully', async ({ page }) => {
    // Mock network failure
    await page.route('/api/players/search*', route => route.abort())
    
    await page.click('text=Player Search & Stats')
    await page.fill('input[placeholder*="Search for a player"]', 'Test Player')
    await page.click('button:has-text("Search")')
    
    await expect(page.locator('text=Error searching players')).toBeVisible()
  })

  test('should display loading state during search', async ({ page }) => {
    // Delay the API response
    await page.route('/api/players/search*', route => {
      setTimeout(() => route.continue(), 1000)
    })
    
    await page.click('text=Player Search & Stats')
    await page.fill('input[placeholder*="Search for a player"]', 'Mike Trout')
    await page.click('button:has-text("Search")')
    
    await expect(page.locator('text=Searching...')).toBeVisible()
  })
})