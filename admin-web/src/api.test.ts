import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

function mockResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ code: 0, data }), {
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

  it('sends the KB id and DELETE method for admin deletion', async () => {
    await api.deleteKB('kb-123')

    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/kbs/kb-123',
      expect.objectContaining({
        credentials: 'include',
        method: 'DELETE',
      }),
    )
  })

  it('serializes settings patches as JSON', async () => {
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
})

function _keepTypeScriptAwareOfResponse(response: Response): Response {
  return response
}

void _keepTypeScriptAwareOfResponse
