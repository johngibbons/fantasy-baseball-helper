import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function GET() {
  try {
    // Test database connection
    const playerCount = await prisma.player.count()
    const leagueCount = await prisma.league.count()
    
    console.log('Prisma models available:', Object.keys(prisma))
    
    return NextResponse.json({ 
      success: true,
      message: 'API is working',
      playerCount,
      leagueCount,
      prismaModels: Object.keys(prisma)
    })
  } catch (error) {
    console.error('Test API error:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Database connection failed' 
    }, { status: 500 })
  }
}