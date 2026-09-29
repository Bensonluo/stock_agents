// 状态词表 —— 同一状态在监控页 / 历史页等所有页面必须同名。
// 未命中的原始值（后端新增状态）直接回退展示，不静默吞掉。
export const STATUS_ZH: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  degraded: '已降级',
  loading: '加载中',
}

export const statusZh = (status: string | undefined) =>
  STATUS_ZH[(status || 'loading').toLowerCase()] || status || '加载中'
