// 拖拽上传 + 整块可点击
// 现代 SaaS 风格: 圆角大, dashed 边框, 居中布局, 整块点击 + 拖拽
//
// Phase PDF-C.4 适配: 调 api.kbSettings 拿当前 KB 的 PDF 解析偏好,
//   - PDF 上传时 toast 提示走哪个 parser (PyMuPDF / Tesseract OCR / Qwen-VL-Max)
//   - 失败时静默 fallback, 不影响现有拖拽上传
// 0 改行为契约 — 老用户完全无感
import {
  Box,
  Button,
  Flex,
  Icon,
  Progress,
  Text,
  useToast,
  VStack,
} from '@chakra-ui/react'
import { AttachmentIcon } from '@chakra-ui/icons'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { formatApiError } from '../lib/apiErrors'
import { PARSER_LABELS } from '../lib/pdfSettings'

interface Props {
  kbId: string
  onUploaded: () => void
}

const ACCEPT = '.pdf,.docx,.md,.txt,.html,.htm'

function parserHintLabel(pref: string, visionEnabled: boolean): string {
  // auto + 开了 vision = 走 PDFInspector 路由, 复杂 layout 自动跳 vision
  if (pref === 'auto' && visionEnabled) return 'auto (PyMuPDF → Tesseract → Qwen-VL-Max)'
  return PARSER_LABELS[pref as keyof typeof PARSER_LABELS] ?? PARSER_LABELS.auto
}

export function Uploader({ kbId, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState({ loaded: 0, total: 0 })
  const [parserHint, setParserHint] = useState<string>(PARSER_LABELS.auto)
  const toast = useToast()

  // Phase PDF-C.4: mount 时拉 KB settings 拿 parser 偏好
  useEffect(() => {
    let cancelled = false
    api
      .kbSettings(kbId)
      .then((s) => {
        if (cancelled) return
        setParserHint(parserHintLabel(s.parser_preference, s.enable_vision_llm))
      })
      .catch(() => {
        if (!cancelled) setParserHint(PARSER_LABELS.auto)
      })
    return () => {
      cancelled = true
    }
  }, [kbId])

  const openPicker = () => {
    if (!uploading) inputRef.current?.click()
  }

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const list = Array.from(files)
    setUploading(true)
    setProgress({ loaded: 0, total: list.reduce((s, f) => s + f.size, 0) })

    // Phase PDF-C.4: PDF 上传时 toast 提示将用哪个 parser 解析
    const pdfFiles = list.filter((f) => f.name.toLowerCase().endsWith('.pdf'))
    if (pdfFiles.length > 0) {
      toast({
        title: `${pdfFiles.length} 个 PDF 文件, 正在用 ${parserHint} 解析`,
        description: '完成后会自动出现在文档列表',
        status: 'info',
        duration: 5000,
      })
    }

    try {
      const result = await api.uploadDocuments(kbId, list, (loaded, total) => {
        setProgress({ loaded, total })
      })
      toast({
        title: `已上传 ${result.uploaded.length} 个文件`,
        description: '正在后台处理, 完成后会自动出现在下方',
        status: 'success',
        duration: 3000,
      })
      onUploaded()
    } catch (e: unknown) {
      toast({
        title: '上传失败',
        description: formatApiError(e, '上传失败'),
        status: 'error',
        duration: 5000,
      })
    } finally {
      setUploading(false)
      setProgress({ loaded: 0, total: 0 })
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <Box
      borderRadius="xl"
      border="2px dashed"
      borderColor={dragOver ? 'brand.500' : 'surface.border'}
      bg={dragOver ? 'brand.50' : 'white'}
      p={{ base: 5, md: 6 }}
      cursor={uploading ? 'default' : 'pointer'}
      transition="all 0.2s"
      _hover={!uploading ? { borderColor: 'brand.300', bg: 'brand.50' } : undefined}
      onClick={openPicker}
      role="button"
      aria-label="点击或拖拽上传文件"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          openPicker()
        }
      }}
      onDragOver={(e) => {
        e.preventDefault()
        if (!uploading) setDragOver(true)
      }}
      onDragLeave={(e) => {
        e.preventDefault()
        setDragOver(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        if (!uploading) handleFiles(e.dataTransfer.files)
      }}
    >
      <VStack spacing={3} align="center">
        <Flex
          align="center"
          justify="center"
          w={{ base: '48px', md: '56px' }}
          h={{ base: '48px', md: '56px' }}
          borderRadius="2xl"
          bg={dragOver ? 'brand.100' : 'surface.sunken'}
          color={dragOver ? 'brand.600' : 'gray.400'}
          transition="all 0.2s"
        >
          <Icon as={AttachmentIcon} boxSize={{ base: 5, md: 6 }} />
        </Flex>
        <VStack spacing={1} textAlign="center">
          <Text fontSize={{ base: 'sm', md: 'md' }} fontWeight="semibold" color={dragOver ? 'brand.700' : 'gray.700'}>
            {dragOver ? '松开以上传' : '点击或拖文件到这里上传'}
          </Text>
          <Text fontSize="xs" color="gray.500">
            支持 PDF / Word / Markdown / TXT / HTML, 可多选
          </Text>
        </VStack>
        <Button
          size="sm"
          colorScheme="brand"
          variant={dragOver ? 'solid' : 'outline'}
          onClick={(e) => {
            e.stopPropagation()
            openPicker()
          }}
          isLoading={uploading}
          loadingText="上传中"
          minH={{ base: '44px', md: 'auto' }}
        >
          选择文件
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          style={{ display: 'none' }}
          onChange={(e) => handleFiles(e.target.files)}
        />
        {uploading && progress.total > 0 && (
          <Box w="100%" pt={1}>
            <Progress
              value={(progress.loaded / progress.total) * 100}
              size="sm"
              colorScheme="brand"
              borderRadius="full"
            />
            <Flex justify="space-between" mt={1}>
              <Text fontSize="xs" color="gray.500">
                {(progress.loaded / 1024).toFixed(0)} / {(progress.total / 1024).toFixed(0)} KB
              </Text>
              <Text fontSize="xs" color="gray.500">
                {((progress.loaded / progress.total) * 100).toFixed(0)}%
              </Text>
            </Flex>
          </Box>
        )}
      </VStack>
    </Box>
  )
}
