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
        name: true,
        platform: true,
        season: true,
        settings: true
      }
    })

    if (!league) {
      return NextResponse.json({ 
        error: 'League not found' 
      }, { status: 404 })
    }

    // Parse the settings JSON to extract scoring information
    const settings = league.settings as any
    
    return NextResponse.json({
      league: {
        id: league.id,
        name: league.name,
        platform: league.platform,
        season: league.season
      },
      scoringSettings: settings?.scoringSettings || null,
      rosterSettings: settings?.rosterSettings || null,
      acquisitionSettings: settings?.acquisitionSettings || null,
      generalSettings: {
        currentMatchupPeriod: settings?.currentMatchupPeriod || 0,
        finalScoringPeriod: settings?.finalScoringPeriod || 0,
        isActive: settings?.isActive ?? true,
        latestScoringPeriod: settings?.latestScoringPeriod || 0
      }
    })
  } catch (error) {
    console.error('Error fetching league settings:', error)
    return NextResponse.json({ 
      error: 'Failed to fetch league settings' 
    }, { status: 500 })
  }
}