// src/app/api/performance/refresh-status/route.ts

import { NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

export async function GET() {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/performance/refresh/status`, {
      cache: 'no-store',
    })
    if (!resp.ok) {
      const text = await resp.text()
      return NextResponse.json({ error: text }, { status: 502 })
    }
    const data = await resp.json()
    return NextResponse.json(data)
  } catch (error: any) {
    return NextResponse.json(
      { error: error.message || 'Failed to get refresh status' },
      { status: 500 },
    )
  }
}
