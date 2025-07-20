import { PrismaClient } from '@prisma/client'

const prisma = new PrismaClient()

async function seedDevData() {
  console.log('🌱 Seeding development data...')

  try {
    // Create a sample league with realistic data
    const league = await prisma.league.upsert({
      where: { id: 'dev_espn_123456_2025' },
      update: {},
      create: {
        id: 'dev_espn_123456_2025',
        platform: 'ESPN',
        externalId: '123456',
        season: '2025',
        name: 'JUICED (Dev League)',
        teamCount: 10,
        isActive: true,
        settings: {
          currentMatchupPeriod: 1,
          finalScoringPeriod: 23,
          isActive: true,
          latestScoringPeriod: 1
        },
        lastSyncAt: new Date(),
        createdAt: new Date(),
        updatedAt: new Date()
      }
    })

    console.log('✅ Created league:', league.name)

    // Create sample teams with realistic names and stats
    const teamsData = [
      { name: 'Team COUG', abbrev: 'COUG', owner: 'John Smith', wins: 8, losses: 4, points: 84.50 },
      { name: 'Team BP', abbrev: 'BP', owner: 'Sarah Johnson', wins: 7, losses: 5, points: 83.52 },
      { name: 'Team SHC', abbrev: 'SHC', owner: 'Mike Wilson', wins: 7, losses: 5, points: 82.52 },
      { name: 'Team WORK', abbrev: 'WORK', owner: 'Lisa Davis', wins: 6, losses: 6, points: 74.60 },
      { name: 'Team TR', abbrev: 'TR', owner: 'Chris Brown', wins: 6, losses: 6, points: 68.64 },
      { name: 'Team BLEW', abbrev: 'BLEW', owner: 'Alex Garcia', wins: 5, losses: 7, points: 61.72 },
      { name: 'Team JAMC', abbrev: 'JAMC', owner: 'Jordan Lee', wins: 5, losses: 7, points: 58.73 },
      { name: 'Team ROP', abbrev: 'ROP', owner: 'Taylor Martinez', wins: 4, losses: 8, points: 58.76 },
      { name: 'Team NOTO', abbrev: 'NOTO', owner: 'Casey Anderson', wins: 4, losses: 8, points: 57.73 },
      { name: 'Team BOOM', abbrev: 'BOOM', owner: 'Morgan Taylor', wins: 3, losses: 9, points: 40.93 }
    ]

    for (let i = 0; i < teamsData.length; i++) {
      const teamData = teamsData[i]
      
      const team = await prisma.team.upsert({
        where: {
          leagueId_externalId: {
            leagueId: league.id,
            externalId: (i + 1).toString()
          }
        },
        update: {
          name: teamData.name,
          ownerName: teamData.owner,
          wins: teamData.wins,
          losses: teamData.losses,
          ties: 0,
          pointsFor: teamData.points,
          pointsAgainst: Math.random() * 80 + 40 // Random opponent points
        },
        create: {
          leagueId: league.id,
          externalId: (i + 1).toString(),
          name: teamData.name,
          ownerName: teamData.owner,
          wins: teamData.wins,
          losses: teamData.losses,
          ties: 0,
          pointsFor: teamData.points,
          pointsAgainst: Math.random() * 80 + 40
        }
      })

      console.log(`✅ Created team: ${team.name} (${team.ownerName})`)
    }

    // Create some sample players for demonstration
    const playersData = [
      { id: 545361, name: 'Mike Trout', position: 'OF' },
      { id: 592450, name: 'Aaron Judge', position: 'OF' },
      { id: 605141, name: 'Mookie Betts', position: 'OF' },
      { id: 596019, name: 'Francisco Lindor', position: 'SS' },
      { id: 571448, name: 'José Altuve', position: '2B' }
    ]

    for (const playerData of playersData) {
      await prisma.player.upsert({
        where: { id: playerData.id },
        update: {},
        create: {
          id: playerData.id,
          fullName: playerData.name,
          firstName: playerData.name.split(' ')[0],
          lastName: playerData.name.split(' ').slice(1).join(' '),
          primaryPosition: playerData.position,
          active: true
        }
      })
    }

    console.log('✅ Created sample players')

    // Add some sample stats for players first (required for roster slots)
    console.log('Creating player stats...')
    for (const playerData of playersData) {
      await prisma.playerStats.upsert({
        where: {
          playerId_season: {
            playerId: playerData.id,
            season: '2025'
          }
        },
        update: {},
        create: {
          playerId: playerData.id,
          season: '2025',
          gamesPlayed: Math.floor(Math.random() * 50) + 100,
          atBats: Math.floor(Math.random() * 100) + 400,
          runs: Math.floor(Math.random() * 50) + 50,
          hits: Math.floor(Math.random() * 100) + 120,
          homeRuns: Math.floor(Math.random() * 30) + 15,
          rbi: Math.floor(Math.random() * 50) + 60,
          stolenBases: Math.floor(Math.random() * 20) + 5,
          battingAverage: 0.250 + Math.random() * 0.100,
          onBasePercentage: 0.300 + Math.random() * 0.100,
          sluggingPercentage: 0.400 + Math.random() * 0.200
        }
      })
    }

    // Create roster slots to connect players to teams
    console.log('Creating roster slots...')
    const teams = await prisma.team.findMany({
      where: { leagueId: league.id }
    })

    // Assign players to teams with different positions
    for (let i = 0; i < teams.length && i < playersData.length; i++) {
      const team = teams[i]
      const player = playersData[i]
      
      await prisma.rosterSlot.upsert({
        where: {
          teamId_playerId_season: {
            teamId: team.id,
            playerId: player.id,
            season: '2025'
          }
        },
        update: {},
        create: {
          teamId: team.id,
          playerId: player.id,
          season: '2025',
          position: player.position === 'OF' ? 'OF' : player.position,
          acquisitionType: 'DRAFT',
          acquisitionDate: new Date('2025-03-01'),
          isActive: true
        }
      })
    }

    console.log('✅ Created roster slots and player stats')

    console.log('\n🎉 Development data seeded successfully!')
    console.log('📊 Created:')
    console.log(`   • 1 League: ${league.name}`)
    console.log(`   • ${teamsData.length} Teams with realistic stats`)
    console.log(`   • ${playersData.length} Sample players with roster slots and stats`)
    console.log('\n💡 Your league data will now persist between server restarts!')

  } catch (error) {
    console.error('❌ Error seeding development data:', error)
    throw error
  } finally {
    await prisma.$disconnect()
  }
}

// Run the seed function
if (require.main === module) {
  seedDevData()
    .catch((error) => {
      console.error(error)
      process.exit(1)
    })
}

export { seedDevData }