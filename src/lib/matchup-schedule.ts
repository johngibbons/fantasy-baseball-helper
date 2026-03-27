// League 77166 matchup schedule (from ESPN league settings page)
// Matchup period ID → [start date, end date]
export const MATCHUP_SCHEDULE: Record<number, [string, string]> = {
  1:  ['2026-03-25', '2026-04-05'],
  2:  ['2026-04-06', '2026-04-12'],
  3:  ['2026-04-13', '2026-04-19'],
  4:  ['2026-04-20', '2026-04-26'],
  5:  ['2026-04-27', '2026-05-03'],
  6:  ['2026-05-04', '2026-05-10'],
  7:  ['2026-05-11', '2026-05-17'],
  8:  ['2026-05-18', '2026-05-24'],
  9:  ['2026-05-25', '2026-05-31'],
  10: ['2026-06-01', '2026-06-07'],
  11: ['2026-06-08', '2026-06-14'],
  12: ['2026-06-15', '2026-06-21'],
  13: ['2026-06-22', '2026-06-28'],
  14: ['2026-06-29', '2026-07-05'],
  15: ['2026-07-06', '2026-07-19'],
  16: ['2026-07-20', '2026-07-26'],
  17: ['2026-07-27', '2026-08-02'],
  18: ['2026-08-03', '2026-08-09'],
  19: ['2026-08-10', '2026-08-16'],
  20: ['2026-08-17', '2026-08-23'],
  21: ['2026-08-17', '2026-08-23'],
}

export function getMatchupDateRange(
  matchupPeriodId: number,
  today: Date,
): { startDate: string; endDate: string; daysRemaining: number } {
  const schedule = MATCHUP_SCHEDULE[matchupPeriodId]

  if (schedule) {
    const [startDate, endDate] = schedule
    const endDateObj = new Date(endDate + 'T23:59:59')

    // Count remaining days: tomorrow through end of matchup
    let daysRemaining = 0
    const cursor = new Date(today)
    cursor.setDate(today.getDate() + 1)
    while (cursor <= endDateObj) {
      daysRemaining++
      cursor.setDate(cursor.getDate() + 1)
    }

    return { startDate, endDate, daysRemaining }
  }

  // Fallback: Mon-Sun estimate for unknown matchup periods
  const dayOfWeek = today.getDay()
  const daysRemaining = dayOfWeek === 0 ? 0 : 7 - dayOfWeek
  const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek
  const monday = new Date(today)
  monday.setDate(today.getDate() + mondayOffset)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)

  return {
    startDate: monday.toISOString().split('T')[0],
    endDate: sunday.toISOString().split('T')[0],
    daysRemaining,
  }
}
