import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fireEvent,
  render,
  screen,
  waitFor,
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
  vi.clearAllMocks()
})

describe('UsersPage', () => {
  it('renders the user table and supports search filtering', async () => {
    mockListUsers.mockResolvedValue([
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
    ])

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('alice')).toBeInTheDocument()
      expect(screen.getByText('bob')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('搜索用户名或邮箱'), {
      target: { value: 'alice' },
    })

    await waitFor(() => {
      expect(screen.getByText('alice')).toBeInTheDocument()
      expect(screen.queryByText('bob')).not.toBeInTheDocument()
    })
  })

  it('invokes api.deleteUser with the user id after confirmation', async () => {
    mockListUsers.mockResolvedValue([
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
    ])
    mockDeleteUser.mockResolvedValue({ deleted: 'u2', existed: true })

    renderUsersPage()

    await waitFor(() =>
      expect(screen.getByText('bob')).toBeInTheDocument(),
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
    mockListUsers.mockResolvedValue([
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
    ])

    renderUsersPage()

    await waitFor(() =>
      expect(screen.getByText('bob')).toBeInTheDocument(),
    )

    // The alert-dialog body is rendered into a portal. Chakra mounts it
    // ahead of `isOpen=true`, so the body may be present in the DOM but
    // hidden; we simply assert it gains a visible role once opened.
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