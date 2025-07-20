import { TextEncoder, TextDecoder } from 'util'

// Polyfill for Next.js Web APIs in test environment
global.TextEncoder = TextEncoder
global.TextDecoder = TextDecoder

// Mock the Request and Response objects for Next.js API testing
if (!global.Request) {
  global.Request = class Request {
    url: string
    method: string
    headers: Map<string, string>
    body: any

    constructor(url: string, init?: any) {
      this.url = url
      this.method = init?.method || 'GET'
      this.headers = new Map()
      this.body = init?.body
      
      if (init?.headers) {
        Object.entries(init.headers).forEach(([key, value]) => {
          this.headers.set(key, value as string)
        })
      }
    }

    async json() {
      if (typeof this.body === 'string') {
        return JSON.parse(this.body)
      }
      return this.body
    }
  } as any
}

if (!global.Response) {
  global.Response = class Response {
    status: number
    body: any

    constructor(body?: any, init?: any) {
      this.body = body
      this.status = init?.status || 200
    }

    async json() {
      if (typeof this.body === 'string') {
        return JSON.parse(this.body)
      }
      return this.body
    }
  } as any
}

// Simple test setup without database for now
beforeEach(() => {
  // Clear all mocks before each test
  jest.clearAllMocks()
})

// This file needs to have at least one test or export
describe('Test Setup', () => {
  it('should be configured correctly', () => {
    expect(true).toBe(true)
  })
})