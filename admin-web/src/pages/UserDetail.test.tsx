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
// We deliberately mock only the methods this page touches; everything else
// falls through to the un-mocked api surface (which we never call here).
const mockListUsers = vi.fn()
const mockListUserFeatures = vi.fn()
const mockUpdateUserFeature = vi.fn()
const mockGetUserStats = vi.fn()
const mockUpdateUser = vi.fn()
const mockGetUserQuota = vi.fn()
const mockResetUserQuota = vi.fn()
const mockMe = vi.fn()

vi.mock('../api', () => ({
  api: {
    me: (...args: unknown[]) => mockMe(...args),
    listUsers: (...args: unknown[]) => mockListUsers(...args),
    listUserFeatures: (...args: unknown[]) => mockListUserFeatures(...args),
    updateUserFeature: (...args: unknown[]) => mockUpdateUserFeature(...args),
    getUserStats: (...args: unknown[]) => mockGetUserStats(...args),
    updateUser: (...args: unknown[]) => mockUpdateUser(...args),
    getUserQuota: (...args: unknown[]) => mockGetUserQuota(...args),
    resetUserQuota: (...args: unknown[]) => mockResetUserQuota(...args),
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

function envelopeForUserList(users: unknown[] = [adminUser, memberUser], total = 2) {
  return { total, items: users, limit: 200, offset: 0 }
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
  mockGetUserStats.mockReset()
  mockUpdateUser.mockReset()
  mockGetUserQuota.mockReset()
  mockResetUserQuota.mockReset()
  mockMe.mockReset()

  // Page defaults look up bob (member, u2). `me` defaults to alice so
  // self-reject guard tests can flip the perspective.
  mockMe.mockResolvedValue(adminUser)
  mockListUsers.mockResolvedValue(envelopeForUserList([adminUser, memberUser]))
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
  mockGetUserStats.mockResolvedValue({
    user_id: 'u2',
    kb_count: 4,
    doc_count: 17,
    chat_count: 92,
  })
  mockUpdateUser.mockImplementation(async (id: string, body: Record<string, unknown>) => {
    const target = id === 'u1' ? adminUser : memberUser
    return {
      ...target,
      ...body,
    }
  })
  // Default quota for bob: 100k total, 20k used, monthly.
  mockGetUserQuota.mockResolvedValue({
    tokens_total: 100000,
    tokens_used: 20000,
    tokens_remaining: 80000,
    period: 'monthly',
    reset_at: '2026-09-01T00:00:00',
    usage_breakdown: [
      { date: '2026-08-10', prompt_tokens: 5000, completion_tokens: 2000, total_tokens: 7000, calls: 3 },
      { date: '2026-08-11', prompt_tokens: 8000, completion_tokens: 5000, total_tokens: 13000, calls: 5 },
    ],
  })
  mockResetUserQuota.mockResolvedValue(undefined)
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

  it('renders the stats card with kb/doc/chat counts', async () => {
    renderUserDetail('u2')

    await waitFor(() =>
      expect(
        screen.getByText(/用户详情 · bob/),
      ).toBeInTheDocument(),
    )

    // Stat labels are present and counts render.
    expect(screen.getByText('知识库')).toBeInTheDocument()
    expect(screen.getByText('文档')).toBeInTheDocument()
    expect(screen.getByText('问答记录')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getByText('17')).toBeInTheDocument()
    expect(screen.getByText('92')).toBeInTheDocument()

    // The stats call fires with the right id.
    expect(mockGetUserStats).toHaveBeenCalledWith('u2')
  })

  it('shows approve + reject buttons with the reject disabled for self', async () => {
    renderUserDetail('u1')

    await waitFor(() =>
      expect(
        screen.getByText(/用户详情 · alice/),
      ).toBeInTheDocument(),
    )

    const approveBtn = screen.getByTestId('user-detail-approve-btn')
    const rejectBtn = screen.getByTestId('user-detail-reject-btn')

    // alice (admin) is already approved ⇒ approve button is disabled.
    expect(approveBtn).toBeDisabled()
    // alice is the current admin ⇒ reject must be disabled to avoid
    // self-lockout (INC-005 / Phase 2.0 self-demotion guard).
    expect(rejectBtn).toBeDisabled()
  })

  it('invokes api.updateUser with is_approved=true when approve is clicked', async () => {
    // bob (member, not yet approved) — the default fixture has him at
    // is_approved=false so the approve button is enabled.
    renderUserDetail('u2')

    await waitFor(() =>
      expect(
        screen.getByText(/用户详情 · bob/),
      ).toBeInTheDocument(),
    )

    const approveBtn = screen.getByTestId('user-detail-approve-btn')
    expect(approveBtn).not.toBeDisabled()

    fireEvent.click(approveBtn)

    await waitFor(() =>
      expect(mockUpdateUser).toHaveBeenCalledWith('u2', { is_approved: true }),
    )
  })

  it('invokes api.updateUser with is_approved=false after the reject confirm', async () => {
    // bob (member, approved=true) — flip him to approved first so the
    // reject button becomes enabled.
    mockListUsers.mockResolvedValue(
      envelopeForUserList([
        adminUser,
        { ...memberUser, is_approved: true },
      ]),
    )

    renderUserDetail('u2')

    await waitFor(() =>
      expect(
        screen.getByText(/用户详情 · bob/),
      ).toBeInTheDocument(),
    )

    const rejectBtn = screen.getByTestId('user-detail-reject-btn')
    expect(rejectBtn).not.toBeDisabled()

    fireEvent.click(rejectBtn)

    await waitFor(() =>
      expect(
        screen.getByText(/撤销对「bob」/),
      ).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: '撤销' }))

    await waitFor(() =>
      expect(mockUpdateUser).toHaveBeenCalledWith(
        'u2',
        { is_approved: false },
      ),
    )
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
    mockListUsers.mockResolvedValue(envelopeForUserList([adminUser, memberUser]))
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

  // ---------------------------------------------------------------------------
  // Quota tab (Phase 2.1)
  // ---------------------------------------------------------------------------

  it('renders the quota tab with usage / total / remaining tokens', async () => {
    renderUserDetail('u2')

    await waitFor(() =>
      expect(screen.getByText(/用户详情 · bob/)).toBeInTheDocument(),
    )

    // Wait for the quota fetch + render (data-testid 来自 UserQuotaCard)
    await waitFor(() => {
      expect(screen.getByTestId('quota-used-tokens')).toBeInTheDocument()
    })

    // 20000 → 20.0K, 100000 → 100K, 80000 → 80.0K
    expect(screen.getByTestId('quota-used-tokens')).toHaveTextContent('20.0K')
    expect(screen.getByTestId('quota-total-tokens')).toHaveTextContent('100K')
    expect(screen.getByTestId('quota-remaining-tokens')).toHaveTextContent('80.0K')

    // 进度条 + 30 天表格 2 行
    expect(screen.getByTestId('quota-progress')).toBeInTheDocument()
    const rows = screen.getAllByTestId('quota-usage-row')
    expect(rows).toHaveLength(2)

    // API 调用次数
    expect(mockGetUserQuota).toHaveBeenCalledWith('u2')
  })

  it('saves the new total tokens via updateUser', async () => {
    renderUserDetail('u2')

    await waitFor(() =>
      expect(screen.getByText(/用户详情 · bob/)).toBeInTheDocument(),
    )

    await waitFor(() => {
      expect(screen.getByTestId('quota-total-input')).toBeInTheDocument()
    })

    // 在 number input 输入 50000
    const input = screen.getByTestId('quota-total-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '50000' } })

    // 点保存
    fireEvent.click(screen.getByTestId('quota-save-button'))

    // updateUser 应该被以 {quota_tokens_total: 50000} 调用
    await waitFor(() =>
      expect(mockUpdateUser).toHaveBeenCalledWith(
        'u2',
        expect.objectContaining({ quota_tokens_total: 50000 }),
      ),
    )
  })

  it('opens a confirm dialog before resetting the user quota', async () => {
    renderUserDetail('u2')

    await waitFor(() =>
      expect(screen.getByText(/用户详情 · bob/)).toBeInTheDocument(),
    )

    await waitFor(() => {
      expect(screen.getByTestId('quota-reset-button')).toBeInTheDocument()
    })

    // 点重置
    fireEvent.click(screen.getByTestId('quota-reset-button'))

    // 确认对话框出现 (data-testid 在 confirm 按钮上)
    await waitFor(() => {
      expect(screen.getByTestId('quota-reset-confirm')).toBeInTheDocument()
    })

    // 确认
    fireEvent.click(screen.getByTestId('quota-reset-confirm'))

    // resetUserQuota 被调用
    await waitFor(() => expect(mockResetUserQuota).toHaveBeenCalledWith('u2'))
  })
})
