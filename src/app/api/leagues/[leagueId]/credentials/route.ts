import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params

    const league = await prisma.league.findUnique({
      where: {
        id: leagueId
      },
      select: {
        id: true,
        settings: true
      }
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const settings = league.settings as any
    const credentials = settings?.credentials

    return NextResponse.json({
      has_credentials: !!(credentials?.espn_s2 && credentials?.swid),
      default_team_id: credentials?.default_team_id ?? null
    })
  } catch (error) {
    console.error('Error fetching league credentials:', error)
    return NextResponse.json(
      { error: 'Failed to fetch league credentials' },
      { status: 500 }
    )
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params
    const body = await request.json()
    const { espn_s2, swid, default_team_id } = body

    if (!espn_s2 || !swid) {
      return NextResponse.json(
        { error: 'espn_s2 and swid are required' },
        { status: 400 }
      )
    }

    const league = await prisma.league.findUnique({
      where: { id: leagueId },
      select: { id: true, settings: true }
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const existingSettings = (league.settings as Record<string, unknown>) ?? {}
    const credentials: Record<string, string> = { espn_s2, swid }
    if (default_team_id !== undefined && default_team_id !== null) {
      credentials.default_team_id = default_team_id
    }

    const updatedSettings = {
      ...existingSettings,
      credentials
    }

    await prisma.league.update({
      where: { id: leagueId },
      data: { settings: updatedSettings }
    })

    return NextResponse.json({ ok: true })
  } catch (error) {
    console.error('Error saving league credentials:', error)
    return NextResponse.json(
      { error: 'Failed to save league credentials' },
      { status: 500 }
    )
  }
}
