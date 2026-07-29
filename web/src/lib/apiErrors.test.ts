// 行为 spec: 后端 ApiError.detail 是 Pydantic 422 错误的 JSON 字符串
// 或 HTTPException(detail=str) 的字符串。helper 要把这两类都转成中文。
import { describe, expect, test } from 'vitest'
import {
  extractFieldErrors,
  formatApiError,
  isLoginCredentialError,
} from './apiErrors'

class ApiError extends Error {
  code: number
  detail: unknown
  constructor(code: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.detail = detail
  }
}

const pydanticDetailString = JSON.stringify([
  {
    type: 'string_too_short',
    loc: ['body', 'username'],
    msg: 'String should have at least 3 characters',
    ctx: { min_length: 3 },
  },
  {
    type: 'string_too_short',
    loc: ['body', 'password'],
    msg: 'String should have at least 8 characters',
    ctx: { min_length: 8 },
  },
])

test('extractFieldErrors parses Pydantic array, label-maps, joins Chinese', () => {
  const e = new ApiError(400, 'validation error', pydanticDetailString)
  const fields = extractFieldErrors(e)
  expect(fields).toEqual([
    { field: 'username', message: '用户名至少 3 个字符' },
    { field: 'password', message: '密码至少 8 个字符' },
  ])
})

test('extractFieldErrors handles regex pattern mismatch and missing', () => {
  const detail = JSON.stringify([
    { type: 'string_pattern_mismatch', loc: ['body', 'username'], msg: 'X' },
    { type: 'string_too_long', loc: ['body', 'username'], msg: 'X', ctx: { max_length: 32 } },
    { type: 'missing', loc: ['body', 'password'], msg: 'X' },
    { type: 'value_error', loc: ['body', 'question'], msg: 'Question too short' },
    { type: 'json_invalid', loc: ['body'], msg: 'X' },
  ])
  const fields = extractFieldErrors(new ApiError(400, 'validation error', detail))
  expect(fields[0].message).toBe('用户名格式不正确')
  expect(fields[1].message).toBe('用户名最多 32 个字符')
  expect(fields[2].message).toBe('请填写密码')
  expect(fields[3].message).toBe('问题: Question too short')
  expect(fields[4].message).toBe('请求数据不是合法 JSON')
})

test('extractFieldErrors returns [] when detail is missing or unrecognized', () => {
  expect(extractFieldErrors(new ApiError(400, 'validation error'))).toEqual([])
  expect(
    extractFieldErrors(new ApiError(400, 'x', 'not json')),
  ).toEqual([])
  expect(extractFieldErrors(new Error('boom'))).toEqual([])
  expect(extractFieldErrors('string error')).toEqual([])
})

test('extractFieldErrors parses Python repr detail (real FastAPI envelope)', () => {
  // 真实后端 envelope: detail = str(exc.errors()) = Python repr
  const detail = "[{'type': 'string_too_short', 'loc': ('body', 'username'), 'msg': 'String should have at least 3 characters', 'input': 'ab', 'ctx': {'min_length': 3}}, {'type': 'string_too_short', 'loc': ('body', 'new_password'), 'msg': 'String should have at least 8 characters', 'input': 'abc', 'ctx': {'min_length': 8}}]"
  const fields = extractFieldErrors(new ApiError(400, 'validation error', detail))
  expect(fields).toEqual([
    { field: 'username', message: '用户名至少 3 个字符' },
    { field: 'new_password', message: '新密码至少 8 个字符' },
  ])
})

test('extractFieldErrors handles regex pattern in Python repr (real email case)', () => {
  // 真实后端捕获: /api/auth/register 400, email="notanemail"
  // Python repr 字符串里含未转义的反斜杠, 转换后必须是合法 JSON。
  const detail = "[{'type': 'string_pattern_mismatch', 'loc': ('body', 'email'), 'msg': \"String should match pattern '^$|^[\\\\w.+-]+@[\\\\w-]+\\\\.[\\\\w.-]+'\", 'input': 'notanemail', 'ctx': {'pattern': \"^$|^[\\\\w.+-]+@[\\\\w-]+\\\\.[\\\\w.-]+$\"}}]"
  const fields = extractFieldErrors(new ApiError(400, 'validation error', detail))
  expect(fields).toEqual([
    { field: 'email', message: '邮箱格式不正确' },
  ])
})

test('extractFieldErrors combines Pydantic array detail (multi-field case)', () => {
  // /register 真实多字段: 短密码 + 非法邮箱
  const detail = JSON.stringify([
    { type: 'string_too_short', loc: ['body', 'password'], msg: 'X', ctx: { min_length: 8 } },
    { type: 'string_pattern_mismatch', loc: ['body', 'email'], msg: 'X' },
  ])
  const fields = extractFieldErrors(new ApiError(400, 'validation error', detail))
  expect(fields).toEqual([
    { field: 'password', message: '密码至少 8 个字符' },
    { field: 'email', message: '邮箱格式不正确' },
  ])
})

test('extractFieldErrors handles Python repr with escaped backslash and unclosed string', () => {
  // 字面反斜杠: Python ``\\`` 在 repr 里是两个 ``\`` 字符
  const detail1 = "[{'type': 'string_too_short', 'loc': ('body', 'name'), 'msg': 'Path C:\\\\Users', 'ctx': {'min_length': 1}}]"
  expect(extractFieldErrors(new ApiError(400, 'x', detail1))).toEqual([
    { field: 'name', message: '名称至少 1 个字符' },
  ])
  // 未闭合字符串: JSON.parse 失败, 应退化为空数组而不是抛错
  expect(extractFieldErrors(new ApiError(400, 'x', "[{'type': 'x', 'msg': 'unclosed"))).toEqual([])
})

test('extractFieldErrors uses generic Chinese fallback for unknown Pydantic type', () => {
  // 真正未知的 Pydantic type 不应该把后端英文 msg 暴露给用户
  const unknown = JSON.stringify([{ type: 'weird_new_type', loc: ['body', 'foo'], msg: 'EN' }])
  expect(extractFieldErrors(new ApiError(400, 'x', unknown))).toEqual([
    { field: 'foo', message: '请求不合法' },
  ])
})

test('formatApiError returns one-line Chinese per Pydantic field, joined', () => {
  const e = new ApiError(400, 'validation error', pydanticDetailString)
  const msg = formatApiError(e)
  expect(msg).toBe('用户名至少 3 个字符；密码至少 8 个字符')
})

test('formatApiError falls back to e.message for non-Pydantic ApiError', () => {
  expect(formatApiError(new ApiError(400, '自定义中文错误'))).toBe('自定义中文错误')
  expect(formatApiError(new ApiError(500, 'internal error', 'stack here'))).toBe('internal error')
})

test('formatApiError covers network and unknown errors', () => {
  expect(formatApiError(new ApiError(-1, '无法连接到后端: refused'))).toBe('无法连接到后端, 请检查网络')
  expect(formatApiError(new Error('boom'))).toBe('操作失败, 请稍后重试')
  expect(formatApiError('string')).toBe('操作失败, 请稍后重试')
  expect(formatApiError(null)).toBe('操作失败, 请稍后重试')
})

test('isLoginCredentialError covers 401 and 403 auth errors', () => {
  expect(isLoginCredentialError(new ApiError(401, 'Invalid credentials'))).toBe(true)
  expect(isLoginCredentialError(new ApiError(403, 'not approved'))).toBe(true)
  expect(isLoginCredentialError(new ApiError(400, 'validation'))).toBe(false)
  expect(isLoginCredentialError(new Error('x'))).toBe(false)
})