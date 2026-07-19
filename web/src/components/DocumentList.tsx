// 文档表格 + 状态轮询 + 删除
import {
  Badge,
  Box,
  Button,
  Flex,
  HStack,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
  useToast,
} from '@chakra-ui/react'
import { DeleteIcon, RepeatIcon } from '@chakra-ui/icons'
import { useEffect, useRef } from 'react'
import type { Document, DocumentStatus } from '../types'
import { api, ApiError } from '../api'

interface Props {
  kbId: string
  documents: Document[]
  onChange: () => void
}

const STATUS_COLOR: Record<DocumentStatus, string> = {
  pending: 'gray',
  processing: 'blue',
  ready: 'green',
  failed: 'red',
}

const STATUS_LABEL: Record<DocumentStatus, string> = {
  pending: '等待',
  processing: '处理中',
  ready: '就绪',
  failed: '失败',
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

export function DocumentList({ kbId, documents, onChange }: Props) {
  const toast = useToast()
  const pollRef = useRef<number | null>(null)

  // 自动轮询: 任何 pending/processing 文档, 每 2s 刷一次
  useEffect(() => {
    const hasActive = documents.some(
      (d) => d.status === 'pending' || d.status === 'processing',
    )
    if (!hasActive) {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }
    pollRef.current = window.setInterval(() => {
      onChange()
    }, 2000)
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [documents, onChange])

  const handleDelete = async (doc: Document) => {
    if (!window.confirm(`确定删除文档 "${doc.filename}"? 这会同时移除其所有 chunks。`)) {
      return
    }
    try {
      await api.deleteDocument(kbId, doc.id)
      toast({ title: '文档已删除', status: 'success', duration: 2000 })
      onChange()
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '删除失败'
      toast({ title: '删除失败', description: msg, status: 'error', duration: 4000 })
    }
  }

  if (documents.length === 0) {
    return (
      <Box bg="white" borderRadius="md" border="1px" borderColor="gray.200" p={6}>
        <Text color="gray.500" textAlign="center">
          还没有文档, 拖文件到上方上传区或点按钮选文件
        </Text>
      </Box>
    )
  }

  return (
    <Box bg="white" borderRadius="md" border="1px" borderColor="gray.200" overflowX="auto">
      <Table size="sm" variant="simple">
        <Thead bg="gray.50">
          <Tr>
            <Th>文件名</Th>
            <Th isNumeric>大小</Th>
            <Th>状态</Th>
            <Th isNumeric>chunks</Th>
            <Th>操作</Th>
          </Tr>
        </Thead>
        <Tbody>
          {documents.map((doc) => (
            <Tr key={doc.id}>
              <Td>
                <Text fontSize="sm" noOfLines={1} maxW="300px">
                  {doc.filename}
                </Text>
              </Td>
              <Td isNumeric>
                <Text fontSize="sm" color="gray.600">
                  {formatSize(doc.size_bytes)}
                </Text>
              </Td>
              <Td>
                {doc.status === 'processing' || doc.status === 'pending' ? (
                  <HStack spacing={2}>
                    <Spinner size="xs" color="blue.500" />
                    <Badge colorScheme={STATUS_COLOR[doc.status]}>
                      {STATUS_LABEL[doc.status]}
                    </Badge>
                  </HStack>
                ) : (
                  <Tooltip
                    label={doc.error || ''}
                    isDisabled={!doc.error}
                    placement="top"
                  >
                    <Badge colorScheme={STATUS_COLOR[doc.status]}>
                      {STATUS_LABEL[doc.status]}
                    </Badge>
                  </Tooltip>
                )}
              </Td>
              <Td isNumeric>
                <Text fontSize="sm" color="gray.600">
                  {doc.chunk_count}
                </Text>
              </Td>
              <Td>
                <HStack spacing={1}>
                  <Tooltip label="刷新状态" placement="top">
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={onChange}
                      aria-label="刷新"
                    >
                      <RepeatIcon />
                    </Button>
                  </Tooltip>
                  <Tooltip label="删除文档" placement="top">
                    <Button
                      size="xs"
                      variant="ghost"
                      colorScheme="red"
                      onClick={() => handleDelete(doc)}
                      aria-label="删除"
                    >
                      <DeleteIcon />
                    </Button>
                  </Tooltip>
                </HStack>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
      <Flex px={4} py={2} fontSize="xs" color="gray.400" borderTop="1px" borderColor="gray.100">
        处理中 / 等待中的文档每 2 秒自动刷新状态
      </Flex>
    </Box>
  )
}