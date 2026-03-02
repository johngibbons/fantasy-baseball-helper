import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

export async function POST(req: NextRequest) {
  const season = req.nextUrl.searchParams.get('season') || '2026'

  try {
    const res = await fetch(`${BACKEND_URL}/api/projections/refresh?season=${season}`, {
      method: 'POST',
      signal: AbortSignal.timeout(120_000), // 2 minutes
    })

    const data = await res.json().catch(() => null)

    if (!res.ok) {
      return NextResponse.json(
        data || { detail: `Backend returned ${res.status}` },
        { status: res.status }
      )
    }

    return NextResponse.json(data)
  } catch (e) {
    const message = e instanceof Error ? e.message : 'Unknown error'
    return NextResponse.json({ detail: message }, { status: 502 })
  }
}
