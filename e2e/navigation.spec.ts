import { test, expect } from '@playwright/test'

test.describe('Navigation and Layout', () => {
  test('should load the homepage successfully', async ({ page }) => {
    await page.goto('/')
    
    // Check main heading
    await expect(page.locator('h1')).toContainText('Fantasy Baseball Helper')
    
    // Check navigation tabs
    await expect(page.locator('text=Player Search & Stats')).toBeVisible()
    await expect(page.locator('text=League Integration')).toBeVisible()
  })

  test('should switch between tabs correctly', async ({ page }) => {
    await page.goto('/')
    
    // Default tab should be Player Search
    await expect(page.locator('text=Search for MLB players')).toBeVisible()
    
    // Switch to League Integration
    await page.click('text=League Integration')
    await expect(page.locator('text=Connect Your Fantasy League')).toBeVisible()
    
    // Switch back to Player Search
    await page.click('text=Player Search & Stats')
    await expect(page.locator('text=Search for MLB players')).toBeVisible()
  })

  test('should be responsive on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto('/')
    
    // Check that content is still visible on mobile
    await expect(page.locator('h1')).toBeVisible()
    await expect(page.locator('text=Player Search & Stats')).toBeVisible()
    await expect(page.locator('text=League Integration')).toBeVisible()
  })

  test('should have proper page title and meta', async ({ page }) => {
    await page.goto('/')
    
    await expect(page).toHaveTitle(/Fantasy Baseball Helper/)
  })

  test('should handle keyboard navigation', async ({ page }) => {
    await page.goto('/')
    
    // Tab navigation should work
    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')
    
    // Should be able to activate tabs with Enter/Space
    await page.keyboard.press('Enter')
    
    // Should maintain accessibility
    const focusedElement = await page.locator(':focus')
    await expect(focusedElement).toBeVisible()
  })
})