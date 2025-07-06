import { NextRequest, NextResponse } from 'next/server'
import { MLBApi } from '@/lib/mlb-api'
import { prisma } from '@/lib/prisma'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const name = searchParams.get('name')
    
    if (!name) {
      return NextResponse.json({ error: 'Name parameter is required' }, { status: 400 })
    }

    const players = await MLBApi.searchPlayers(name)
    
    // Store or update players in database
    for (const player of players) {
      await prisma.player.upsert({
        where: { id: player.id },
        update: {
          fullName: player.fullName,
          firstName: player.firstName,
          lastName: player.lastName,
          primaryNumber: player.primaryNumber,
          birthDate: player.birthDate ? new Date(player.birthDate) : null,
          currentAge: player.currentAge,
          birthCity: player.birthCity,
          birthStateProvince: player.birthStateProvince,
          birthCountry: player.birthCountry,
          height: player.height,
          weight: player.weight,
          active: player.active,
          primaryPosition: player.primaryPosition?.name,
          useName: player.useName,
          mlbDebutDate: player.mlbDebutDate ? new Date(player.mlbDebutDate) : null,
          batSide: player.batSide?.code,
          pitchHand: player.pitchHand?.code,
          nameSlug: player.nameSlug,
          strikeZoneTop: player.strikeZoneTop,
          strikeZoneBottom: player.strikeZoneBottom,
        },
        create: {
          id: player.id,
          fullName: player.fullName,
          firstName: player.firstName,
          lastName: player.lastName,
          primaryNumber: player.primaryNumber,
          birthDate: player.birthDate ? new Date(player.birthDate) : null,
          currentAge: player.currentAge,
          birthCity: player.birthCity,
          birthStateProvince: player.birthStateProvince,
          birthCountry: player.birthCountry,
          height: player.height,
          weight: player.weight,
          active: player.active,
          primaryPosition: player.primaryPosition?.name,
          useName: player.useName,
          mlbDebutDate: player.mlbDebutDate ? new Date(player.mlbDebutDate) : null,
          batSide: player.batSide?.code,
          pitchHand: player.pitchHand?.code,
          nameSlug: player.nameSlug,
          strikeZoneTop: player.strikeZoneTop,
          strikeZoneBottom: player.strikeZoneBottom,
        },
      })
    }

    return NextResponse.json({ players })
  } catch (error) {
    console.error('Error searching players:', error)
    return NextResponse.json({ error: 'Failed to search players' }, { status: 500 })
  }
}