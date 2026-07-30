import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Flex,
  HStack,
  Heading,
  Icon,
  Spinner,
  Stack,
  Table,
  Tag,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useDisclosure,
  useToast,
} from '@chakra-ui/react'
import { useEffect, useState } from 'react'
import { api, formatApiError } from '../api'
import type { AdminKB } from '../api'
import { FiTrash2 } from '../layouts/icons'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { formatDateTime, formatNumber } from '../lib/format'

export function KBsPage() {
  const [kbs, setKbs] = useState<AdminKB[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<AdminKB | null>(null)
  const [busy, setBusy] = useState(false)
  const dialog = useDisclosure()
  const toast = useToast()

  const reload = async () => {
    try {
      const data = await api.listKBs()
      setKbs(data)
      setError(null)
    } catch (err: unknown) {
      setError(formatApiError(err))
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  const handleDelete = async () => {
    if (!pending) return
    setBusy(true)
    try {
      await api.deleteKB(pending.id)
      toast({
        title: '已删除',
        description: `知识库 ${pending.name} 已删除`,
        status: 'success',
        duration: 4000,
        isClosable: true,
      })
      dialog.onClose()
      setPending(null)
      await reload()
    } catch (err: unknown) {
      toast({
        title: '删除失败',
        description: formatApiError(err),
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return (
      <Alert status="error" variant="left-accent">
        <AlertIcon />
        <Text>{error}</Text>
      </Alert>
    )
  }

  if (!kbs) {
    return (
      <Flex h="60vh" align="center" justify="center">
        <Spinner color="signal.400" size="lg" />
      </Flex>
    )
  }

  return (
    <Stack spacing={6}>
      <Box>
        <Heading fontFamily="heading" color="copper.300" size="lg">
          知识库
        </Heading>
        <Text mt={1} color="whiteAlpha.600" fontSize="sm">
          管理所有用户创建的知识库；删除操作不可逆，会移除文档与向量。
        </Text>
      </Box>
      <Box
        bg="ink.900"
        borderWidth="1px"
        borderColor="whiteAlpha.100"
        borderRadius="lg"
        overflow="hidden"
      >
        <Table variant="admin" size="md">
          <Thead>
            <Tr>
              <Th>名称</Th>
              <Th>所有者</Th>
              <Th>可见性</Th>
              <Th isNumeric>文档</Th>
              <Th isNumeric>切片</Th>
              <Th>创建时间</Th>
              <Th>操作</Th>
            </Tr>
          </Thead>
          <Tbody>
            {kbs.length === 0 ? (
              <Tr>
                <Td colSpan={7}>
                  <Text textAlign="center" color="whiteAlpha.500" py={6}>
                    暂无知识库
                  </Text>
                </Td>
              </Tr>
            ) : (
              kbs.map((kb) => (
                <Tr key={kb.id} _hover={{ bg: 'whiteAlpha.50' }}>
                  <Td>
                    <Text fontFamily="heading" color="copper.300">{kb.name}</Text>
                  </Td>
                  <Td>
                    <Text color="whiteAlpha.800">{kb.owner_username || '系统'}</Text>
                  </Td>
                  <Td>
                    <HStack spacing={2}>
                      {kb.is_shared && <Tag size="sm" colorScheme="orange">共享</Tag>}
                      {kb.is_public && <Tag size="sm" colorScheme="purple">公开</Tag>}
                      {!kb.is_shared && !kb.is_public && <Tag size="sm" colorScheme="gray">私有</Tag>}
                    </HStack>
                  </Td>
                  <Td isNumeric>{formatNumber(kb.doc_count)}</Td>
                  <Td isNumeric>{formatNumber(kb.chunk_count)}</Td>
                  <Td>
                    <Text color="whiteAlpha.700" fontSize="sm">{formatDateTime(kb.created_at)}</Text>
                  </Td>
                  <Td>
                    <Button
                      size="sm"
                      variant="ghost"
                      colorScheme="red"
                      leftIcon={<Icon as={FiTrash2} />}
                      onClick={() => {
                        setPending(kb)
                        dialog.onOpen()
                      }}
                    >
                      删除
                    </Button>
                  </Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Box>
      <ConfirmDialog
        isOpen={dialog.isOpen}
        onClose={dialog.onClose}
        onConfirm={handleDelete}
        title="删除知识库"
        body={
          pending
            ? `确认删除知识库「${pending.name}」？文档与向量将被永久删除，此操作不可撤销。`
            : ''
        }
        confirmLabel="删除"
        isLoading={busy}
      />
    </Stack>
  )
}
