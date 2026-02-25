'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const navItems = [
  { href: '/', label: 'Dashboard' },
  { href: '/rankings', label: 'Rankings' },
  { href: '/draft', label: 'Draft Board' },
  { href: '/keepers', label: 'Keepers' },
  { href: '/inseason', label: 'In-Season' },
  { href: '/players', label: 'Player Search' },
  { href: '/leagues', label: 'Leagues' },
]

export default function Navigation() {
  const pathname = usePathname()

  return (
    <nav className="bg-[#0d1117] border-b border-white/[0.06]">
      <div className="max-w-[90rem] mx-auto px-4 sm:px-6">
        <div className="flex items-center h-11 gap-6">
          <Link href="/" className="text-sm font-bold text-white tracking-tight shrink-0">
            <span className="text-blue-500">&#9670;</span> Fantasy Baseball
          </Link>
          <div className="flex items-center gap-0.5 overflow-x-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
            {navItems.map((item) => {
              const isActive =
                item.href === '/' ? pathname === '/' : pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`px-3 py-1 rounded-md text-xs font-medium transition-colors shrink-0 ${
                    isActive
                      ? 'text-white bg-white/10'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {item.label}
                </Link>
              )
            })}
          </div>
        </div>
      </div>
    </nav>
  )
}
