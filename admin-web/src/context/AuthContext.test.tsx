import { render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    me: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  },
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : String(err)),
}))

type AuthSnapshot = ReturnType<typeof useAuth>

function Capture({ onReady }: { onReady: (value: AuthSnapshot) => void }) {
  const auth = useAuth()
  onReady(auth)
  return null
}

describe('AuthProvider', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('starts loading and resolves to the current user on mount', async () => {
    const fakeUser = {
      id: 'u1',
      username: 'admin',
      email: 'a@example.com',
      role: 'admin' as const,
      is_active: true,
      is_approved: true,
      created_at: null,
      last_login_at: null,
    }
    vi.mocked(api.me).mockResolvedValue(fakeUser)

    let snapshot: AuthSnapshot | null = null
    render(
      <AuthProvider>
        <Capture onReady={(s) => (snapshot = s)} />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(snapshot).not.toBeNull()
      expect(snapshot?.loading).toBe(false)
    })
    expect(snapshot?.user).toEqual(fakeUser)
    expect(snapshot?.error).toBeNull()
    expect(api.me).toHaveBeenCalledTimes(1)
  })

  it('clears user when /me fails', async () => {
    vi.mocked(api.me).mockRejectedValue(new Error('not authenticated'))

    let snapshot: AuthSnapshot | null = null
    render(
      <AuthProvider>
        <Capture onReady={(s) => (snapshot = s)} />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(snapshot?.loading).toBe(false)
    })
    expect(snapshot?.user).toBeNull()
    expect(snapshot?.error).toBe('not authenticated')
  })
})
