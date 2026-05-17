'use client'

import type { ReactNode } from 'react'

export type SortDir = 'asc' | 'desc'

export function compareValues(
  a: number | string | null | undefined,
  b: number | string | null | undefined,
  dir: SortDir,
): number {
  if (a == null && b == null) return 0
  if (a == null) return 1
  if (b == null) return -1
  if (typeof a === 'number' && typeof b === 'number') {
    return dir === 'desc' ? b - a : a - b
  }
  const sa = String(a).toLowerCase()
  const sb = String(b).toLowerCase()
  return dir === 'desc' ? sb.localeCompare(sa) : sa.localeCompare(sb)
}

interface SortableThProps {
  col: string
  label: ReactNode
  sortCol: string | null
  sortDir: SortDir
  onSort: (col: string) => void
  align?: 'left' | 'right'
  className?: string
}

export function SortableTh({
  col,
  label,
  sortCol,
  sortDir,
  onSort,
  align = 'left',
  className = '',
}: SortableThProps) {
  const active = sortCol === col
  const arrow = active ? (sortDir === 'desc' ? '↓' : '↑') : ''
  return (
    <th
      onClick={() => onSort(col)}
      className={`cursor-pointer select-none hover:text-white ${
        align === 'right' ? 'text-right' : 'text-left'
      } ${className}`}
    >
      <span className={active ? 'text-white' : ''}>{label}</span>
      {arrow && <span className="ml-1 text-gray-400">{arrow}</span>}
    </th>
  )
}
