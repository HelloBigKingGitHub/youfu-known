import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Flex,
  HStack,
  Heading,
  Icon,
  Input,
  InputGroup,
  InputLeftElement,
  Select,
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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FiChevronLeft, FiChevronRight, FiTrash2 } from '../layouts/icons'

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

type RoleFilter = '' | 'admin' | 'member'

// Status filter values (matches the tags rendered in the table).
// - all     : no filter
// - approved: is_approved=true
// - pending : is_approved=false
// - active  : is_active=true
// - inactive: is_active=false
type StatusFilter = 'all' | 'approved' | 'pending' | 'active' | 'inactive'

const PAGE_SIZE = 50

export function UsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [role, setRole] = useState<RoleFilter>('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [offset, setOffset] = useState(0)
  const [pending, setPending] = useState<AdminUser | null>(null)
  const [busy, setBusy] = useState(false)
  const dialog = useDisclosure()
  const toast = useToast()

  // Debounce the search input so we don't spam the backend on every keystroke.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearch(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [searchInput])

  // Reset to first page whenever a filter changes.
  useEffect(() => {
    setOffset(0)
  }, [role, status])

  const load = useCallback(
    async (nextOffset: number) => {
      try {
        const data = await api.listUsers({
          q: search || undefined,
          role: (role || undefined) as 'admin' | 'member' | undefined,
          is_approved:
            status === 'approved'
              ? true
              : status === 'pending'
                ? false
                : undefined,
          is_active:
            status === 'active'
              ? true
              : status === 'inactive'
                ? false
                : undefined,
          limit: PAGE_SIZE,
          offset: nextOffset,
        })
        setUsers(data.items)
        setTotal(data.total)
        setError(null)
      } catch (err: unknown) {
        setError(formatApiError(err))
      }
    },
    [search, role, status],
  )

  useEffect(() => {
    void load(offset)
  }, [load, offset])

  const pageEnd = useMemo(
    () => Math.min(offset + PAGE_SIZE, total),
    [offset, total],
  )

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
      await load(offset)
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

  const canPrev = offset > 0
  const canNext = offset + PAGE_SIZE < total

  return (
    <Stack spacing={6}>
      <Box>
        <Heading fontFamily="heading" color="copper.300" size="lg">
          用户管理
        </Heading>
        <Text mt={1} color="whiteAlpha.600" fontSize="sm">
          搜索 / 筛选 / 分页查看所有用户；批准、封禁、角色变更在右侧用户详情操作。
        </Text>
      </Box>

      <HStack spacing={4} flexWrap="wrap">
        <InputGroup maxW="320px">
          <InputLeftElement pointerEvents="none">
            <Icon as={FiSearchIcon} color="whiteAlpha.500" />
          </InputLeftElement>
          <Input
            placeholder="搜索用户名或邮箱"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            bg="ink.800"
            borderColor="whiteAlpha.200"
            _hover={{ borderColor: 'copper.400' }}
            _focusVisible={{ borderColor: 'signal.300', boxShadow: 'none' }}
            data-testid="users-search-input"
          />
        </InputGroup>

        <Select
          value={role}
          onChange={(e) => setRole(e.target.value as RoleFilter)}
          maxW="160px"
          bg="ink.800"
          borderColor="whiteAlpha.200"
          _hover={{ borderColor: 'copper.400' }}
          aria-label="按角色筛选"
          data-testid="users-role-filter"
        >
          <option value="">全部角色</option>
          <option value="admin">仅管理员</option>
          <option value="member">仅成员</option>
        </Select>

        <Select
          value={status}
          onChange={(e) => setStatus(e.target.value as StatusFilter)}
          maxW="180px"
          bg="ink.800"
          borderColor="whiteAlpha.200"
          _hover={{ borderColor: 'copper.400' }}
          aria-label="按状态筛选"
          data-testid="users-status-filter"
        >
          <option value="all">全部状态</option>
          <option value="approved">已批准</option>
          <option value="pending">待批准</option>
          <option value="active">活跃</option>
          <option value="inactive">已禁用</option>
        </Select>

        <Text color="whiteAlpha.500" fontSize="sm" ml="auto">
          {total === 0
            ? '共 0 人'
            : `共 ${total} 人 · 显示 ${offset + 1}-${pageEnd}`}
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
            {users.length === 0 ? (
              <Tr>
                <Td colSpan={7}>
                  <Text textAlign="center" color="whiteAlpha.500" py={6}>
                    {search || role || status !== 'all'
                      ? '没有匹配的用户'
                      : '暂无用户'}
                  </Text>
                </Td>
              </Tr>
            ) : (
              users.map((u) => (
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

      <HStack justify="flex-end" spacing={2}>
        <Button
          size="sm"
          variant="outline"
          colorScheme="copper"
          isDisabled={!canPrev}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          leftIcon={<Icon as={FiChevronLeft} boxSize={4} />}
          data-testid="users-prev-page"
        >
          上一页
        </Button>
        <Button
          size="sm"
          variant="outline"
          colorScheme="copper"
          isDisabled={!canNext}
          onClick={() => setOffset(offset + PAGE_SIZE)}
          rightIcon={<Icon as={FiChevronRight} boxSize={4} />}
          data-testid="users-next-page"
        >
          下一页
        </Button>
      </HStack>

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
