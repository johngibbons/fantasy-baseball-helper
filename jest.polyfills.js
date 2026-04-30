// jest.polyfills.js
// Polyfill Web Fetch API globals required by Next.js 15 at module-load time.
// Must run via setupFiles (before test framework) so Next.js server code can be
// imported without crashing on Node 16 which lacks these globals natively.
'use strict'

if (typeof globalThis.Request === 'undefined') {
  class Request {
    constructor(input, init) {
      this.url = typeof input === 'string' ? input : input.url
      this.method = (init && init.method) || 'GET'
      this.headers = (init && init.headers) || {}
      this.body = (init && init.body) || null
    }
  }
  class Response {
    constructor(body, init) {
      this.body = body
      this.status = (init && init.status) || 200
      this.ok = this.status >= 200 && this.status < 300
      this.statusText = (init && init.statusText) || ''
    }
    async json() { return JSON.parse(this.body) }
    async text() { return String(this.body) }
  }
  class Headers {
    constructor(init) { this._headers = Object.assign({}, init) }
    get(name) {
      const val = this._headers[name.toLowerCase()]
      return val !== undefined ? val : null
    }
    set(name, value) { this._headers[name.toLowerCase()] = value }
    has(name) { return name.toLowerCase() in this._headers }
  }
  globalThis.Request = Request
  globalThis.Response = Response
  globalThis.Headers = Headers
}
