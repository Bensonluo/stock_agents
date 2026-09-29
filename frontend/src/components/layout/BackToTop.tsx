'use client'

import { useEffect, useState } from 'react'
import { ArrowUp } from 'lucide-react'

/* 返回顶部悬浮按钮 —— 长报告页滚动 600px 后出现 */
export function BackToTop() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 600)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  if (!visible) return null

  return (
    <button
      type="button"
      aria-label="返回顶部"
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      className="no-print fixed bottom-6 right-6 z-40 h-10 w-10 rounded-full bg-slate-900 text-white shadow-lg shadow-slate-900/20 hover:bg-slate-700 flex items-center justify-center transition-colors"
    >
      <ArrowUp className="h-5 w-5" />
    </button>
  )
}
