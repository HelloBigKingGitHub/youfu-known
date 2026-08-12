import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, formatApiError } from './api'

function mockResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ code: 0, data }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockError(message: string, code = 1, status = 400): Response {
  return new Response(JSON.stringify({ code, message }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('admin api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse({})))
  })

  it('uses credentials for dashboard requests', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse({ kbs: { total: 3 } }),
    )

    await api.dashboard()

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/dashboard',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('serializes login credentials as JSON', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse({ user: { id: 'u1' }, access_token: 't' }),
    )

    await api.login('alice', 'secret')

    expect(fetch).toHaveBeenCalledWith(
      '/api/auth/login',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({ username: 'alice', password: 'secret' }),
        headers: expect.any(Headers),
      }),
    )
  })

  it('posts to /api/auth/logout with credentials', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse({ logged_out: true }),
    )

    await api.logout()

    expect(fetch).toHaveBeenCalledWith(
      '/api/auth/logout',
      expect.objectContaining({ credentials: 'include', method: 'POST' }),
    )
  })

  it('hits /api/auth/me for the current user', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse({ id: 'u1', username: 'admin', role: 'admin' }),
    )

    await api.me()

    expect(fetch).toHaveBeenCalledWith(
      '/api/auth/me',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('lists KBs via GET', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))

    await api.listKBs()

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/kbs',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('sends the KB id and DELETE method for admin deletion', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse({ deleted: 'kb-123' }))

    await api.deleteKB('kb-123')

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/kbs/kb-123',
      expect.objectContaining({
        credentials: 'include',
        method: 'DELETE',
      }),
    )
  })

  it('percent-encodes KB ids with special characters on delete', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse({ deleted: 'kb/1' }))

    await api.deleteKB('kb/1')

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/kbs/kb%2F1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('fetches audit entries with limit param', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))

    await api.audit(50)

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/audit?limit=50',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('uses default audit limit of 100', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))

    await api.audit()

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/audit?limit=100',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('fetches settings via GET', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse({ model_name: 'm', embedding_batch_size: 10 }),
    )

    await api.settings()

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/settings',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('serializes settings patches as JSON', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse({ model_name: 'm' }))

    await api.updateSettings({ model_name: 'MiniMax-Test' })

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/settings',
      expect.objectContaining({
        credentials: 'include',
        method: 'PATCH',
        body: JSON.stringify({ model_name: 'MiniMax-Test' }),
      }),
    )
  })

  it('throws ApiError with status and message on backend error', async () => {
    vi.mocked(fetch).mockImplementation(() =>
      Promise.resolve(mockError('bad', 1, 400)),
    )

    await expect(api.dashboard()).rejects.toBeInstanceOf(ApiError)
    await expect(api.dashboard().catch((e: unknown) => e)).resolves.toMatchObject({
      status: 400,
      message: 'bad',
    })
  })

  it('wraps network failures as ApiError with status 0', async () => {
    vi.mocked(fetch).mockImplementation(() =>
      Promise.reject(new TypeError('network down')),
    )

    await expect(api.dashboard()).rejects.toBeInstanceOf(ApiError)
    await expect(
      api.dashboard().catch((e: unknown) => e),
    ).resolves.toMatchObject({ status: 0 })
  })

  it('throws when backend returns non-JSON', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response('not json', { status: 500 }),
    )

    await expect(api.dashboard()).rejects.toMatchObject({
      status: 500,
    })
  })

  it('formats ApiError messages via formatApiError', () => {
    const err = new ApiError(400, 'bad request', 400)
    expect(formatApiError(err)).toBe('bad request')
  })

  it('formats generic Error messages via formatApiError', () => {
    expect(formatApiError(new Error('boom'))).toBe('boom')
  })

  it('formats unknown values via formatApiError', () => {
    expect(formatApiError('weird')).toBe('请求失败')
  })

  it('fetches a user quota via GET', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse({
        tokens_total: 100000,
        tokens_used: 20000,
        tokens_remaining: 80000,
        period: 'monthly',
        reset_at: '2026-03-01T00:00:00',
        usage_breakdown: [],
      }),
    )

    await api.getUserQuota('u2')

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/users/u2/quota',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('resets a user quota via POST', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse({ reset: true }))

    await api.resetUserQuota('u2')

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/users/u2/quota/reset',
      expect.objectContaining({ credentials: 'include', method: 'POST' }),
    )
  })

  it('accepts quota_tokens_total / quota_period on updateUser', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse({ id: 'u2' }))

    await api.updateUser('u2', {
      quota_tokens_total: 50000,
      quota_period: 'weekly',
    })

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/users/u2',
      expect.objectContaining({
        credentials: 'include',
        method: 'PATCH',
        body: JSON.stringify({
          quota_tokens_total: 50000,
          quota_period: 'weekly',
        }),
      }),
    )
  })
})

