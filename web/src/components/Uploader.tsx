// 拖拽上传 + 按钮选文件
import { Box, Button, Flex, HStack, Icon, Progress, Text, useToast, VStack } from '@chakra-ui/react'
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
      borderRadius="md"
      border="2px dashed"
      borderColor={dragOver ? 'brand.500' : 'gray.300'}
      bg={dragOver ? 'brand.50' : 'white'}
      p={5}
      transition="all 0.15s"
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        handleFiles(e.dataTransfer.files)
      }}
    >
      <VStack spacing={3}>
        <Icon as={AttachmentIcon} boxSize={6} color={dragOver ? 'brand.500' : 'gray.400'} />
        <Text fontSize="sm" color={dragOver ? 'brand.700' : 'gray.600'}>
          {dragOver ? '松开以上传' : '拖文件到这里, 或点按钮选文件'}
        </Text>
        <Text fontSize="xs" color="gray.400">
          支持 PDF / Word / Markdown / TXT / HTML
        </Text>
        <HStack>
          <Button
            size="sm"
            colorScheme="brand"
            onClick={() => inputRef.current?.click()}
            isLoading={uploading}
            loadingText="上传中"
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
        </HStack>
        {uploading && progress.total > 0 && (
          <Box w="100%">
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