import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function GET() {
  try {
    const leagues = await prisma.league.findMany({
      select: {
        id: true,
        name: true,
        platform: true,
        season: true,
        teamCount: true,
        isActive: true,
        lastSyncAt: true,
      },
      where: {
        isActive: true,
      },
      orderBy: {
        lastSyncAt: 'desc',
      },
    })

    return NextResponse.json(leagues)
  } catch (error) {
    console.error('Error fetching leagues:', error)
    return NextResponse.json({ error: 'Failed to fetch leagues' }, { status: 500 })
  }
}