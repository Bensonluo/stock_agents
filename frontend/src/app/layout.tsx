import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import Link from 'next/link'
import { LineChart, FlaskConical, Radar } from 'lucide-react'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Stock Agent · 智能股票研究平台',
  description:
    '证据约束的多 Agent 股票研究:多空质询、证据审计、风险委员会与成本化回测,每个数字可溯源。',
}

const NAV_ITEMS = [
  { href: '/', label: '研究分析', icon: LineChart },
  { href: '/backtest', label: '策略回测', icon: FlaskConical },
  { href: '/monitoring', label: '运行监控', icon: Radar },
]

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body className={inter.className}>
        <div className="min-h-screen bg-background flex flex-col">
          <header className="sticky top-0 z-50 border-b border-slate-200/70 bg-white/80 backdrop-blur-md">
            <div className="container mx-auto px-4 py-3">
              <div className="flex items-center justify-between">
                <Link href="/" className="flex items-center gap-2.5 group">
                  <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-600/20 group-hover:shadow-blue-600/30 transition-shadow">
                    <LineChart className="h-5 w-5 text-white" />
                  </div>
                  <div>
                    <h1 className="text-lg font-bold tracking-tight">Stock Agent</h1>
                    <p className="text-[11px] text-muted-foreground -mt-0.5">证据约束的多 Agent 研究</p>
                  </div>
                </Link>
                <nav className="flex items-center gap-1">
                  {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
                    <Link
                      key={href}
                      href={href}
                      className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-slate-100 px-3 py-1.5 rounded-lg transition-colors"
                    >
                      <Icon className="h-4 w-4" />
                      <span className="hidden sm:inline">{label}</span>
                    </Link>
                  ))}
                </nav>
              </div>
            </div>
          </header>
          <main className="flex-1">
            {children}
          </main>
          <footer className="border-t border-slate-200/70 mt-12">
            <div className="container mx-auto px-4 py-5 text-center text-xs text-muted-foreground">
              Stock Agent · 多 Agent 股票研究系统 · 报告仅供研究参考,不构成投资建议
            </div>
          </footer>
        </div>
      </body>
    </html>
  )
}
