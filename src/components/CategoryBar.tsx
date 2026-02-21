// ── Category balance bar component ──

export function CategoryBar({ label, value, isWeakest }: { label: string; value: number; isWeakest: boolean }) {
  // Scale bar: clamp to [-10, 10] for display
  const maxVal = 10
  const clamped = Math.max(-maxVal, Math.min(maxVal, value))
  const pct = Math.abs(clamped) / maxVal * 100

  return (
    <div className={`flex items-center gap-2 py-0.5 ${isWeakest ? 'bg-red-950/30 -mx-2 px-2 rounded' : ''}`}>
      <span className={`w-8 text-[10px] font-bold tabular-nums text-right shrink-0 ${isWeakest ? 'text-red-400' : 'text-gray-400'}`}>
        {label}
      </span>
      <div className="flex-1 h-3 bg-gray-800 rounded-full overflow-hidden relative">
        <div
          className={`h-full rounded-full transition-all ${
            value >= 0 ? 'bg-emerald-500/60' : 'bg-red-500/60'
          } ${isWeakest ? (value >= 0 ? 'bg-emerald-500/40' : 'bg-red-500/80') : ''}`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
      <span className={`w-9 text-[10px] font-bold tabular-nums text-right shrink-0 ${value >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
        {value > 0 ? '+' : ''}{value.toFixed(1)}
      </span>
    </div>
  )
}
