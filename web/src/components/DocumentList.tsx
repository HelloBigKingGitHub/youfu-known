// 文档列表 - 响应式: 桌面表格, 移动端卡片
import {
  Badge,
  Box,
  Button,
  Flex,
  HStack,
  Heading,
  IconButton,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
  VStack,
  useBreakpointValue,
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

// 复用状态徽章
function StatusBadge({ status, error }: { status: DocumentStatus; error: string }) {
  if (status === 'processing' || status === 'pending') {
    return (
      <HStack spacing={2}>
        <Spinner size="xs" color="blue.500" />
        <Badge colorScheme={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Badge>
      </HStack>
    )
  }
  return (
    <Tooltip label={error || ''} isDisabled={!error} placement="top">
      <Badge colorScheme={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Badge>
    </Tooltip>
  )
}

// 移动端卡片
function DocCard({ doc, onDelete, onRefresh }: { doc: Document; onDelete: (d: Document) => void; onRefresh: () => void }) {
  return (
    <Box
      bg="white"
      borderRadius="md"
      border="1px"
      borderColor="gray.200"
      p={3}
      mb={2}
    >
      <Flex justify="space-between" align="start" gap={2}>
        <Box flex={1} minW={0}>
          <Heading size="sm" noOfLines={1} mb={1}>
            {doc.filename}
          </Heading>
          <HStack spacing={3} fontSize="xs" color="gray.500" flexWrap="wrap">
            <Text>大小: {formatSize(doc.size_bytes)}</Text>
            <Text>chunks: {doc.chunk_count}</Text>
          </HStack>
          <Box mt={2}>
            <StatusBadge status={doc.status} error={doc.error} />
          </Box>
        </Box>
        <VStack spacing={1}>
          <Tooltip label="刷新状态" placement="left">
            <IconButton
              size="sm"
              variant="ghost"
              onClick={onRefresh}
              aria-label="刷新"
              icon={<RepeatIcon />}
              minW="44px"
              minH="44px"
            />
          </Tooltip>
          <Tooltip label="删除文档" placement="left">
            <IconButton
              size="sm"
              variant="ghost"
              colorScheme="red"
              onClick={() => onDelete(doc)}
              aria-label="删除"
              icon={<DeleteIcon />}
              minW="44px"
              minH="44px"
            />
          </Tooltip>
        </VStack>
      </Flex>
    </Box>
  )
}

export function DocumentList({ kbId, documents, onChange }: Props) {
  const toast = useToast()
  const pollRef = useRef<number | null>(null)
  const isMobile = useBreakpointValue({ base: true, md: false })

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

  // 移动端: 卡片列表
  if (isMobile) {
    return (
      <Box>
        <VStack align="stretch" spacing={0}>
          {documents.map((doc) => (
            <DocCard
              key={doc.id}
              doc={doc}
              onDelete={handleDelete}
              onRefresh={onChange}
            />
          ))}
        </VStack>
        <Flex px={2} py={2} fontSize="xs" color="gray.400">
          处理中 / 等待中的文档每 2 秒自动刷新状态
        </Flex>
      </Box>
    )
  }

  // 桌面 / 平板: 表格
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
                <StatusBadge status={doc.status} error={doc.error} />
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
