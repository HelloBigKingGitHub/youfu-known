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
//   ``[{'type': 'x', 'loc': ('body', 'foo'), 'msg': 'Pattern \w...'}]``
// 也可能用双引号包字符串 (当字符串里含单引号时): ``"msg": "foo's bar"``。
// 这里做一个最小的 Python 字符串字面量识别器, 把 ``'..'`` 或 ``".."`` 转成 JSON
// 字符串字面量, 保留结构性 ``[``/``{``/``]``/``}``、``:``、``,``、裸字面量。
// 反斜杠在 Python repr 里按字面写入 (例如 ``\w`` 是两个字面字符), JSON 同,
// 原文搬运即可; 真控制字符 (LF/CR/Tab) 由末尾分支再 escape。
// 反斜杠收尾 (输入末尾是 ``\``) 不做特殊处理, 直接拼到 body — 永远会被
// 上层 ``JSON.parse`` 拒绝, 触发 ``asErrArray`` 的回退分支。
function pythonReprToJson(s: string): string {
  const src = s
    .replace(/\(/g, '[')
    .replace(/\)/g, ']')
    .replace(/\bTrue\b/g, 'true')
    .replace(/\bFalse\b/g, 'false')
    .replace(/\bNone\b/g, 'null')

  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    if (c === "'" || c === '"') {
      const quote = c
      let j = i + 1
      let body = ''
      while (j < n && src[j] !== quote) {
        const ch = src[j]
        // Python repr 里 ``\X`` 总是字面两个字符 (反斜杠本身用 ``\\``), JSON 同;
        // 但真控制字符 (换行/CR/tab) 必须 escape, 所以单字符 ``\n`` 等也要转。
        if (ch === '\\' && j + 1 < n) {
          body += '\\' + src[j + 1]
          j += 2
          continue
        }
        if (ch === '"' && quote === "'") {
          body += '\\"'
          j++
          continue
        }
        if (ch === '\n') { body += '\\n'; j++; continue }
        if (ch === '\r') { body += '\\r'; j++; continue }
        if (ch === '\t') { body += '\\t'; j++; continue }
        body += ch
        j++
      }
      out += '"' + body + '"'
      i = j + 1
      continue
    }
    out += c
    i++
  }
  return out
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
    case 'value_error':
      // Pydantic 自定义校验 (例如 ``@validator`` 抛 ``ValueError``),
      // msg 通常是开发者写的中/英文诊断, 透传给用户比丢成 "请求不合法" 更有用。
      return { field, message: label ? `${label}: ${err.msg ?? ''}` : err.msg ?? '请求不合法' }
    default:
      // 真正的未知类型: 不暴露后端英文 msg, 一律给出统一中文兜底。
      return { field: field || '_', message: '请求不合法' }
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
