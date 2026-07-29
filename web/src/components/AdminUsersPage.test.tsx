// AdminUsersPage 单元测试 - 5 个 Vitest spec 覆盖:
//   1. 初始加载: Spinner
//   2. 加载完成: 用户表 + 搜索框
//   3. 批准用户: 列表更新 + toast.success
//   4. 切换角色: 列表更新 + toast
//   5. 删除用户: 列表移除 + toast
//
// 设计要点:
//   - 0 改 AdminUsersPage.tsx (chakra useToast 必须从 hook 拿, 但我们 mock hook 返回一个 plain fn)
//   - mock 掉 ../api, 内存级 vi.fn() 接管 adminListUsers/adminUpdateUser/adminDeleteUser
//   - vi.mock '@chakra-ui/react', partial mock: spread actual + 用 plain vi.fn() 替换 useToast
//     (不能整包 mock, 否则 ChakraProvider/Spinner/Button/Table 都没了)
//
// 复用 web/src/components/__tests__/test-utils.tsx 的 ChakraProvider wrapper
//   - 这样未来 LoginPage / RegisterPage 等都能用同一个 helper

import { beforeEach, describe, expect, test, vi } from 'vitest'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { renderWithChakra } from './__tests__/test-utils'

// --- mock 整个 ../api, 让 api.adminXxx 变成内存中的 vi.fn ---
const mockListUsers = vi.fn()
const mockUpdateUser = vi.fn()
const mockDeleteUser = vi.fn()

vi.mock('../api', () => ({
  api: {
    adminListUsers: () => mockListUsers(),
    adminUpdateUser: (...args: unknown[]) => mockUpdateUser(...args),
    adminDeleteUser: (...args: unknown[]) => mockDeleteUser(...args),
  },
  USER_STORAGE_KEY: 'test_user_storage_key',
}))

// --- partial mock '@chakra-ui/react', 把 useToast 换成直接返回 mockToast ---
const mockToast = vi.fn()
vi.mock('@chakra-ui/react', async () => {
  const actual =
    await vi.importActual<typeof import('@chakra-ui/react')>('@chakra-ui/react')
  return {
    ...actual,
    useToast: () => mockToast,
  }
})

// 注: import 放在 vi.mock 之后, 让 mock 生效
import { AdminUsersPage } from './AdminUsersPage'

// --- 测试 fixtures ---
const baseUser = {
  id: 'u1',
  username: 'admin',
  email: 'admin@test',
  role: 'admin' as const,
  is_active: true,
  is_approved: true,
  created_at: '2025-01-01T00:00:00',
  last_login_at: null,
}

const member1Approved = {
  id: 'u2',
  username: 'member1',
  email: 'm1@test',
  role: 'member' as const,
  is_active: true,
  is_approved: true,
  created_at: '2025-01-02T00:00:00',
  last_login_at: null,
}

const member2Pending = {
  // 待批准用户, 用例 3 用它来测批准按钮
  id: 'u3',
  username: 'member2',
  email: 'm2@test',
  role: 'member' as const,
  is_active: true,
  is_approved: false,
  created_at: '2025-01-03T00:00:00',
  last_login_at: null,
}

function renderPage() {
  return render(renderWithChakra(<AdminUsersPage />))
}

// helper: 定位 username='xxx' 的用户行 tr.
// 注意: 'admin' 既出现在 td (用户名) 又出现在 role badge, 所以要 scope 到 row 内.
// Chakra <Td> 在 JSDOM 里没有 'cell' role, 改用 *ElementsByTagName.
function getUserRow(username: string): HTMLTableRowElement {
  const rows = screen.getAllByRole('row')
  for (const row of rows) {
    // thead 的 row 用 <th>, tbody 的 row 用 <td>. 这里只关心 tbody rows.
    const cells = (row as HTMLTableRowElement).cells
    if (cells.length === 0) continue
    if (cells[0].textContent === username) {
      return row as HTMLTableRowElement
    }
  }
  throw new Error(`No row with username="${username}" found`)
}

beforeEach(() => {
  mockListUsers.mockReset()
  mockUpdateUser.mockReset()
  mockDeleteUser.mockReset()
  mockToast.mockReset()
  // 默认本地存储里没有 current user (AdminUsersPage 用 useMemo 读 localStorage),
  // 这样 isSelf() 永远 false, 4 个操作按钮全部启用
  localStorage.clear()
  // 删除弹窗默认 true
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

// ============================================================================
// 1. 初始加载状态 - 只看 spinner / 加载中文案, 不等列表
// ============================================================================
test('renders loading spinner on mount', async () => {
  // 故意 pending: 永不 resolve, 这样 loading 状态不会结束
  mockListUsers.mockReturnValue(new Promise(() => {}))

  const { container } = renderPage()

  // 默认就是 loading=true, 立即可见加载文案
  expect(screen.getByText('加载中...')).toBeInTheDocument()
  // Chakra Spinner 渲染成一个 .chakra-spinner class (无 SVG 在 JSDOM)
  expect(container.querySelector('.chakra-spinner')).toBeTruthy()
  // 加载中分支没有 <table>: queryAllByRole('row') 应为空数组
  expect(screen.queryAllByRole('row')).toHaveLength(0)
  // 不应出现 user 邮箱文案
  expect(screen.queryByText('admin@test')).toBeNull()
})

// ============================================================================
// 2. 加载完成 - 用户表行 + 搜索框
// ============================================================================
test('renders user table with search input after list resolves', async () => {
  mockListUsers.mockResolvedValueOnce([baseUser, member1Approved])

  renderPage()

  // 等表行 (data-render -> after listUsers resolves -> setUsers -> render)
  await waitFor(() => {
    expect(getUserRow('admin')).toBeInTheDocument()
  })
  expect(getUserRow('member1')).toBeInTheDocument()

  // 邮箱 cell - 邮箱唯一不会跟用户名/角色冲突
  expect(screen.getByText('admin@test')).toBeInTheDocument()
  expect(screen.getByText('m1@test')).toBeInTheDocument()

  // 搜索框 - placeholder 命中
  const search = screen.getByPlaceholderText('搜索用户名或邮箱')
  expect(search).toBeInTheDocument()
  fireEvent.change(search, { target: { value: 'admin' } })
  // 输入 'admin' 后, 只剩 admin 用户 (member1 不在表格里)
  await waitFor(() => {
    expect(screen.queryByText('m1@test')).toBeNull()
  })
  expect(getUserRow('admin')).toBeInTheDocument()
})

// ============================================================================
// 3. 批准用户 - 点 "批准" 按钮, API 调用 + toast + 列表更新
// ============================================================================
test('approve user updates list and fires success toast', async () => {
  mockListUsers.mockResolvedValueOnce([baseUser, member2Pending])
  // 批准后端返回更新后的 user: is_approved: true
  mockUpdateUser.mockResolvedValueOnce({
    ...member2Pending,
    is_approved: true,
  })

  renderPage()
  await waitFor(() => {
    expect(getUserRow('member2')).toBeInTheDocument()
  })

  // member2 行内应有 "批准" 按钮, baseUser (admin) 已批准 -> 只有 member2 行才有
  const member2Row = getUserRow('member2')
  const approveBtn = within(member2Row).getByRole('button', { name: '批准' })
  expect(approveBtn).toBeInTheDocument()
  fireEvent.click(approveBtn)

  await waitFor(() => {
    expect(mockUpdateUser).toHaveBeenCalledWith('u3', { is_approved: true })
  })

  // 成功后, 该行不再有 "批准" 按钮, 而是 "已批准" badge
  await waitFor(() => {
    expect(within(member2Row).queryByText('批准')).toBeNull()
  })
  // 全表已有两个 "已批准" badge (admin + member2)
  expect(screen.getAllByText('已批准')).toHaveLength(2)

  // toast.success 调用: title 应是 "<username> 已批准"
  expect(mockToast).toHaveBeenCalled()
  const call = mockToast.mock.calls.find(
    (args) =>
      typeof args[0] === 'object' &&
      args[0] !== null &&
      (args[0] as { title?: string }).title === 'member2 已批准',
  )
  expect(call).toBeTruthy()
})

// ============================================================================
// 4. 切换角色 - admin -> member, API 调用 role=member + toast
// ============================================================================
test('change role to member updates list and fires toast', async () => {
  mockListUsers.mockResolvedValueOnce([baseUser, member1Approved])
  mockUpdateUser.mockResolvedValueOnce({
    ...baseUser,
    role: 'member',
  })

  renderPage()
  await waitFor(() => {
    expect(getUserRow('admin')).toBeInTheDocument()
  })

  // baseUser.role === 'admin', 按钮 label 是 "降为 member".
  // 直接按 label 找按钮 (label 唯一, 不受 badge 同字串影响).
  const adminRow = getUserRow('admin')
  const roleBtn = within(adminRow).getByRole('button', {
    name: '降为 member',
  })
  expect(roleBtn).toBeInTheDocument()
  fireEvent.click(roleBtn)

  await waitFor(() => {
    expect(mockUpdateUser).toHaveBeenCalledWith('u1', { role: 'member' })
  })

  // 列表应已经把这个 admin 用户更新成 member - 按钮文案翻转
  await waitFor(() => {
    expect(
      within(adminRow).getByRole('button', { name: '提为 admin' }),
    ).toBeInTheDocument()
  })

  // toast: title 是 "<username> 角色已改为 member"
  const call = mockToast.mock.calls.find(
    (args) =>
      typeof args[0] === 'object' &&
      args[0] !== null &&
      (args[0] as { title?: string }).title === 'admin 角色已改为 member',
  )
  expect(call).toBeTruthy()
})

// ============================================================================
// 5. 删除用户 - 点 "删除" -> confirm -> API -> list 移除
// ============================================================================
test('delete user cascade removes them from the list', async () => {
  mockListUsers.mockResolvedValueOnce([baseUser, member1Approved])
  mockDeleteUser.mockResolvedValueOnce(undefined)

  renderPage()
  await waitFor(() => {
    expect(getUserRow('member1')).toBeInTheDocument()
  })

  // member1 行内点删除 (按行 scope, 不被 admin 行的删除按钮干扰)
  const member1Row = getUserRow('member1')
  const deleteBtn = within(member1Row).getByRole('button', { name: '删除' })
  fireEvent.click(deleteBtn)

  await waitFor(() => {
    expect(mockDeleteUser).toHaveBeenCalledWith('u2')
  })

  // confirm 应被弹过
  expect(window.confirm).toHaveBeenCalled()

  // 列表应只剩 admin (m1@test 邮箱消失, admin@test 仍存)
  await waitFor(() => {
    expect(screen.queryByText('m1@test')).toBeNull()
  })
  expect(screen.getByText('admin@test')).toBeInTheDocument()

  // toast: "<username> 已删除"
  const call = mockToast.mock.calls.find(
    (args) =>
      typeof args[0] === 'object' &&
      args[0] !== null &&
      (args[0] as { title?: string }).title === 'member1 已删除',
  )
  expect(call).toBeTruthy()
})
