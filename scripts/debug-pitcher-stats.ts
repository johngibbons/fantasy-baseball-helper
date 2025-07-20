import { PrismaClient } from '@prisma/client'

const prisma = new PrismaClient()

async function debugPitcherStats() {
  console.log('🔍 Analyzing current pitcher stats to find correct mappings...')

  // Check current stats for Max Fried
  const maxFried = await prisma.player.findFirst({
    where: { fullName: 'Max Fried' },
    include: { stats: true }
  })

  if (maxFried && maxFried.stats.length > 0) {
    const stats = maxFried.stats[0]
    console.log('\n📊 Max Fried current stored stats:')
    console.log('  ERA (onBasePercentage):', stats.onBasePercentage)
    console.log('  WHIP (sluggingPercentage):', stats.sluggingPercentage) 
    console.log('  Wins (runs):', stats.runs)
    console.log('  Strikeouts (strikeOuts):', stats.strikeOuts)
    console.log('  Games (gamesPlayed):', stats.gamesPlayed)
    console.log('  Innings (totalBases):', stats.totalBases)
    
    console.log('\n🎯 Expected Max Fried 2025 stats:')
    console.log('  ERA: 2.43')
    console.log('  WHIP: 1.01')
    console.log('  Wins: 11') 
    console.log('  Strikeouts: 113')
    console.log('  Games: 20')
    
    console.log('\n✅ Analysis:')
    if (Math.abs(stats.sluggingPercentage - 1.01) < 0.01) {
      console.log('  WHIP is CORRECT (key 41 works)')
    } else {
      console.log('  WHIP is wrong')
    }
    
    if (Math.abs(stats.onBasePercentage - 2.43) < 0.1) {
      console.log('  ERA is CORRECT')
    } else {
      console.log(`  ERA is wrong: showing ${stats.onBasePercentage}, should be 2.43`)
    }
    
    if (stats.runs === 11) {
      console.log('  Wins are CORRECT')
    } else {
      console.log(`  Wins are wrong: showing ${stats.runs}, should be 11`)
    }
    
    if (stats.strikeOuts === 113) {
      console.log('  Strikeouts are CORRECT')
    } else {
      console.log(`  Strikeouts are wrong: showing ${stats.strikeOuts}, should be 113`)
    }
  }

  // Check Tyler Rogers for saves
  const tylerRogers = await prisma.player.findFirst({
    where: { fullName: 'Tyler Rogers' },
    include: { stats: true }
  })

  if (tylerRogers && tylerRogers.stats.length > 0) {
    const stats = tylerRogers.stats[0]
    console.log('\n📊 Tyler Rogers current stored stats:')
    console.log('  Saves (doubles):', stats.doubles)
    console.log('  Expected saves: should be reasonable (0-50)')
    
    if (stats.doubles > 100) {
      console.log('  ❌ Saves are definitely wrong - too high')
    } else {
      console.log('  ✅ Saves might be correct')
    }
  }

  console.log('\n💡 Recommendations:')
  console.log('The ESPN stat key mappings need to be corrected.')
  console.log('Key 41 (WHIP) appears to be working correctly.')
  console.log('Other keys need to be identified through sync debugging.')
}

debugPitcherStats()
  .catch(console.error)
  .finally(() => prisma.$disconnect())