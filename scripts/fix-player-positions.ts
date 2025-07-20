import { PrismaClient } from '@prisma/client'

const prisma = new PrismaClient()

async function fixPlayerPositions() {
  console.log('🔧 Fixing player positions based on stat analysis...')

  // Get all players with stats
  const players = await prisma.player.findMany({
    include: {
      stats: {
        take: 1,
        orderBy: { season: 'desc' }
      }
    }
  })

  let fixed = 0
  
  for (const player of players) {
    let correctedPosition = player.primaryPosition
    
    // Analyze stats to determine correct position
    if (player.stats.length > 0) {
      const stats = player.stats[0]
      
      // Check for pitcher stats (non-zero pitching stats)
      const isPitcher = (
        stats.onBasePercentage !== null && stats.onBasePercentage > 0 && stats.onBasePercentage < 50 // ERA
      ) || (
        stats.sluggingPercentage !== null && stats.sluggingPercentage > 0 && stats.sluggingPercentage < 5 // WHIP
      ) || (
        stats.gamesPlayed !== null && stats.gamesPlayed > 0 && 
        stats.homeRuns === 0 && stats.rbi === 0 && stats.battingAverage === 0 // Pitcher with zero hitting stats
      )
      
      // Check for position player stats (non-zero hitting stats)
      const isPositionPlayer = (
        stats.homeRuns !== null && stats.homeRuns > 0
      ) || (
        stats.rbi !== null && stats.rbi > 0
      ) || (
        stats.battingAverage !== null && stats.battingAverage > 0.1 // Real batting average
      )
      
      if (isPitcher && !isPositionPlayer) {
        // This is a pitcher - determine SP vs RP based on games started (stored in atBats field)
        const gamesStarted = stats.atBats || 0
        correctedPosition = gamesStarted > 10 ? 'SP' : 'RP'
      } else if (isPositionPlayer && !isPitcher) {
        // This is a position player - fix known misclassified ones
        const knownPositions: { [key: string]: string } = {
          'Juan Soto': 'OF',
          'Lawrence Butler': 'OF', 
          'Jackson Chourio': 'OF',
          'Marcus Semien': 'SS',
          'Seiya Suzuki': 'OF',
          'Rafael Devers': '3B',
          'Corey Seager': 'SS',
          'Nick Kurtz': '1B',
          'Ozzie Albies': '2B',
          'Jordan Westburg': '3B',
          'Adley Rutschman': 'C',
          'Jazz Chisholm Jr.': '2B',
          'Jonathan Aranda': '1B',
          'Ivan Herrera': 'C',
          'Jurickson Profar': 'OF'
        }
        
        if (knownPositions[player.fullName]) {
          correctedPosition = knownPositions[player.fullName]
        }
      }
    }
    
    // Known pitchers that might not have stats yet
    const knownPitchers: { [key: string]: string } = {
      'Max Fried': 'SP',
      'Cole Ragans': 'SP', 
      'Framber Valdez': 'SP',
      'Joe Boyle': 'SP',
      'Joe Ryan': 'SP',
      'Michael Wacha': 'SP',
      'Roki Sasaki': 'SP',
      'Ryan Pepiot': 'SP',
      'Emmet Sheehan': 'SP',
      'Tyler Rogers': 'RP',
      'Kris Bubic': 'RP',
      'Randy Rodriguez': 'RP',
      'Ronny Henriquez': 'RP'
    }
    
    // Known position players that might be misclassified
    const knownPositionPlayers: { [key: string]: string } = {
      'Juan Soto': 'OF',
      'Lawrence Butler': 'OF', 
      'Jackson Chourio': 'OF',
      'Marcus Semien': 'SS',
      'Seiya Suzuki': 'OF',
      'Rafael Devers': '3B',
      'Corey Seager': 'SS',
      'Nick Kurtz': '1B',
      'Ozzie Albies': '2B',
      'Jordan Westburg': '3B',
      'Adley Rutschman': 'C',
      'Jazz Chisholm Jr.': '2B',
      'Jonathan Aranda': '1B',
      'Ivan Herrera': 'C',
      'Jurickson Profar': 'OF'
    }
    
    if (knownPitchers[player.fullName]) {
      correctedPosition = knownPitchers[player.fullName]
    } else if (knownPositionPlayers[player.fullName]) {
      correctedPosition = knownPositionPlayers[player.fullName]
    }
    
    // Update if position changed
    if (correctedPosition !== player.primaryPosition) {
      console.log(`📝 ${player.fullName}: ${player.primaryPosition} → ${correctedPosition}`)
      
      await prisma.player.update({
        where: { id: player.id },
        data: { primaryPosition: correctedPosition }
      })
      
      fixed++
    }
  }
  
  console.log(`✅ Fixed ${fixed} player positions`)
}

fixPlayerPositions()
  .catch(console.error)
  .finally(() => prisma.$disconnect())