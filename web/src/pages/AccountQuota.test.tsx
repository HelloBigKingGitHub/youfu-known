// AccountQuota.test.tsx — Phase 2.1
// 覆盖:
//   1. 正常用户: 卡片渲染 已用 / 总额 + 进度条 + 用量表格
//   2. 超额状态: 红色 banner 显示
//   3. 无限额: total=0 时显示 "无限额", 不显示进度条 (显示占位条)
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { ChakraProvider } from '@chakra-ui/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AccountQuota } from './AccountQuota'
import type { QuotaInfo } from '../api'

const mockGetMyQuota = vi.fn()
const mockToast = vi.fn()

vi.mock('../api', () => ({
  api: {
    getMyQuota: () => mockGetMyQuota(),
  },
}))

vi.mock('@chakra-ui/react', async () => {
  const actual = await vi.importActual<typeof import('@chakra-ui/react')>('@chakra-ui/react')
  return { ...actual, useToast: () => mockToast }
})

function makeQuota(overrides: Partial<QuotaInfo> = {}): QuotaInfo {
  return {
    tokens_total: 100000,
    tokens_used: 20000,
    tokens_remaining: 80000,
    period: 'monthly',
    reset_at: '2026-09-01T00:00:00',
    usage_breakdown: [
      {
        date: '2026-08-10',
        prompt_tokens: 5000,
        completion_tokens: 2000,
        total_tokens: 7000,
        calls: 3,
      },
      {
        date: '2026-08-11',
        prompt_tokens: 8000,
        completion_tokens: 5000,
        total_tokens: 13000,
        calls: 5,
      },
    ],
    ...overrides,
  }
}

function renderPage() {
  return render(
    <ChakraProvider>
      <MemoryRouter initialEntries={['/account/quota']}>
        <Routes>
          <Route path="/account/quota" element={<AccountQuota />} />
        </Routes>
      </MemoryRouter>
    </ChakraProvider>,
  )
}

beforeEach(() => {
  mockGetMyQuota.mockReset()
  mockToast.mockReset()
  mockGetMyQuota.mockResolvedValue(makeQuota())
})

describe('AccountQuota', () => {
  it('renders the summary card with used/total tokens and the usage table', async () => {
    renderPage()

    // 标题
    expect(await screen.findByText('我的额度')).toBeInTheDocument()

    // 等待数据加载完 (loading 消失)
    await waitFor(() => {
      expect(mockGetMyQuota).toHaveBeenCalledTimes(1)
    })

    // 周期文案 (period='monthly' → '按月')
    expect(screen.getByText(/周期 · 按月/)).toBeInTheDocument()

    // 进度条在 (data-testid)
    expect(screen.getByTestId('quota-progress')).toBeInTheDocument()

    // 用量表格: 2 行
    const rows = screen.getAllByTestId('quota-usage-row')
    expect(rows).toHaveLength(2)

    // 合计 (20000 / 1000 → 20.0K)
    // 注意: Chakra Text 节点可能拆成多个 textNode, 用 data-testid 锁元素
    expect(screen.getByTestId('quota-used-tokens')).toHaveTextContent('20.0K')
    // 总额 100000 → 100K
    expect(screen.getByTestId('quota-total-tokens')).toHaveTextContent('100K')
    // 剩余 80000 → 80.0K
    expect(screen.getByTestId('quota-remaining-tokens')).toHaveTextContent('80.0K')

    // 不显示超额 banner
    expect(screen.queryByTestId('quota-exhausted-banner')).not.toBeInTheDocument()
  })

  it('shows a red exhausted banner when tokens_used >= tokens_total', async () => {
    mockGetMyQuota.mockResolvedValue(
      makeQuota({
        tokens_total: 100000,
        tokens_used: 120000,
        tokens_remaining: 0,
      }),
    )

    renderPage()

    expect(
      await screen.findByTestId('quota-exhausted-banner'),
    ).toBeInTheDocument()

    // banner 内文断言
    expect(screen.getByText(/额度已用完/)).toBeInTheDocument()
  })

  it('shows "无限额" and hides the progress bar when tokens_total is 0', async () => {
    mockGetMyQuota.mockResolvedValue(
      makeQuota({
        tokens_total: 0,
        tokens_used: 50000,
        tokens_remaining: null,
        period: 'none',
        reset_at: null,
      }),
    )

    renderPage()

    // 标题 + "无限额" 文案 (DOM 里是 "周期 · 无限额", 精确匹配 '无限额' 失败, 用正则)
    expect(await screen.findByText('我的额度')).toBeInTheDocument()
    expect(screen.getByText(/无限额/)).toBeInTheDocument()
    // 无限额时 progress 隐藏, 改为 unlimited 占位条
    expect(screen.getByTestId('quota-unlimited')).toBeInTheDocument()
    expect(screen.queryByTestId('quota-progress')).not.toBeInTheDocument()
    // 不显示超额 banner
    expect(screen.queryByTestId('quota-exhausted-banner')).not.toBeInTheDocument()
  })
})
