import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { ChakraProvider } from '@chakra-ui/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { UserDetail } from './UserDetail'

// Mock the api module so UserDetail can be exercised without an HTTP backend.
// We deliberately mock only the three methods this page touches; everything
// else falls through to the un-mocked api surface (which we never call here).
const mockListUsers = vi.fn()
const mockListUserFeatures = vi.fn()
const mockUpdateUserFeature = vi.fn()
const mockMe = vi.fn()

vi.mock('../api', () => ({
  api: {
    me: (...args: unknown[]) => mockMe(...args),
    listUsers: (...args: unknown[]) => mockListUsers(...args),
    listUserFeatures: (...args: unknown[]) => mockListUserFeatures(...args),
    updateUserFeature: (...args: unknown[]) => mockUpdateUserFeature(...args),
  },
  formatApiError: (err: unknown) =>
    err instanceof Error ? err.message : String(err),
}))

const adminUser = {
  id: 'u1',
  username: 'alice',
  email: 'alice@example.com',
  role: 'admin' as const,
  is_active: true,
  is_approved: true,
  created_at: '2026-01-01T00:00:00',
  last_login_at: '2026-02-01T00:00:00',
}

const memberUser = {
  id: 'u2',
  username: 'bob',
  email: 'bob@example.com',
  role: 'member' as const,
  is_active: true,
  is_approved: false,
  created_at: '2026-01-02T00:00:00',
  last_login_at: null,
}

function renderUserDetail(userId: string = 'u2') {
  return render(
    <ChakraProvider>
      <MemoryRouter initialEntries={[`/admin/users/${userId}`]}>
        <Routes>
          <Route path="/admin/users/:id" element={<UserDetail />} />
        </Routes>
      </MemoryRouter>
    </ChakraProvider>,
  )
}

afterEach(() => {
  cleanup()
})

beforeEach(() => {
  mockListUsers.mockReset()
  mockListUserFeatures.mockReset()
  mockUpdateUserFeature.mockReset()
  mockMe.mockReset()
  // Page defaults look up bob (member, u2).
  mockListUsers.mockResolvedValue([adminUser, memberUser])
  mockListUserFeatures.mockResolvedValue([
    {
      user_id: 'u2',
      feature: 'kb_chat',
      enabled: true,
      granted_by: 'admin',
      granted_at: '2026-01-02T00:00:00',
      created_at: '2026-01-02T00:00:00',
    },
  ])
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('UserDetail', () => {
  it('renders 5 feature cards with default states', async () => {
    renderUserDetail('u2')

    await waitFor(() =>
      expect(
        screen.getByText(/用户详情 · bob/),
      ).toBeInTheDocument(),
    )

    // All 5 feature labels are present.
    expect(screen.getByText('知识库问答 (KB Chat)')).toBeInTheDocument()
    expect(screen.getByText('创建知识库')).toBeInTheDocument()
    expect(screen.getByText('上传文档')).toBeInTheDocument()
    expect(screen.getByText('删除文档')).toBeInTheDocument()
    expect(screen.getByText('历史会话')).toBeInTheDocument()

    // Bob (member) does not override kb_create ⇒ falls back to default=false.
    expect(screen.getAllByText('默认 关闭').length).toBeGreaterThanOrEqual(3)
    // chat_history default is true, and bob has no override either.
    expect(screen.getAllByText('默认 启用').length).toBeGreaterThanOrEqual(1)
  })

  it('toggles a feature and calls api.updateUserFeature after confirm', async () => {
    mockUpdateUserFeature.mockResolvedValue({
      user_id: 'u2',
      feature: 'kb_create',
      enabled: true,
      granted_by: 'admin',
      granted_at: '2026-02-15T00:00:00',
      created_at: '2026-02-15T00:00:00',
    })
    // After the toggle the page re-fetches flags — provide a second list.
    mockListUserFeatures
      .mockResolvedValueOnce([
        {
          user_id: 'u2',
          feature: 'kb_chat',
          enabled: true,
          granted_by: 'admin',
          granted_at: '2026-01-02T00:00:00',
          created_at: '2026-01-02T00:00:00',
        },
      ])
      .mockResolvedValueOnce([
        {
          user_id: 'u2',
          feature: 'kb_chat',
          enabled: true,
          granted_by: 'admin',
          granted_at: '2026-01-02T00:00:00',
          created_at: '2026-01-02T00:00:00',
        },
        {
          user_id: 'u2',
          feature: 'kb_create',
          enabled: true,
          granted_by: 'admin',
          granted_at: '2026-02-15T00:00:00',
          created_at: '2026-02-15T00:00:00',
        },
      ])

    renderUserDetail('u2')

    await waitFor(() =>
      expect(screen.getByText('创建知识库')).toBeInTheDocument(),
    )

    // The second switch corresponds to kb_create in FEATURE_DEFS order.
    const allSwitches = Array.from(document.querySelectorAll('label.chakra-switch'))
    // React 18 StrictMode mounts twice — use unique filter
    const seen = new Set<Element>()
    const uniqueSwitches = allSwitches.filter((sw) => {
      if (seen.has(sw)) return false
      seen.add(sw)
      return true
    })
    const switches = uniqueSwitches
    expect(switches.length).toBe(5)
    fireEvent.click(switches[1])

    await waitFor(() =>
      expect(
        screen.getByText(/确定要为用户「bob」启用功能「创建知识库」/),
      ).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: '启用' }))

    await waitFor(() =>
      expect(mockUpdateUserFeature).toHaveBeenCalledWith(
        'u2',
        'kb_create',
        true,
      ),
    )

    // The second GET must have fired to refresh the flag list.
    expect(mockListUserFeatures).toHaveBeenCalledTimes(2)
  })

  it('shows the confirm dialog before a toggle takes effect', async () => {
    renderUserDetail('u2')

    await waitFor(() =>
      expect(screen.getByText('创建知识库')).toBeInTheDocument(),
    )

    const allSwitches = Array.from(document.querySelectorAll('label.chakra-switch'))
    // React 18 StrictMode mounts twice — use unique filter
    const seen = new Set<Element>()
    const uniqueSwitches = allSwitches.filter((sw) => {
      if (seen.has(sw)) return false
      seen.add(sw)
      return true
    })
    const switches = uniqueSwitches
    fireEvent.click(switches[1])

    await waitFor(() =>
      expect(
        screen.getByText(/确定要为用户「bob」启用功能「创建知识库」/),
      ).toBeInTheDocument(),
    )

    // While the dialog is open, the toggle has not been sent yet.
    expect(mockUpdateUserFeature).not.toHaveBeenCalled()
    expect(
      screen.getByRole('button', { name: '取消' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '启用' }),
    ).toBeInTheDocument()

    // Cancel closes the dialog without mutating.
    fireEvent.click(screen.getByRole('button', { name: '取消' }))

    await waitFor(() =>
      expect(mockUpdateUserFeature).not.toHaveBeenCalled(),
    )
  })

  it('bypasses overrides for admin users and disables their switches', async () => {
    // alice (admin) has no flags but every switch must read true.
    mockListUsers.mockResolvedValue([adminUser, memberUser])
    mockListUserFeatures.mockResolvedValue([])

    renderUserDetail('u1')

    await waitFor(() =>
      expect(
        screen.getByText(/用户详情 · alice/),
      ).toBeInTheDocument(),
    )

    // Each enabled tag should read "已启用" at minimum once per card.
    const enabledTags = screen.getAllByText('已启用')
    expect(enabledTags.length).toBeGreaterThanOrEqual(5)

    const allSwitches = Array.from(document.querySelectorAll('label.chakra-switch'))
    // React 18 StrictMode mounts twice — use unique filter
    const seen = new Set<Element>()
    const uniqueSwitches = allSwitches.filter((sw) => {
      if (seen.has(sw)) return false
      seen.add(sw)
      return true
    })
    const switches = uniqueSwitches
    expect(switches.length).toBe(5)
    switches.forEach((sw) => {
      expect(sw).toHaveAttribute('data-checked', '')
      // The actual disabled <input> sits inside the label
      const input = sw.querySelector('input.chakra-switch__input')
      expect(input).toHaveAttribute('aria-disabled', 'true')
    })

    // Clicking a disabled admin switch must not open the dialog nor call API.
    fireEvent.click(switches[0])
    expect(mockUpdateUserFeature).not.toHaveBeenCalled()
    expect(
      screen.queryByText(/确定要为用户「alice」/),
    ).not.toBeInTheDocument()

    // The admin-bypass hint is shown in every card.
    expect(
      screen.getAllByText('管理员自动启用，无法关闭').length,
    ).toBeGreaterThanOrEqual(5)
  })
})
