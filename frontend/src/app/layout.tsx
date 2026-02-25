import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import Link from 'next/link'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Stock Analysis Multi-Agent System',
  description: 'AI-powered stock analysis with multi-agent orchestration',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="min-h-screen bg-background">
          <header className="border-b">
            <div className="container mx-auto px-4 py-4">
              <div className="flex items-center justify-between">
                <Link href="/">
                  <div className="flex items-center gap-2">
                    <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
                      <span className="text-primary-foreground font-bold text-lg">SA</span>
                    </div>
                    <div>
                      <h1 className="text-xl font-bold">Stock Agent</h1>
                      <p className="text-xs text-muted-foreground">Multi-Agent Analysis System</p>
                    </div>
                  </div>
                </Link>
                <nav className="flex gap-4">
                  <Link href="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
                    Analysis
                  </Link>
                  <Link href="/backtest" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
                    Backtest
                  </Link>
                  <Link href="/monitoring" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
                    Monitoring
                  </Link>
                </nav>
              </div>
            </div>
          </header>
          <main className="container mx-auto px-4 py-8">
            {children}
          </main>
          <footer className="border-t mt-12">
            <div className="container mx-auto px-4 py-4 text-center text-sm text-muted-foreground">
              Stock Analysis Multi-Agent System • Powered by LangGraph
            </div>
          </footer>
        </div>
      </body>
    </html>
  )
}
