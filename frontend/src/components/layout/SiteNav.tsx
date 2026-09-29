'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LineChart, FlaskConical, Radar, History } from 'lucide-react'

const NAV_ITEMS = [
  { href: '/', label: '研究分析', icon: LineChart, exact: true },
  { href: '/backtest', label: '策略回测', icon: FlaskConical, exact: false },
  { href: '/history', label: '历史记录', icon: History, exact: false },
  { href: '/monitoring', label: '运行监控', icon: Radar, exact: false },
]

export function SiteNav() {
  const pathname = usePathname()

  return (
    <nav className="flex items-center gap-1" aria-label="主导航">
      {NAV_ITEMS.map(({ href, label, icon: Icon, exact }) => {
        const active = exact ? pathname === href : pathname.startsWith(href)
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-colors ${
              active
                ? 'bg-blue-50 text-blue-700 font-medium'
                : 'text-muted-foreground hover:text-foreground hover:bg-slate-100'
            }`}
          >
            <Icon className="h-4 w-4" />
            <span className="hidden sm:inline">{label}</span>
          </Link>
        )
      })}
    </nav>
  )
}
