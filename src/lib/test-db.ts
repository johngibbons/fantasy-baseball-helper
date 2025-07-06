import { PrismaClient } from '../../prisma/generated/test-client'
import { execSync } from 'child_process'
import { join } from 'path'

const prisma = new PrismaClient()

export async function setupTestDb() {
  // Generate test client
  execSync('npx prisma generate --schema=prisma/schema.test.prisma', {
    cwd: join(process.cwd()),
    stdio: 'inherit'
  })

  // Push schema to test database
  execSync('npx prisma db push --schema=prisma/schema.test.prisma', {
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