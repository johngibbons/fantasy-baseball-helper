'use client'

interface Props {
  selectedLeague: string
  selectedTeam: string
  credentialsOk: boolean | null
}

export default function StealthTab(_: Props) {
  return <div className="text-gray-400 text-sm p-4">Stealth Breakouts view — coming up next.</div>
}
