// API 封装 - 用户额度 (Phase 2.1)
//
// 后端 spec:
//   GET  /api/users/me/quota           (普通用户调, auth required)
//     → QuotaInfo
//   GET  /api/admin/users/{id}/quota   (admin only, admin-web 用)
//     → QuotaInfo
//   PATCH /api/admin/users/{id}        (扩展 body 加 quota_tokens_total / quota_period)
//   POST /api/admin/users/{id}/quota/reset
//
// 主仓 web 只用 getMyQuota; admin 端调用见 admin-web/src/api.ts.

export type QuotaPeriod = 'monthly' | 'weekly' | 'daily' | 'none'

export interface QuotaUsageDay {
  /** YYYY-MM-DD */
  date: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  calls: number
}

export interface QuotaInfo {
  tokens_total: number
  tokens_used: number
  /** null = 无上限 (tokens_total === 0 时) */
  tokens_remaining: number | null
  period: QuotaPeriod
  /** ISO datetime 或 null (period=none 或无重置时间) */
  reset_at: string | null
  usage_breakdown: QuotaUsageDay[]
}
