import {
  Alert,
  AlertIcon,
  Box,
  Flex,
  HStack,
  Heading,
  Icon,
  Input,
  InputGroup,
  InputLeftElement,
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
import { useEffect, useMemo, useState } from 'react'
import { FiTrash2 } from '../layouts/icons'

// Inline search icon — mirrors the FiSearch pattern from layouts/icons
// without modifying the shared icon module.
function FiSearchIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      width="1em"
      height="1em"
      {...props}
    >
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}
import { api, formatApiError } from '../api'
import type { AdminUser } from '../api'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { formatDateTime } from '../lib/format'

export function UsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [pending, setPending] = useState<AdminUser | null>(null)
  const [busy, setBusy] = useState(false)
  const dialog = useDisclosure()
  const toast = useToast()

  const reload = async () => {
    try {
      const data = await api.listUsers()
      setUsers(data)
      setError(null)
    } catch (err: unknown) {
      setError(formatApiError(err))
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  const filtered = useMemo(() => {
    if (!users) return []
    if (!search.trim()) return users
    const q = search.trim().toLowerCase()
    return users.filter(
      (u) =>
        u.username.toLowerCase().includes(q) ||
        (u.email || '').toLowerCase().includes(q),
    )
  }, [users, search])

  const handleDelete = async () => {
    if (!pending) return
    setBusy(true)
    try {
      await api.deleteUser(pending.id)
      toast({
        title: '已删除',
        description: `用户 ${pending.username} 已删除`,
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

  if (!users) {
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
          用户管理
        </Heading>
        <Text mt={1} color="whiteAlpha.600" fontSize="sm">
          查看所有注册用户并执行删除操作；角色与审批流调整留待 Phase 2。
        </Text>
      </Box>
      <HStack justify="space-between">
        <InputGroup maxW="320px">
          <InputLeftElement pointerEvents="none">
            <Icon as={FiSearchIcon} color="whiteAlpha.500" />
          </InputLeftElement>
          <Input
            placeholder="搜索用户名或邮箱"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            bg="ink.800"
            borderColor="whiteAlpha.200"
            _hover={{ borderColor: 'copper.400' }}
            _focusVisible={{ borderColor: 'signal.300', boxShadow: 'none' }}
          />
        </InputGroup>
        <Text color="whiteAlpha.500" fontSize="sm">
          共 {filtered.length} / {users.length} 人
        </Text>
      </HStack>
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
              <Th>用户名</Th>
              <Th>邮箱</Th>
              <Th>角色</Th>
              <Th>状态</Th>
              <Th>最近登录</Th>
              <Th>注册时间</Th>
              <Th>操作</Th>
            </Tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr>
                <Td colSpan={7}>
                  <Text textAlign="center" color="whiteAlpha.500" py={6}>
                    {search ? '没有匹配的用户' : '暂无用户'}
                  </Text>
                </Td>
              </Tr>
            ) : (
              filtered.map((u) => (
                <Tr key={u.id} _hover={{ bg: 'whiteAlpha.50' }}>
                  <Td>
                    <Text fontFamily="heading" color="copper.300">{u.username}</Text>
                  </Td>
                  <Td>
                    <Text color="whiteAlpha.800" fontSize="sm">{u.email || '—'}</Text>
                  </Td>
                  <Td>
                    <Tag
                      size="sm"
                      colorScheme={u.role === 'admin' ? 'purple' : 'gray'}
                      variant="subtle"
                    >
                      {u.role === 'admin' ? '管理员' : '成员'}
                    </Tag>
                  </Td>
                  <Td>
                    <HStack spacing={1}>
                      {u.is_approved ? (
                        <Tag size="sm" colorScheme="green" variant="subtle">
                          已批准
                        </Tag>
                      ) : (
                        <Tag size="sm" colorScheme="yellow" variant="subtle">
                          待批准
                        </Tag>
                      )}
                      {!u.is_active && (
                        <Tag size="sm" colorScheme="red" variant="subtle">
                          已禁用
                        </Tag>
                      )}
                    </HStack>
                  </Td>
                  <Td>
                    <Text color="whiteAlpha.700" fontSize="sm">{formatDateTime(u.last_login_at)}</Text>
                  </Td>
                  <Td>
                    <Text color="whiteAlpha.700" fontSize="sm">{formatDateTime(u.created_at)}</Text>
                  </Td>
                  <Td>
                    <HStack spacing={2}>
                      {u.role === 'admin' && (
                        <Tag size="sm" colorScheme="purple" variant="outline">
                          保留
                        </Tag>
                      )}
                      <Box
                        as="button"
                        aria-label={`删除用户 ${u.username}`}
                        onClick={() => {
                          if (u.role === 'admin') return
                          setPending(u)
                          dialog.onOpen()
                        }}
                        cursor={u.role === 'admin' ? 'not-allowed' : 'pointer'}
                        opacity={u.role === 'admin' ? 0.4 : 1}
                        color="red.300"
                        _hover={u.role === 'admin' ? undefined : { color: 'red.200' }}
                        px={2}
                        py={1}
                        borderRadius="md"
                        display="inline-flex"
                        alignItems="center"
                        gap={1}
                      >
                        <Icon as={FiTrash2} boxSize={4} />
                        <Text fontSize="sm">删除</Text>
                      </Box>
                    </HStack>
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
        title="删除用户"
        body={
          pending
            ? `确认删除用户「${pending.username}」？其知识库、文档与向量将被永久删除，此操作不可撤销。`
            : ''
        }
        confirmLabel="删除"
        isLoading={busy}
      />
    </Stack>
  )
}