/* 报告加载骨架屏 —— 比孤立转圈更快建立「报告结构」的心理预期 */
export function ReportSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="正在加载报告">
      <div className="space-y-3">
        <div className="h-8 w-2/5 rounded-lg bg-slate-200 animate-pulse" />
        <div className="h-4 w-4/5 rounded bg-slate-200 animate-pulse" />
        <div className="h-4 w-3/5 rounded bg-slate-200 animate-pulse" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="h-36 rounded-xl bg-slate-200 animate-pulse" />
        <div className="h-36 rounded-xl bg-slate-200 animate-pulse" />
      </div>
      <div className="h-48 rounded-xl bg-slate-200 animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="h-44 rounded-xl bg-slate-200 animate-pulse" />
        <div className="h-44 rounded-xl bg-slate-200 animate-pulse" />
      </div>
      <div className="h-24 rounded-xl bg-slate-200 animate-pulse" />
    </div>
  )
}
