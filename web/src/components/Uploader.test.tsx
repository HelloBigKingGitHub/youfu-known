import { beforeEach, describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ChakraProvider } from '@chakra-ui/react'
import { Uploader } from './Uploader'

const { mockUploadDocuments, mockKBSettings, mockToast } = vi.hoisted(() => ({
  mockUploadDocuments: vi.fn(),
  mockKBSettings: vi.fn(),
  mockToast: vi.fn(),
}))

vi.mock('../api', () => ({
  api: {
    uploadDocuments: (...args: unknown[]) => mockUploadDocuments(...args),
    kbSettings: (kbId: string) => mockKBSettings(kbId),
    updateKBSettings: (...args: unknown[]) => mockKBSettings(...args),
  },
}))

vi.mock('@chakra-ui/react', async () => {
  const actual = await vi.importActual<typeof import('@chakra-ui/react')>('@chakra-ui/react')
  return { ...actual, useToast: () => mockToast }
})

function renderUploader() {
  return render(
    <ChakraProvider>
      <Uploader kbId="kb-1" onUploaded={vi.fn()} />
    </ChakraProvider>,
  )
}

function fileInput() {
  return screen.getByLabelText('点击或拖拽上传文件').querySelector('input[type="file"]') as HTMLInputElement
}

beforeEach(() => {
  mockUploadDocuments.mockReset()
  mockKBSettings.mockReset()
  mockToast.mockReset()
  mockKBSettings.mockResolvedValue({
    enable_ocr: false,
    enable_vision_llm: false,
    parser_preference: 'auto',
    pdf_cache_size_mb: 10240,
    vision_llm_monthly_limit_yuan: 5000,
  })
  mockUploadDocuments.mockResolvedValue({
    uploaded: [{ doc_id: 'd1', filename: 'test.pdf', status: 'processing' }],
  })
})

describe('Uploader PDF integration', () => {
  test('loads KB settings when mounted', async () => {
    renderUploader()

    await waitFor(() => {
      expect(mockKBSettings).toHaveBeenCalledWith('kb-1')
    })
  })

  test('shows the selected PDF parser before uploading a PDF', async () => {
    renderUploader()
    await waitFor(() => expect(mockKBSettings).toHaveBeenCalled())

    fireEvent.change(fileInput(), {
      target: {
        files: [new File(['fake pdf'], 'test.pdf', { type: 'application/pdf' })],
      },
    })

    await waitFor(() => {
      expect(mockUploadDocuments).toHaveBeenCalled()
    })
    // The PDF parser info toast fires synchronously inside handleFiles
    // (before await api.uploadDocuments) — assert the parser hint
    // (PARSER_LABELS.auto = "自动 (推荐) - 按 PDF 类型选") is recorded.
    expect(mockToast.mock.calls.some((call) => {
      const arg = call[0] as { status?: string; title?: string }
      return (
        arg &&
        arg.status === 'info' &&
        typeof arg.title === 'string' &&
        arg.title.includes('解析')
      )
    })).toBe(true)
  })

  test('reports upload errors with a toast', async () => {
    mockUploadDocuments.mockRejectedValue(new Error('Upload failed'))
    renderUploader()
    await waitFor(() => expect(mockKBSettings).toHaveBeenCalled())

    fireEvent.change(fileInput(), {
      target: {
        files: [new File(['x'], 'test.pdf', { type: 'application/pdf' })],
      },
    })

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ status: 'error' }))
    })
  })
})
