import { beforeEach, describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ChakraProvider } from '@chakra-ui/react'
import { KBSettings } from './KBSettings'
import {
  DEFAULT_PDF_SETTINGS,
  PARSER_LABELS,
  VISION_LLM_WARNING,
} from '../lib/pdfSettings'

const { mockGetSettings, mockUpdateSettings, mockToast } = vi.hoisted(() => ({
  mockGetSettings: vi.fn(),
  mockUpdateSettings: vi.fn(),
  mockToast: vi.fn(),
}))

vi.mock('../api', () => ({
  api: {
    kbSettings: (kbId: string) => mockGetSettings(kbId),
    updateKBSettings: (kbId: string, settings: unknown) =>
      mockUpdateSettings(kbId, settings),
  },
}))

vi.mock('@chakra-ui/react', async () => {
  const actual = await vi.importActual<typeof import('@chakra-ui/react')>('@chakra-ui/react')
  return { ...actual, useToast: () => mockToast }
})

function renderKBSettings(props: Partial<React.ComponentProps<typeof KBSettings>> = {}) {
  return render(
    <ChakraProvider>
      <KBSettings kbId="kb-1" isOpen={true} onClose={vi.fn()} {...props} />
    </ChakraProvider>,
  )
}

beforeEach(() => {
  mockGetSettings.mockReset()
  mockUpdateSettings.mockReset()
  mockToast.mockReset()
  mockGetSettings.mockResolvedValue(DEFAULT_PDF_SETTINGS)
  mockUpdateSettings.mockResolvedValue(DEFAULT_PDF_SETTINGS)
})

describe('KBSettings', () => {
  test('renders drawer with all PDF setting sections', async () => {
    renderKBSettings()

    expect(await screen.findByText('启用 Tesseract OCR (扫描件)')).toBeInTheDocument()
    expect(screen.getByText('启用 Qwen-VL-Max 多模态')).toBeInTheDocument()
    expect(screen.getByText('解析器偏好')).toBeInTheDocument()
    expect(screen.getByText('PDF 缓存大小 (MB)')).toBeInTheDocument()
    expect(screen.getByText('多模态 LLM 月度预算 (¥)')).toBeInTheDocument()
  })

  test('loads settings for the knowledge base when opened', async () => {
    renderKBSettings()

    await waitFor(() => {
      expect(mockGetSettings).toHaveBeenCalledWith('kb-1')
    })
  })

  test('shows the vision cost warning when vision is enabled', async () => {
    mockGetSettings.mockResolvedValue({
      ...DEFAULT_PDF_SETTINGS,
      enable_vision_llm: true,
    })
    renderKBSettings()

    expect(await screen.findByText(VISION_LLM_WARNING)).toBeInTheDocument()
  })

  test('parser preference select exposes all four parser choices', async () => {
    renderKBSettings()
    await screen.findByText('解析器偏好')

    for (const label of Object.values(PARSER_LABELS)) {
      expect(screen.getByRole('option', { name: label })).toBeInTheDocument()
    }
  })

  test('saves settings and shows a success toast', async () => {
    renderKBSettings()
    await screen.findByText('解析器偏好')

    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(mockUpdateSettings).toHaveBeenCalledWith(
        'kb-1',
        expect.objectContaining({
          enable_ocr: false,
          enable_vision_llm: false,
          parser_preference: 'auto',
          pdf_cache_size_mb: 10240,
          vision_llm_monthly_limit_yuan: 5000,
        }),
      )
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'success', title: '设置已保存' }),
      )
    })
  })
})
