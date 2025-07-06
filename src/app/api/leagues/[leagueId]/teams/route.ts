import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function GET(
  request: NextRequest,
  { params }: { params: { leagueId: string } }
) {
  try {
    const { leagueId } = params

    const teams = await prisma.team.findMany({
      where: {
        leagueId: leagueId
      },
      orderBy: [
        { wins: 'desc' },
        { pointsFor: 'desc' }
      ]
    })

    return NextResponse.json({ teams })
  } catch (error) {
    console.error('Error fetching teams:', error)
    return NextResponse.json({ 
      error: 'Failed to fetch teams' 
    }, { status: 500 })
  }
}