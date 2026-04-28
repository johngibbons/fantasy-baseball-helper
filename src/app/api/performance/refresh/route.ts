// src/app/api/performance/refresh/route.ts

import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}))
    const season = body.season ?? 2026
    const playerType = body.player_type ?? 'all'

    const resp = await fetch(`${BACKEND_URL}/api/performance/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ season, player_type: playerType }),
    })

    if (!resp.ok) {
      const text = await resp.text()
      return NextResponse.json({ error: text }, { status: 502 })
    }

    const data = await resp.json()
    return NextResponse.json({ ...data, refreshed_at: new Date().toISOString() })
  } catch (error: any) {
    console.error('Performance refresh error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to refresh stats' },
      { status: 500 },
    )
  }
}
