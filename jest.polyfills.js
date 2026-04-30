// jest.polyfills.js
// Polyfill Web Fetch API globals required by Next.js 15 at module-load time.
// Loaded at the top of jest.config.js (before require('next/jest')) so the
// polyfill is in place before Next.js code is evaluated. Node 18+ has these
// globals natively; this only matters when running under Node 16.
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
