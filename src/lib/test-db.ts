import { execSync } from 'child_process'
import { join } from 'path'

// Use regular Prisma client for tests, with test database URL
import { PrismaClient } from '@prisma/client'

const prisma = new PrismaClient({
  datasources: {
    db: {
      url: process.env.NODE_ENV === 'test' 
        ? 'file:./test.db' 
        : process.env.DATABASE_URL
    }
  }
})

export async function setupTestDb() {
  // Generate main client (same schema)
  execSync('npx prisma generate', {
    cwd: join(process.cwd()),
    stdio: 'inherit'
  })

  // Push main schema to test database
  execSync('npx prisma db push', {
    cwd: join(process.cwd()),
    stdio: 'inherit'
  })

  return prisma
}

export async function teardownTestDb() {
  await prisma.$disconnect()
  
  // Clean up test database
  try {
    execSync('rm -f prisma/test.db*', {
      cwd: join(process.cwd()),
      stdio: 'ignore'
    })
  } catch (error) {
    // Ignore errors if files don't exist
  }
}

export async function clearTestDb() {
  // Clear all tables in reverse dependency order
  await prisma.rosterSlot.deleteMany()
  await prisma.playerStats.deleteMany()
  await prisma.team.deleteMany()
  await prisma.userLeague.deleteMany()
  await prisma.league.deleteMany()
  await prisma.player.deleteMany()
  await prisma.user.deleteMany()
}

export { prisma as testPrisma }