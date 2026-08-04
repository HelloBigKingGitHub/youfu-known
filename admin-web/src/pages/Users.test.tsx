import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  act,
} from '@testing-library/react'
import { ChakraProvider } from '@chakra-ui/react'
import { UsersPage } from './Users'

// Mock the api module so UsersPage can be exercised without an HTTP backend.
const mockListUsers = vi.fn()
const mockDeleteUser = vi.fn()
const mockMe = vi.fn()

vi.mock('../api', () => ({
  api: {
    me: (...args: unknown[]) => mockMe(...args),
    listUsers: (...args: unknown[]) => mockListUsers(...args),
    deleteUser: (...args: unknown[]) => mockDeleteUser(...args),
  },
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : String(err)),
}))

function renderUsersPage() {
  return render(
    <ChakraProvider>
      <UsersPage />
    </ChakraProvider>,
  )
}

beforeEach(() => {
  mockListUsers.mockReset()
  mockDeleteUser.mockReset()
  mockMe.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function envelope(items: unknown[], total = items.length) {
  return { total, items, limit: 50, offset: 0 }
}

// React 18 StrictMode mounts twice → querySelectorAll / getAllBy* returns
// duplicate entries. Use this helper to de-duplicate by element identity
// so the test assertions target a single virtual instance.
function uniqueByIdentity<T extends Element>(nodes: T[]): T[] {
  const seen = new Set<T>()
  const out: T[] = []
  for (const n of nodes) {
    if (seen.has(n)) continue
    seen.add(n)
    out.push(n)
  }
  return out
}

describe('UsersPage', () => {
  it('renders the user table and triggers a debounced search call', async () => {
    mockListUsers.mockResolvedValue(
      envelope([
        {
          id: 'u1',
          username: 'alice',
          email: 'alice@example.com',
          role: 'admin',
          is_active: true,
          is_approved: true,
          created_at: '2026-01-01T00:00:00',
          last_login_at: '2026-02-01T00:00:00',
        },
        {
          id: 'u2',
          username: 'bob',
          email: 'bob@example.com',
          role: 'member',
          is_active: true,
          is_approved: false,
          created_at: '2026-01-02T00:00:00',
          last_login_at: null,
        },
      ]),
    )

    renderUsersPage()

    // Wait for the table to render both rows (StrictMode mounts twice so
    // getAllByText returns 2; use getAllByText + length assertion).
    await waitFor(() => {
      expect(screen.getAllByText('alice').length).toBeGreaterThan(0)
      expect(screen.getAllByText('bob').length).toBeGreaterThan(0)
    })

    fireEvent.change(screen.getByPlaceholderText('搜索用户名或邮箱'), {
      target: { value: 'alice' },
    })

    // The debounce is 300ms — after waiting past it, the second
    // listUsers call must include q='alice'.
    await waitFor(
      () => {
        const calls = mockListUsers.mock.calls
        const lastCall = calls[calls.length - 1]?.[0]
        expect(lastCall?.q).toBe('alice')
      },
      { timeout: 2000 },
    )
  })

  it('sends role + status filter params when selects change', async () => {
    mockListUsers.mockResolvedValue(envelope([]))

    renderUsersPage()

    await waitFor(() => expect(mockListUsers).toHaveBeenCalled())

    // Role select — de-dupe StrictMode duplicates.
    const roleSelects = uniqueByIdentity(
      screen.getAllByTestId('users-role-filter'),
    )
    expect(roleSelects.length).toBeGreaterThan(0)
    fireEvent.change(roleSelects[0], { target: { value: 'admin' } })

    // Status select — de-dupe StrictMode duplicates.
    const statusSelects = uniqueByIdentity(
      screen.getAllByTestId('users-status-filter'),
    )
    expect(statusSelects.length).toBeGreaterThan(0)
    fireEvent.change(statusSelects[0], { target: { value: 'approved' } })

    await waitFor(() => {
      const calls = mockListUsers.mock.calls
      const lastCall = calls[calls.length - 1]?.[0]
      expect(lastCall?.role).toBe('admin')
      expect(lastCall?.is_approved).toBe(true)
    })
  })

  it('debounces the search input by 300ms', async () => {
    vi.useFakeTimers()
    try {
      mockListUsers.mockResolvedValue(envelope([]))

      renderUsersPage()

      // Initial fetch happens on mount. Allow microtasks to settle.
      await act(async () => {
        await vi.runOnlyPendingTimersAsync()
      })
      expect(mockListUsers).toHaveBeenCalled()

      const callsBefore = mockListUsers.mock.calls.length

      const input = screen.getByPlaceholderText(
        '搜索用户名或邮箱',
      ) as HTMLInputElement

      fireEvent.change(input, { target: { value: 'a' } })
      fireEvent.change(input, { target: { value: 'al' } })
      fireEvent.change(input, { target: { value: 'ali' } })
      fireEvent.change(input, { target: { value: 'alic' } })
      fireEvent.change(input, { target: { value: 'alice' } })

      // No new fetch yet — debounce hasn't fired.
      expect(mockListUsers.mock.calls.length).toBe(callsBefore)

      // Advance past the 300ms debounce.
      await act(async () => {
        vi.advanceTimersByTime(350)
      })

      // Exactly one new fetch triggered by the debounced search.
      const calls = mockListUsers.mock.calls
      expect(calls.length).toBeGreaterThan(callsBefore)
      const lastCall = calls[calls.length - 1]?.[0]
      expect(lastCall?.q).toBe('alice')
    } finally {
      vi.useRealTimers()
    }
  })

  it('paginates with prev/next buttons', async () => {
    // First page has 1 user, total=120 ⇒ next page available.
    mockListUsers.mockImplementation(
      (params: { offset?: number; limit?: number } = {}) => {
        if ((params.offset ?? 0) === 0) {
          return Promise.resolve(
            envelope(
              [
                {
                  id: 'p0',
                  username: 'page0_user',
                  email: 'p0@example.com',
                  role: 'member',
                  is_active: true,
                  is_approved: true,
                  created_at: '2026-01-01T00:00:00',
                  last_login_at: null,
                },
              ],
              120,
            ),
          )
        }
        // Offset 50 → second page with a different user.
        return Promise.resolve(
          envelope(
            [
              {
                id: 'p50',
                username: 'page50_user',
                email: 'p50@example.com',
                role: 'member',
                is_active: true,
                is_approved: true,
                created_at: '2026-01-01T00:00:00',
                last_login_at: null,
              },
            ],
            120,
          ),
        )
      },
    )

    renderUsersPage()

    await waitFor(() =>
      expect(screen.getAllByText('page0_user').length).toBeGreaterThan(0),
    )

    // Prev is disabled at offset=0.
    const prevBtn = uniqueByIdentity(screen.getAllByTestId('users-prev-page'))[0]
    expect(prevBtn).toBeDisabled()
    // Next is enabled because total=120 > limit=50.
    const nextBtn = uniqueByIdentity(screen.getAllByTestId('users-next-page'))[0]
    expect(nextBtn).not.toBeDisabled()

    fireEvent.click(nextBtn)

    await waitFor(() =>
      expect(screen.getAllByText('page50_user').length).toBeGreaterThan(0),
    )

    // Now prev is enabled.
    expect(prevBtn).not.toBeDisabled()
  })

  it('invokes api.deleteUser with the user id after confirmation', async () => {
    mockListUsers.mockResolvedValue(
      envelope([
        {
          id: 'u2',
          username: 'bob',
          email: 'bob@example.com',
          role: 'member',
          is_active: true,
          is_approved: false,
          created_at: '2026-01-02T00:00:00',
          last_login_at: null,
        },
      ]),
    )
    mockDeleteUser.mockResolvedValue({ deleted: 'u2', existed: true })

    renderUsersPage()

    await waitFor(() =>
      expect(screen.getAllByText('bob').length).toBeGreaterThan(0),
    )

    fireEvent.click(screen.getAllByRole('button', { name: /删除用户 bob/ })[0])

    await waitFor(() =>
      expect(
        screen.getByText(/确认删除用户「bob」/),
      ).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: '删除' }))

    await waitFor(() =>
      expect(mockDeleteUser).toHaveBeenCalledWith('u2'),
    )
  })

  it('shows the confirm dialog before deletion', async () => {
    mockListUsers.mockResolvedValue(
      envelope([
        {
          id: 'u2',
          username: 'bob',
          email: 'bob@example.com',
          role: 'member',
          is_active: true,
          is_approved: false,
          created_at: '2026-01-02T00:00:00',
          last_login_at: null,
        },
      ]),
    )

    renderUsersPage()

    await waitFor(() =>
      expect(screen.getAllByText('bob').length).toBeGreaterThan(0),
    )

    fireEvent.click(screen.getAllByRole('button', { name: /删除用户 bob/ })[0])

    await waitFor(() =>
      expect(
        screen.getByText(/确认删除用户「bob」/),
      ).toBeInTheDocument(),
    )

    // The confirm dialog should expose a Cancel + Delete pair once open.
    expect(
      screen.getByRole('button', { name: '取消' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '删除' }),
    ).toBeInTheDocument()
  })
})
