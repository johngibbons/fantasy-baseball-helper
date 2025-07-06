import '@testing-library/jest-dom'
import { TextEncoder, TextDecoder } from 'util'

// Mock Next.js router
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
  }),
  useSearchParams: () => ({
    get: jest.fn(),
  }),
  usePathname: () => '/',
}))

// Mock Node.js globals for Next.js API routes
global.TextEncoder = TextEncoder
global.TextDecoder = TextDecoder

// Mock fetch
global.fetch = jest.fn()

// Mock environment variables
process.env.NODE_ENV = 'test'

// Clean up after each test
afterEach(() => {
  jest.clearAllMocks()
})