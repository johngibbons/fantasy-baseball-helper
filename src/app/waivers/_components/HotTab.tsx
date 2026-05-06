'use client'

interface Props {
  selectedLeague: string
  selectedTeam: string
  credentialsOk: boolean | null
}

export default function HotTab(_: Props) {
  return <div className="text-gray-400 text-sm p-4">Hot + Sustainable view — coming up next.</div>
}
