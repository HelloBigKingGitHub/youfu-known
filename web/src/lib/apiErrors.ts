// 后端错误友好化: 将 ApiError.detail (Pydantic 422 错误 JSON 字符串) 转中文
// 也兼容 HTTPException(detail=str) 与网络错误。供表单字段与 toast 共用。
import type { ApiError } from '../api'

export interface FieldError {
  field: string
  message: string
}

const FIELD_LABELS: Record<string, string> = {
  username: '用户名',
  email: '邮箱',
  password: '密码',
  old_password: '当前密码',
  new_password: '新密码',
  confirm_password: '确认密码',
  name: '名称',
  description: '描述',
  files: '文件',
  question: '问题',
  code: '验证码',
  role: '角色',
  is_active: '状态',
  is_approved: '审批',
  is_shared: '共享',
  is_public: '公开',
  kbId: '知识库',
  id: '编号',
  email_pattern: '邮箱',
}

function labelOf(field: string): string {
  return FIELD_LABELS[field] ?? field
}

interface PydanticErr {
  type?: string
  loc?: unknown[]
  msg?: string
  ctx?: Record<string, unknown>
}

function asErrArray(detail: unknown): PydanticErr[] | null {
  if (Array.isArray(detail)) return detail as PydanticErr[]
  if (typeof detail === 'string') {
    // 1) 真 JSON 字符串
    try {
      const parsed = JSON.parse(detail)
      if (Array.isArray(parsed)) return parsed as PydanticErr[]
    } catch {
      /* fall through */
    }
    // 2) Python repr (Pydantic ``str(exc.errors())`` 输出)
    try {
      const pyJson = pythonReprToJson(detail)
      const parsed = JSON.parse(pyJson)
      if (Array.isArray(parsed)) return parsed as PydanticErr[]
    } catch {
      return null
    }
  }
  return null
}

// FastAPI/Pydantic 把 ``exc.errors()`` 序列化成 Python repr 字符串:
//   ``[{'type': 'x', 'loc': ('body', 'foo'), ...}]``
// 这里只对这种受限格式做最小转换 (不通用 Python 解析器, 仅服务错误 detail)。
function pythonReprToJson(s: string): string {
  if (!s.trimStart().startsWith('[') && !s.trimStart().startsWith('{')) {
    throw new Error('not a python repr')
  }
  return s
    .replace(/\(/g, '[')
    .replace(/\)/g, ']')
    .replace(/'/g, '"')
    .replace(/\bTrue\b/g, 'true')
    .replace(/\bFalse\b/g, 'false')
    .replace(/\bNone\b/g, 'null')
}

function lastSegment(loc: unknown[] | undefined): string {
  if (!Array.isArray(loc) || loc.length === 0) return ''
  // FastAPI 包装: ['body','username'] 或 ['body',0,'name'] -> 跳过 'body'
  const segs = loc.filter((s) => s !== 'body' && s !== 'query' && s !== 'path')
  if (segs.length === 0) return ''
  return String(segs[segs.length - 1])
}

function translateOne(err: PydanticErr): FieldError | null {
  const field = lastSegment(err.loc)
  const label = field ? labelOf(field) : ''
  const t = err.type ?? ''
  const ctx = (err.ctx ?? {}) as Record<string, unknown>
  const minLen = ctx.min_length
  const maxLen = ctx.max_length
  const fallbackField: FieldError = {
    field: field || '_',
    message: err.msg ? (label ? `${label}: ${err.msg}` : err.msg) : '请求不合法',
  }
  switch (t) {
    case 'string_too_short':
      return { field, message: `${label}至少 ${minLen} 个字符` }
    case 'string_too_long':
      return { field, message: `${label}最多 ${maxLen} 个字符` }
    case 'string_pattern_mismatch':
      return { field, message: `${label}格式不正确` }
    case 'missing':
      return { field, message: `请填写${label}` }
    case 'extra_forbidden':
      return { field, message: `${label}不允许` }
    case 'json_invalid':
      return { field: field || '_', message: '请求数据不是合法 JSON' }
    case 'int_parsing':
    case 'int_type':
      return { field, message: `${label}必须为整数` }
    case 'enum':
      return { field, message: `${label}取值不合法` }
    default:
      return fallbackField
  }
}

function isApiError(e: unknown): e is ApiError {
  return e instanceof Error && e.name === 'ApiError' && 'code' in e && 'detail' in e
}

export function extractFieldErrors(e: unknown): FieldError[] {
  if (!isApiError(e)) return []
  const arr = asErrArray(e.detail)
  if (!arr) return []
  const out: FieldError[] = []
  for (const item of arr) {
    const fe = translateOne(item)
    if (fe) out.push(fe)
  }
  return out
}

export function formatApiError(e: unknown, fallback = '操作失败, 请稍后重试'): string {
  if (isApiError(e)) {
    if (e.code === -1) return '无法连接到后端, 请检查网络'
    const fields = extractFieldErrors(e)
    if (fields.length > 0) {
      return fields.map((f) => f.message).join('；')
    }
    return e.message || fallback
  }
  return fallback
}

export function isLoginCredentialError(e: unknown): boolean {
  return isApiError(e) && (e.code === 401 || e.code === 403)
}
