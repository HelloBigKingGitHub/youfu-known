export interface AdminUser {
  id: string
  username: string
  email: string
  role: 'admin' | 'member'
  is_active: boolean
  is_approved: boolean
  created_at: string | null
  last_login_at: string | null
}

export interface LoginResult {
  user: AdminUser
  access_token: string
  refresh_token: string
  expires_at: string
}

export interface DashboardStats {
  kbs: {
    total: number
    shared: number
    private: number
  }
  users: {
    total: number
    approved: number
    pending: number
  }
  documents: {
    total: number
    by_status: Record<string, number>
  }
  chunks: number
  chat_turns_24h: number
  storage_bytes: number
  llm_calls_24h: number
  uploaded_24h: number
}

export interface AdminKB {
  id: string
  name: string
  owner_id: string | null
  owner_username: string | null
  is_shared: boolean
  is_public: boolean
  doc_count: number
  chunk_count: number
  created_at: string | null
}

export interface AuditEntry {
  id: string
  type: 'login' | 'chat' | string
  user_id: string | null
  username: string | null
  kb_id: string | null
  question: string | null
  detail: Record<string, unknown>
  created_at: string | null
}

export interface AdminSettings {
  model_name: string
  embedding_batch_size: number
  chunk_size: number
  chunk_overlap: number
  max_upload_size_mb: number
}

export type SettingsPatch = Partial<AdminSettings>

export interface FeatureFlag {
  user_id: string
  feature: string
  enabled: boolean
  granted_by?: string | null
  granted_at?: string | null
  created_at: string
}

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

interface Envelope<T> {
  code: number
  data?: T
  message?: string
  detail?: unknown
}

export class ApiError extends Error {
  readonly code: number
  readonly detail: unknown
  readonly status: number

  constructor(code: number, message: string, status: number, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.detail = detail
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return '请求失败'
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      credentials: 'include',
      headers,
    })
  } catch (error: unknown) {
    throw new ApiError(-1, `无法连接到后端: ${errorMessage(error)}`, 0)
  }

  let body: Envelope<T>
  try {
    body = (await response.json()) as Envelope<T>
  } catch (error: unknown) {
    throw new ApiError(
      response.status,
      `后端返回非 JSON (HTTP ${response.status})`,
      response.status,
      error,
    )
  }

  if (!response.ok || body.code !== 0 || body.data === undefined) {
    throw new ApiError(
      body.code || response.status,
      body.message || `请求失败 (HTTP ${response.status})`,
      response.status,
      body.detail,
    )
  }
  return body.data
}

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return errorMessage(error)
}

export const api = {
  login: (username: string, password: string) =>
    request<LoginResult>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () =>
    request<{ logged_out: boolean }>('/api/auth/logout', { method: 'POST' }),
  me: () => request<AdminUser>('/api/auth/me'),
  dashboard: () => request<DashboardStats>('/api/admin/dashboard'),
  listKBs: () => request<AdminKB[]>('/api/admin/kbs'),
  deleteKB: (kbId: string) =>
    request<{ deleted: string }>(`/api/admin/kbs/${encodeURIComponent(kbId)}`, {
      method: 'DELETE',
    }),
  audit: (limit = 100) =>
    request<AuditEntry[]>(`/api/admin/audit?limit=${encodeURIComponent(limit)}`),
  settings: () => request<AdminSettings>('/api/admin/settings'),
  updateSettings: (patch: SettingsPatch) =>
    request<AdminSettings>('/api/admin/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  listUsers: (params?: {
    q?: string
    role?: 'admin' | 'member' | ''
    is_approved?: boolean
    is_active?: boolean
    limit?: number
    offset?: number
  }) => {
    const search = new URLSearchParams()
    if (params?.q) search.set('q', params.q)
    if (params?.role) search.set('role', params.role)
    if (typeof params?.is_approved === 'boolean') {
      search.set('is_approved', params.is_approved ? 'true' : 'false')
    }
    if (typeof params?.is_active === 'boolean') {
      search.set('is_active', params.is_active ? 'true' : 'false')
    }
    if (typeof params?.limit === 'number') {
      search.set('limit', String(params.limit))
    }
    if (typeof params?.offset === 'number') {
      search.set('offset', String(params.offset))
    }
    const qs = search.toString()
    return request<{
      total: number
      items: AdminUser[]
      limit: number
      offset: number
    }>(`/api/admin/users${qs ? `?${qs}` : ''}`)
  },
  getUserStats: (userId: string) =>
    request<{
      user_id: string
      kb_count: number
      doc_count: number
      chat_count: number
    }>(`/api/admin/users/${encodeURIComponent(userId)}/stats`),
  updateUser: (
    userId: string,
    body: {
      is_approved?: boolean
      role?: 'admin' | 'member'
      is_active?: boolean
      email?: string
      quota_tokens_total?: number
      quota_period?: QuotaPeriod
    },
  ) =>
    request<AdminUser>(
      `/api/admin/users/${encodeURIComponent(userId)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    ),
  getUserQuota: (userId: string) =>
    request<QuotaInfo>(
      `/api/admin/users/${encodeURIComponent(userId)}/quota`,
    ),
  resetUserQuota: (userId: string) =>
    request<{ reset: true }>(
      `/api/admin/users/${encodeURIComponent(userId)}/quota/reset`,
      { method: 'POST' },
    ),
  deleteUser: (userId: string) =>
    request<{ deleted: string; existed: boolean }>(
      `/api/admin/users/${encodeURIComponent(userId)}`,
      { method: 'DELETE' },
    ),
  listUserFeatures: (userId: string) =>
    request<FeatureFlag[]>(
      `/api/admin/users/${encodeURIComponent(userId)}/features`,
    ),
  updateUserFeature: (userId: string, feature: string, enabled: boolean) =>
    request<FeatureFlag>(
      `/api/admin/users/${encodeURIComponent(userId)}/features/${encodeURIComponent(feature)}`,
      { method: 'PUT', body: JSON.stringify({ enabled }) },
    ),
}

export { request }
