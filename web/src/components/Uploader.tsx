// 拖拽上传 + 整块可点击
// 现代 SaaS 风格: 圆角大, dashed 边框, 居中布局, 整块点击 + 拖拽
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
import { useRef, useState } from 'react'
import { api, ApiError } from '../api'

interface Props {
  kbId: string
  onUploaded: () => void
}

const ACCEPT = '.pdf,.docx,.md,.txt,.html,.htm'

export function Uploader({ kbId, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState({ loaded: 0, total: 0 })
  const toast = useToast()

  const openPicker = () => {
    if (!uploading) inputRef.current?.click()
  }

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const list = Array.from(files)
    setUploading(true)
    setProgress({ loaded: 0, total: list.reduce((s, f) => s + f.size, 0) })
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
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '上传失败'
      toast({ title: '上传失败', description: msg, status: 'error', duration: 5000 })
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
