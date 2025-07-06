import { prisma } from '../../lib/prisma'

describe('Prisma Client', () => {
  it('should export a prisma instance', () => {
    expect(prisma).toBeDefined()
    expect(typeof prisma).toBe('object')
  })

  it('should have required database models', () => {
    expect(prisma.player).toBeDefined()
    expect(prisma.league).toBeDefined()
    expect(prisma.team).toBeDefined()
    expect(prisma.rosterSlot).toBeDefined()
  })
})