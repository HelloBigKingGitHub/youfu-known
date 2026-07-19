// 文档列表 - 现代 SaaS 风格
// 桌面 / 平板: 表格 + pill 状态徽章 (带前导圆点/旋转图标)
// 移动端: 卡片列表
import {
  Badge,
  Box,
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

// 状态视觉 (圆点 + pill 徽章)
const STATUS_STYLES: Record<
  DocumentStatus,
  { dotColor: string; bg: string; color: string; label: string }
> = {
  pending: {
    dotColor: 'gray.400',
    bg: 'gray.100',
    color: 'gray.600',
    label: '等待',
  },
  processing: {
    dotColor: 'blue.500',
    bg: 'blue.50',
    color: 'blue.600',
    label: '处理中',
  },
  ready: {
    dotColor: 'green.500',
    bg: 'green.50',
    color: 'green.600',
    label: '就绪',
  },
  failed: {
    dotColor: 'red.500',
    bg: 'red.50',
    color: 'red.600',
    label: '失败',
  },
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

// 状态徽章: 前导圆点 / spinner + pill 文字
function StatusBadge({ status, error }: { status: DocumentStatus; error: string }) {
  const s = STATUS_STYLES[status]
  const isActive = status === 'processing' || status === 'pending'
  const badge = (
    <Badge
      px={2}
      py={1}
      borderRadius="full"
      bg={s.bg}
      color={s.color}
      fontWeight="medium"
      fontSize="xs"
      display="inline-flex"
      alignItems="center"
      gap={1.5}
    >
      {isActive ? (
        <Spinner size="xs" color={s.dotColor} speed="0.8s" />
      ) : (
        <Box w={1.5} h={1.5} borderRadius="full" bg={s.dotColor} />
      )}
      {s.label}
    </Badge>
  )
  if (status === 'failed' && error) {
    return (
      <Tooltip label={error} placement="top" hasArrow>
        {badge}
      </Tooltip>
    )
  }
  return badge
}

// 移动端卡片
function DocCard({
  doc,
  onDelete,
  onRefresh,
}: {
  doc: Document
  onDelete: (d: Document) => void
  onRefresh: () => void
}) {
  return (
    <Box
      bg="white"
      borderRadius="xl"
      border="1px"
      borderColor="surface.border"
      p={3}
      mb={2}
      boxShadow="xs"
      transition="all 0.15s"
      _hover={{ boxShadow: 'sm', borderColor: 'brand.200' }}
    >
      <Flex justify="space-between" align="start" gap={2}>
        <Box flex={1} minW={0}>
          <Heading size="sm" noOfLines={1} mb={1.5}>
            {doc.filename}
          </Heading>
          <HStack spacing={3} fontSize="xs" color="gray.500" flexWrap="wrap" mb={2}>
            <Text>{formatSize(doc.size_bytes)}</Text>
            <Text>·</Text>
            <Text>{doc.chunk_count} chunks</Text>
          </HStack>
          <StatusBadge status={doc.status} error={doc.error} />
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
              color="gray.500"
              _hover={{ color: 'brand.600', bg: 'brand.50' }}
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
      <Box
        bg="white"
        borderRadius="xl"
        border="1px dashed"
        borderColor="surface.border"
        p={6}
        textAlign="center"
      >
        <Text color="gray.500" fontSize="sm">
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
    <Box
      bg="white"
      borderRadius="xl"
      border="1px"
      borderColor="surface.border"
      boxShadow="sm"
      overflow="hidden"
    >
      <Table size="sm" variant="simple">
        <Thead bg="surface.sunken">
          <Tr>
            <Th borderColor="surface.border" color="gray.600" fontWeight="semibold">
              文件名
            </Th>
            <Th isNumeric borderColor="surface.border" color="gray.600" fontWeight="semibold">
              大小
            </Th>
            <Th borderColor="surface.border" color="gray.600" fontWeight="semibold">
              状态
            </Th>
            <Th isNumeric borderColor="surface.border" color="gray.600" fontWeight="semibold">
              chunks
            </Th>
            <Th borderColor="surface.border" color="gray.600" fontWeight="semibold">
              操作
            </Th>
          </Tr>
        </Thead>
        <Tbody>
          {documents.map((doc) => (
            <Tr
              key={doc.id}
              transition="background 0.15s"
              _hover={{ bg: 'surface.sunken' }}
            >
              <Td borderColor="surface.border">
                <Text fontSize="sm" noOfLines={1} maxW="300px" fontWeight="medium">
                  {doc.filename}
                </Text>
              </Td>
              <Td isNumeric borderColor="surface.border">
                <Text fontSize="sm" color="gray.600">
                  {formatSize(doc.size_bytes)}
                </Text>
              </Td>
              <Td borderColor="surface.border">
                <StatusBadge status={doc.status} error={doc.error} />
              </Td>
              <Td isNumeric borderColor="surface.border">
                <Text fontSize="sm" color="gray.600">
                  {doc.chunk_count}
                </Text>
              </Td>
              <Td borderColor="surface.border">
                <HStack spacing={1}>
                  <Tooltip label="刷新状态" placement="top">
                    <IconButton
                      size="xs"
                      variant="ghost"
                      onClick={onChange}
                      aria-label="刷新"
                      icon={<RepeatIcon />}
                      minW="32px"
                      minH="32px"
                      color="gray.500"
                      _hover={{ color: 'brand.600', bg: 'brand.50' }}
                    />
                  </Tooltip>
                  <Tooltip label="删除文档" placement="top">
                    <IconButton
                      size="xs"
                      variant="ghost"
                      colorScheme="red"
                      onClick={() => handleDelete(doc)}
                      aria-label="删除"
                      icon={<DeleteIcon />}
                      minW="32px"
                      minH="32px"
                    />
                  </Tooltip>
                </HStack>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
      <Flex
        px={4}
        py={2}
        fontSize="xs"
        color="gray.400"
        borderTop="1px"
        borderColor="surface.border"
        bg="surface.sunken"
      >
        处理中 / 等待中的文档每 2 秒自动刷新状态
      </Flex>
    </Box>
  )
}
