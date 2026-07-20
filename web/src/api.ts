// API 封装 - 统一 envelope 解包 + 错误处理
// 后端响应: 成功 { code: 0, data: T }, 失败 { code: number, message: string, detail?: any }

import type {
  KB,
  KBDetail,
  Document,
  DocumentStatusInfo,
  UploadResult,
  ChatResponse,
  HealthInfo,
  User,
  LoginResponse,
} from './types'

export const USER_STORAGE_KEY = 'youfu-known:user'

export class ApiError extends Error {
  public readonly code: number
  public readonly detail: unknown

  constructor(code: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.detail = detail
  }
}

interface Envelope<T> {
  code: number
  data?: T
  message?: string
  detail?: unknown
}

async function request<T>(url: string, opts: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, {
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(opts.headers || {}),
      },
      ...opts,
    })
  } catch (e) {
    // 网络层失败 (CORS / 连不上 / 跨域等)
    const msg = e instanceof Error ? e.message : '网络错误'
    throw new ApiError(-1, `无法连接到后端: ${msg}`)
  }

  // 401 统一处理: 清用户状态并跳登录 (login/me 校验接口由上层处理)
  if (res.status === 401 && !url.includes('/auth/login') && !url.includes('/auth/me')) {
    localStorage.removeItem(USER_STORAGE_KEY)
    window.location.href = '/login'
    throw new Error('not authenticated')
  }

  // 尝试解析 JSON, 容错非 JSON 错误
  let body: Envelope<T>
  try {
    body = (await res.json()) as Envelope<T>
  } catch {
    throw new ApiError(
      res.status,
      `后端返回非 JSON (HTTP ${res.status})`,
    )
  }

  if (body.code !== 0 || body.data === undefined) {
    throw new ApiError(
      body.code ?? res.status,
      body.message ?? `请求失败 (HTTP ${res.status})`,
      body.detail,
    )
  }
  return body.data
}

export const api = {
  // 健康 (公开)
  health: () => request<HealthInfo>('/api/health'),

  // 认证
  login: (username: string, password: string) =>
    request<LoginResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  me: () => request<User>('/api/auth/me'),

  changePassword: (oldPassword: string, newPassword: string) =>
    request<void>('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
      }),
    }),

  // KB
  listKBs: () => request<KB[]>('/api/kbs'),
  createKB: (name: string, description?: string) =>
    request<KB>('/api/kbs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        description: description ?? '',
      }),
    }),
  getKB: (kbId: string) => request<KBDetail>(`/api/kbs/${kbId}`),
  updateKB: (kbId: string, name?: string, description?: string) =>
    request<KB>(`/api/kbs/${kbId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...(name !== undefined ? { name } : {}),
        ...(description !== undefined ? { description } : {}),
      }),
    }),
  deleteKB: (kbId: string) =>
    request<{ deleted: string }>(`/api/kbs/${kbId}`, {
      method: 'DELETE',
    }),

  // 文档
  listDocuments: (kbId: string) =>
    request<Document[]>(`/api/kbs/${kbId}/documents`),
  getDocument: (kbId: string, docId: string) =>
    request<Document>(`/api/kbs/${kbId}/documents/${docId}`),
  getDocumentStatus: (kbId: string, docId: string) =>
    request<DocumentStatusInfo>(
      `/api/kbs/${kbId}/documents/${docId}/status`,
    ),
  uploadDocuments: async (
    kbId: string,
    files: File[],
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<UploadResult> => {
    const form = new FormData()
    for (const f of files) form.append('files', f)

    // 使用 XMLHttpRequest 以获取上传进度 (fetch 暂不支持)
    return new Promise<UploadResult>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `/api/kbs/${kbId}/documents`)
      xhr.withCredentials = true
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && onProgress) {
          onProgress(ev.loaded, ev.total)
        }
      }
      xhr.onerror = () =>
        reject(new ApiError(-1, '上传失败: 网络错误'))
      xhr.onload = () => {
        let body: Envelope<UploadResult>
        try {
          body = JSON.parse(xhr.responseText) as Envelope<UploadResult>
        } catch {
          reject(
            new ApiError(
              xhr.status,
              `上传失败: 非 JSON 响应 (HTTP ${xhr.status})`,
            ),
          )
          return
        }
        if (body.code !== 0 || body.data === undefined) {
          reject(
            new ApiError(
              body.code ?? xhr.status,
              body.message ?? `上传失败 (HTTP ${xhr.status})`,
              body.detail,
            ),
          )
          return
        }
        resolve(body.data)
      }
      xhr.send(form)
    })
  },
  deleteDocument: (kbId: string, docId: string) =>
    request<{ deleted: string }>(
      `/api/kbs/${kbId}/documents/${docId}`,
      { method: 'DELETE' },
    ),

  // 问答
  chat: (kbId: string, question: string, topK = 6) =>
    request<ChatResponse>(`/api/kbs/${kbId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        top_k: topK,
        stream: false,
      }),
    }),
}