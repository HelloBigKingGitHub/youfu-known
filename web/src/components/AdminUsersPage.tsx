// Admin 用户管理页 - 列表 / 搜索 / 批准 / 改角色 / 启用禁用 / 删除
import {
  Badge,
  Box,
  Button,
  Heading,
  HStack,
  Input,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useToast,
} from '@chakra-ui/react'
import { useEffect, useMemo, useState } from 'react'
import { api, ApiError, USER_STORAGE_KEY } from '../api'
import type { User } from '../types'

export function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const toast = useToast()

  const currentUser = useMemo<User | null>(() => {
    const raw = localStorage.getItem(USER_STORAGE_KEY)
    if (!raw) return null
    try {
      return JSON.parse(raw) as User
    } catch {
      return null
    }
  }, [])

  const loadUsers = async () => {
    setLoading(true)
    try {
      const list = await api.adminListUsers()
      setUsers(list)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '加载失败'
      toast({ title: '加载失败', description: msg, status: 'error', duration: 4000 })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadUsers()
  }, [])

  const filtered = users.filter(
    (u) =>
      u.username.toLowerCase().includes(search.toLowerCase()) ||
      (u.email || '').toLowerCase().includes(search.toLowerCase()),
  )

  const updateOne = (userId: string, patch: Partial<User>) => {
    setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, ...patch } : u)))
  }

  const handleApprove = async (u: User) => {
    setBusyId(u.id)
    try {
      const updated = await api.adminUpdateUser(u.id, { is_approved: true })
      updateOne(u.id, updated)
      toast({ title: `${u.username} 已批准`, status: 'success', duration: 2000 })
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '操作失败'
      toast({ title: '批准失败', description: msg, status: 'error', duration: 3000 })
    } finally {
      setBusyId(null)
    }
  }

  const handleToggleActive = async (u: User) => {
    setBusyId(u.id)
    try {
      const updated = await api.adminUpdateUser(u.id, { is_active: !u.is_active })
      updateOne(u.id, updated)
      toast({
        title: updated.is_active ? `${u.username} 已启用` : `${u.username} 已禁用`,
        status: 'success',
        duration: 2000,
      })
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '操作失败'
      toast({ title: '操作失败', description: msg, status: 'error', duration: 3000 })
    } finally {
      setBusyId(null)
    }
  }

  const handleChangeRole = async (u: User) => {
    const nextRole = u.role === 'admin' ? 'member' : 'admin'
    setBusyId(u.id)
    try {
      const updated = await api.adminUpdateUser(u.id, { role: nextRole })
      updateOne(u.id, updated)
      toast({
        title: `${u.username} 角色已改为 ${updated.role}`,
        status: 'success',
        duration: 2000,
      })
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '操作失败'
      toast({ title: '角色修改失败', description: msg, status: 'error', duration: 3000 })
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async (u: User) => {
    if (!window.confirm(`确定删除用户 ${u.username}? 不可恢复。`)) return
    setBusyId(u.id)
    try {
      await api.adminDeleteUser(u.id)
      setUsers((prev) => prev.filter((x) => x.id !== u.id))
      toast({ title: `${u.username} 已删除`, status: 'success', duration: 2000 })
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '删除失败'
      toast({ title: '删除失败', description: msg, status: 'error', duration: 3000 })
    } finally {
      setBusyId(null)
    }
  }

  const isSelf = (u: User) => u.id === currentUser?.id

  return (
    <Box flex={1} h="100%" overflowY="auto" bg="gray.50">
      <Box maxW="960px" mx="auto" p={{ base: 3, md: 5, lg: 6 }}>
        <Heading size={{ base: 'md', md: 'lg' }} color="gray.900" mb={{ base: 4, md: 6 }}>
          用户管理
        </Heading>

        <Input
          placeholder="搜索用户名或邮箱"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          mb={4}
          bg="white"
        />

        {loading ? (
          <HStack justify="center" py={10} color="gray.500">
            <Spinner size="sm" color="brand.500" />
            <Text>加载中...</Text>
          </HStack>
        ) : filtered.length === 0 ? (
          <Text color="gray.500" py={6}>
            没有匹配的用户
          </Text>
        ) : (
          <Box overflowX="auto" bg="white" borderRadius="md" borderWidth="1px" borderColor="gray.200">
            <Table variant="simple" size="sm" minW="640px">
              <Thead>
                <Tr>
                  <Th>用户名</Th>
                  <Th>邮箱</Th>
                  <Th>角色</Th>
                  <Th>状态</Th>
                  <Th>操作</Th>
                </Tr>
              </Thead>
              <Tbody>
                {filtered.map((u) => (
                  <Tr key={u.id}>
                    <Td>{u.username}</Td>
                    <Td>{u.email || '-'}</Td>
                    <Td>
                      <Badge colorScheme={u.role === 'admin' ? 'purple' : 'gray'}>
                        {u.role}
                      </Badge>
                    </Td>
                    <Td>
                      <HStack spacing={1} flexWrap="wrap">
                        {u.is_approved ? (
                          <Badge colorScheme="green">已批准</Badge>
                        ) : (
                          <Badge colorScheme="yellow">待批准</Badge>
                        )}
                        {!u.is_active && <Badge colorScheme="red">已禁用</Badge>}
                      </HStack>
                    </Td>
                    <Td>
                      <HStack spacing={2} flexWrap="wrap">
                        {!u.is_approved && (
                          <Button
                            size="xs"
                            colorScheme="green"
                            onClick={() => handleApprove(u)}
                            isLoading={busyId === u.id}
                          >
                            批准
                          </Button>
                        )}
                        <Button
                          size="xs"
                          onClick={() => handleToggleActive(u)}
                          isLoading={busyId === u.id}
                          isDisabled={isSelf(u)}
                        >
                          {u.is_active ? '禁用' : '启用'}
                        </Button>
                        <Button
                          size="xs"
                          colorScheme={u.role === 'admin' ? 'gray' : 'purple'}
                          variant="outline"
                          onClick={() => handleChangeRole(u)}
                          isLoading={busyId === u.id}
                          isDisabled={isSelf(u)}
                        >
                          {u.role === 'admin' ? '降为 member' : '提为 admin'}
                        </Button>
                        <Button
                          size="xs"
                          colorScheme="red"
                          variant="ghost"
                          onClick={() => handleDelete(u)}
                          isLoading={busyId === u.id}
                          isDisabled={isSelf(u)}
                        >
                          删除
                        </Button>
                      </HStack>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Box>
        )}
      </Box>
    </Box>
  )
}
