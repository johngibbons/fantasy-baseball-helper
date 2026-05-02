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

export function getMatchupEndDateForDate(dateStr: string): string | null {
  for (const [, [start, end]] of Object.entries(MATCHUP_SCHEDULE)) {
    if (dateStr >= start && dateStr <= end) {
      return end
    }
  }
  return null
}

// Format a Date as YYYY-MM-DD using local timezone
export function toLocalDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function getMatchupDateRange(
  matchupPeriodId: number,
  today: Date,
): { startDate: string; endDate: string; daysRemaining: number } {
  const schedule = MATCHUP_SCHEDULE[matchupPeriodId]
  const todayStr = toLocalDateStr(today)

  if (schedule) {
    const [startDate, endDate] = schedule

    // Count remaining days: today through end of matchup (inclusive, since ESPN
    // stats typically don't reflect today's games until overnight processing)
    let daysRemaining = 0
    const cursor = new Date(today.getFullYear(), today.getMonth(), today.getDate())
    while (toLocalDateStr(cursor) <= endDate) {
      daysRemaining++
      cursor.setDate(cursor.getDate() + 1)
    }

    return { startDate, endDate, daysRemaining }
  }

  // Fallback: Mon-Sun estimate for unknown matchup periods
  const dayOfWeek = today.getDay()
  const daysRemaining = dayOfWeek === 0 ? 0 : 7 - dayOfWeek
  const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek
  const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate() + mondayOffset)
  const sunday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6)

  return {
    startDate: toLocalDateStr(monday),
    endDate: toLocalDateStr(sunday),
    daysRemaining,
  }
}
