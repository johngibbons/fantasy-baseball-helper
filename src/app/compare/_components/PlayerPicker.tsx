'use client'
import { useState, useEffect } from 'react'

export interface PlayerResult {
  id: number
  fullName: string
  primaryPosition?: { name?: string; abbreviation?: string }
}

export default function PlayerPicker({
  onAdd,
}: { onAdd: (p: PlayerResult) => void }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<PlayerResult[]>([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (q.length < 2) { setResults([]); return }
    const t = setTimeout(() => {
      fetch(`/api/players/search?name=${encodeURIComponent(q)}`)
        .then((r) => r.json())
        .then((d) => {
          setResults(d.players || [])
          setOpen(true)
        })
        .catch(() => {})
    }, 250)
    return () => clearTimeout(t)
  }, [q])

  return (
    <div className="relative">
      <input
        type="text"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Add player..."
        className="bg-gray-900 border border-gray-700 rounded px-3 py-2 w-64 text-sm text-white placeholder-gray-500"
      />
      {open && results.length > 0 && (
        <ul className="absolute mt-1 bg-gray-800 border border-gray-700 rounded shadow-lg z-10 w-64 max-h-72 overflow-y-auto">
          {results.slice(0, 12).map((p) => (
            <li
              key={p.id}
              onMouseDown={() => { onAdd(p); setQ(''); setResults([]); setOpen(false) }}
              className="px-3 py-2 hover:bg-gray-700 cursor-pointer text-sm"
            >
              <span className="text-white">{p.fullName}</span>{' '}
              <span className="text-xs text-gray-400">
                {p.primaryPosition?.abbreviation ?? p.primaryPosition?.name ?? ''}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
