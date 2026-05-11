'use client'

import InfoTip from '@/components/InfoTip'
import { FORM_COPY } from '@/lib/waiver-symbol-copy'

interface Props {
  // Either an OPS-style delta (positive = hotter) or already-computed level
  delta?: number | null
  level?: 'hot' | 'cool' | 'cold' | 'neutral' | null
  tooltip?: string
}

type Level = 'hot' | 'cool' | 'cold' | 'neutral'

function levelFromDelta(d: number): Level {
  if (d >= 0.080) return 'hot'
  if (d >= 0.020) return 'cool'
  if (d <= -0.080) return 'cold'
  return 'neutral'
}

const styles: Record<Level, string> = {
  hot:     'bg-emerald-500/30 text-emerald-300',
  cool:    'bg-emerald-500/15 text-emerald-200',
  neutral: 'bg-gray-500/20 text-gray-300',
  cold:    'bg-red-500/25 text-red-300',
}

const labels: Record<Level, string> = {
  hot:     '🔥',
  cool:    '↗',
  neutral: '→',
  cold:    '❄',
}

export default function FormBadge({ delta, level, tooltip }: Props) {
  const lvl: Level | null =
    level ?? (delta != null ? levelFromDelta(delta) : null)
  if (!lvl) return null
  return (
    <InfoTip content={tooltip ?? FORM_COPY[lvl]}>
      <span className={`inline-block px-1.5 py-0.5 rounded text-xs ${styles[lvl]}`}>
        {labels[lvl]}
      </span>
    </InfoTip>
  )
}
