import { prisma } from '@/lib/prisma'

export async function getESPNCredentials(leagueId: string): Promise<{
  espnSwid: string
  espnS2: string
} | null> {
  const userLeague = await prisma.userLeague.findFirst({
    where: { leagueId },
    include: { user: true }
  })

  if (!userLeague?.user?.espnSwid || !userLeague?.user?.espnS2) {
    return null
  }

  return {
    espnSwid: userLeague.user.espnSwid,
    espnS2: userLeague.user.espnS2
  }
}
