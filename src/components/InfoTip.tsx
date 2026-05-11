'use client'

import { useId, type ReactNode } from 'react'

interface InfoTipProps {
  content: string | ReactNode
  children: ReactNode
  className?: string
}

export default function InfoTip({ content, children, className }: InfoTipProps) {
  const tipId = useId()
  return (
    <span className={`relative inline-block group ${className ?? ''}`}>
      <span aria-describedby={tipId}>{children}</span>
      <span
        id={tipId}
        role="tooltip"
        className={[
          'pointer-events-none absolute left-0 top-full mt-1 z-50',
          'opacity-0 group-hover:opacity-100 transition-opacity duration-100',
          'bg-gray-800/95 border border-white/10 rounded-md shadow-xl',
          'px-3 py-2 text-xs text-gray-200 leading-snug',
          'max-w-xs whitespace-normal',
        ].join(' ')}
      >
        {content}
      </span>
    </span>
  )
}
