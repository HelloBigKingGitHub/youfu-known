import {
  Alert,
  AlertIcon,
  Box,
  Button,
  ButtonGroup,
  Card,
  CardBody,
  CardHeader,
  Flex,
  HStack,
  Heading,
  SimpleGrid,
  Spinner,
  Stack,
  Stat,
  StatLabel,
  StatNumber,
  Switch,
  Tag,
  Text,
  useDisclosure,
  useToast,
} from '@chakra-ui/react'
import { useCallback, useEffect, useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import { api, formatApiError } from '../api'
import type { AdminUser, FeatureFlag } from '../api'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { formatDateTime } from '../lib/format'

interface FeatureDef {
  id: string
  label: string
  desc: string
  defaultEnabled: boolean
}

const FEATURE_DEFS: readonly FeatureDef[] = [
  {
    id: 'kb_chat',
    label: '知识库问答 (KB Chat)',
    desc: '跟 KB 聊天 — 检索 + LLM 答案',
    defaultEnabled: false,
  },
  {
    id: 'kb_create',
    label: '创建知识库',
    desc: '允许创建 / 删除 KB',
    defaultEnabled: false,
  },
  {
    id: 'doc_upload',
    label: '上传文档',
    desc: '允许上传 PDF / Word / MD 到 KB',
    defaultEnabled: false,
  },
  {
    id: 'doc_delete',
    label: '删除文档',
    desc: '允许删除已上传文档',
    defaultEnabled: false,
  },
  {
    id: 'chat_history',
    label: '历史会话',
    desc: '允许查看 / 搜索历史问答',
    defaultEnabled: true,
  },
]

interface UserStats {
  user_id: string
  kb_count: number
  doc_count: number
  chat_count: number
}

export function UserDetail() {
  const { id } = useParams<{ id: string }>()
  const [user, setUser] = useState<AdminUser | null>(null)
  const [flags, setFlags] = useState<FeatureFlag[]>([])
  const [stats, setStats] = useState<UserStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingToggle, setPendingToggle] =
    useState<{ feature: string; enabled: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const [approving, setApproving] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [me, setMe] = useState<AdminUser | null>(null)
  const { isOpen, onOpen, onClose } = useDisclosure()
  const rejectDialog = useDisclosure()
  const toast = useToast()

  // The current admin (so we can disable the self-reject button per
  // the Phase 2.0 spec — an admin must not be able to revoke their own
  // approval and lose access to the panel).
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const m = await api.me()
        if (!cancelled) setMe(m)
      } catch {
        // Non-fatal: the only thing that depends on `me` is the
        // self-reject guard.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const reload = useCallback(async () => {
    if (!id) return
    try {
      const list = await api.listUsers({ limit: 200 })
      const found = list.items.find((u) => u.id === id) ?? null
      setUser(found)
      const [featureList, userStats] = await Promise.all([
        api.listUserFeatures(id),
        api.getUserStats(id).catch(() => null),
      ])
      setFlags(featureList)
      setStats(userStats)
      setError(null)
    } catch (err: unknown) {
      setError(formatApiError(err))
    }
  }, [id])

  useEffect(() => {
    void reload()
  }, [reload])

  const flagFor = (feature: string): boolean | undefined =>
    flags.find((f) => f.feature === feature)?.enabled

  const handleToggleRequest = (feature: string, enabled: boolean) => {
    setPendingToggle({ feature, enabled })
    onOpen()
  }

  const handleToggleConfirm = async () => {
    if (!pendingToggle || !id) return
    setBusy(true)
    try {
      await api.updateUserFeature(
        id,
        pendingToggle.feature,
        pendingToggle.enabled,
      )
      const updated = await api.listUserFeatures(id)
      setFlags(updated)
      toast({
        title: '功能开关已更新',
        description: pendingToggle.feature,
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
      onClose()
      setPendingToggle(null)
    } catch (err: unknown) {
      toast({
        title: '更新失败',
        description: formatApiError(err),
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setBusy(false)
    }
  }

  const handleDismiss = () => {
    if (busy) return
    onClose()
    setPendingToggle(null)
  }

  const handleApprove = async () => {
    if (!id) return
    setApproving(true)
    try {
      const updated = await api.updateUser(id, { is_approved: true })
      setUser(updated)
      // Feature flags reconcile server-side; refresh the local list so
      // the toggle cards reflect the new effective state.
      const refreshed = await api.listUserFeatures(id)
      setFlags(refreshed)
      toast({
        title: '已批准',
        description: `用户 ${updated.username} 已批准`,
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
    } catch (err: unknown) {
      toast({
        title: '批准失败',
        description: formatApiError(err),
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setApproving(false)
    }
  }

  const openReject = () => {
    rejectDialog.onOpen()
  }

  const handleRejectConfirm = async () => {
    if (!id) return
    setRejecting(true)
    try {
      const updated = await api.updateUser(id, { is_approved: false })
      setUser(updated)
      const refreshed = await api.listUserFeatures(id)
      setFlags(refreshed)
      toast({
        title: '已撤销批准',
        description: `用户 ${updated.username} 已撤销批准`,
        status: 'info',
        duration: 3000,
        isClosable: true,
      })
      rejectDialog.onClose()
    } catch (err: unknown) {
      toast({
        title: '撤销失败',
        description: formatApiError(err),
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setRejecting(false)
    }
  }

  const handleRejectDismiss = () => {
    if (rejecting) return
    rejectDialog.onClose()
  }

  if (error) {
    return (
      <Alert status="error" variant="left-accent">
        <AlertIcon />
        <Text>{error}</Text>
      </Alert>
    )
  }

  if (!user) {
    return (
      <Flex h="60vh" align="center" justify="center">
        <Spinner color="signal.400" size="lg" />
      </Flex>
    )
  }

  const isAdmin = user.role === 'admin'
  const isSelf = me !== null && me.id === user.id
  const canReject = !isSelf // admins cannot reject themselves

  const confirmBody = pendingToggle
    ? `确定要为用户「${user.username}」${
        pendingToggle.enabled ? '启用' : '禁用'
      }功能「${
        FEATURE_DEFS.find((d) => d.id === pendingToggle.feature)?.label ??
        pendingToggle.feature
      }」？`
    : ''

  return (
    <Stack spacing={6}>
      <Box>
        <HStack spacing={3} mb={1}>
          <Heading fontFamily="heading" color="copper.300" size="lg">
            用户详情 · {user.username}
          </Heading>
          <Tag
            size="sm"
            colorScheme={isAdmin ? 'purple' : 'gray'}
            variant="subtle"
          >
            {isAdmin ? '管理员' : '成员'}
          </Tag>
          {user.is_approved ? (
            <Tag size="sm" colorScheme="green" variant="subtle">
              已批准
            </Tag>
          ) : (
            <Tag size="sm" colorScheme="yellow" variant="subtle">
              待批准
            </Tag>
          )}
          {!user.is_active && (
            <Tag size="sm" colorScheme="red" variant="subtle">
              已禁用
            </Tag>
          )}
        </HStack>
        <Text color="whiteAlpha.600" fontSize="sm">
          邮箱 {user.email || '—'} · 注册 {formatDateTime(user.created_at)} ·{' '}
          最近登录 {formatDateTime(user.last_login_at)}
        </Text>
      </Box>

      <Box>
        <Button
          as={RouterLink}
          to="/admin/users"
          size="sm"
          variant="ghost"
          colorScheme="copper"
        >
          ← 返回用户列表
        </Button>
      </Box>

      {/* Approval controls + stats cards */}
      <SimpleGrid columns={{ base: 1, md: 4 }} spacing={4}>
        <Stat
          bg="ink.900"
          borderColor="whiteAlpha.100"
          borderWidth="1px"
          borderRadius="lg"
          px={5}
          py={4}
        >
          <StatLabel color="whiteAlpha.600" fontSize="xs">
            知识库
          </StatLabel>
          <StatNumber color="copper.300" fontFamily="heading">
            {stats?.kb_count ?? '—'}
          </StatNumber>
        </Stat>
        <Stat
          bg="ink.900"
          borderColor="whiteAlpha.100"
          borderWidth="1px"
          borderRadius="lg"
          px={5}
          py={4}
        >
          <StatLabel color="whiteAlpha.600" fontSize="xs">
            文档
          </StatLabel>
          <StatNumber color="copper.300" fontFamily="heading">
            {stats?.doc_count ?? '—'}
          </StatNumber>
        </Stat>
        <Stat
          bg="ink.900"
          borderColor="whiteAlpha.100"
          borderWidth="1px"
          borderRadius="lg"
          px={5}
          py={4}
        >
          <StatLabel color="whiteAlpha.600" fontSize="xs">
            问答记录
          </StatLabel>
          <StatNumber color="copper.300" fontFamily="heading">
            {stats?.chat_count ?? '—'}
          </StatNumber>
        </Stat>
        <Card
          bg="ink.900"
          borderColor="whiteAlpha.100"
          borderWidth="1px"
          data-testid="user-detail-approval-card"
        >
          <CardHeader pb={2}>
            <Heading size="sm" color="whiteAlpha.900">
              审批
            </Heading>
          </CardHeader>
          <CardBody pt={0}>
            <ButtonGroup size="sm" isAttached variant="outline">
              <Button
                colorScheme="green"
                isLoading={approving}
                isDisabled={approving || rejecting || user.is_approved}
                onClick={handleApprove}
                data-testid="user-detail-approve-btn"
              >
                {user.is_approved ? '已批准' : '批准'}
              </Button>
              <Button
                colorScheme="red"
                isLoading={rejecting}
                isDisabled={!user.is_approved || rejecting || !canReject}
                onClick={openReject}
                title={
                  canReject
                    ? undefined
                    : '不能撤销自己的批准，否则将失去后台访问权限'
                }
                data-testid="user-detail-reject-btn"
              >
                撤销批准
              </Button>
            </ButtonGroup>
            {!canReject && (
              <Text mt={2} fontSize="xs" color="whiteAlpha.500">
                不能撤销自己的批准（避免失去后台访问权限）。
              </Text>
            )}
          </CardBody>
        </Card>
      </SimpleGrid>

      <Stack spacing={4}>
        {FEATURE_DEFS.map((def) => {
          const override = flagFor(def.id)
          const effective = isAdmin ? true : (override ?? def.defaultEnabled)
          const hasOverride = override !== undefined && !isAdmin
          return (
            <Card
              key={def.id}
              bg="ink.900"
              borderColor="whiteAlpha.100"
              borderWidth="1px"
            >
              <CardHeader pb={2}>
                <HStack justify="space-between" align="flex-start">
                  <Box>
                    <Heading size="sm" color="whiteAlpha.900">
                      {def.label}
                    </Heading>
                    <Text fontSize="sm" color="whiteAlpha.600" mt={1}>
                      {def.desc}
                    </Text>
                  </Box>
                  <Switch
                    isChecked={effective}
                    isDisabled={isAdmin}
                    onChange={(e) =>
                      handleToggleRequest(def.id, e.target.checked)
                    }
                    colorScheme="signal"
                    size="md"
                  />
                </HStack>
              </CardHeader>
              <CardBody pt={0}>
                <HStack spacing={2}>
                  <Tag
                    size="sm"
                    colorScheme={effective ? 'green' : 'gray'}
                    variant="subtle"
                  >
                    {effective ? '已启用' : '已禁用'}
                  </Tag>
                  {isAdmin && (
                    <Text fontSize="xs" color="purple.300">
                      管理员自动启用，无法关闭
                    </Text>
                  )}
                  {!isAdmin && hasOverride && (
                    <Text fontSize="xs" color="whiteAlpha.500">
                      已覆盖默认值
                    </Text>
                  )}
                  {!isAdmin && !hasOverride && (
                    <Text fontSize="xs" color="whiteAlpha.500">
                      默认 {def.defaultEnabled ? '启用' : '关闭'}
                    </Text>
                  )}
                </HStack>
              </CardBody>
            </Card>
          )
        })}
      </Stack>

      <ConfirmDialog
        isOpen={isOpen}
        onClose={handleDismiss}
        onConfirm={handleToggleConfirm}
        title="切换功能开关"
        body={confirmBody}
        confirmLabel={pendingToggle?.enabled ? '启用' : '禁用'}
        isLoading={busy}
      />

      <ConfirmDialog
        isOpen={rejectDialog.isOpen}
        onClose={handleRejectDismiss}
        onConfirm={handleRejectConfirm}
        title="撤销批准"
        body={
          canReject
            ? `撤销对「${user.username}」的批准？其所有功能开关将被关闭，需重新批准才能恢复。`
            : '不能撤销自己的批准。'
        }
        confirmLabel="撤销"
        isLoading={rejecting}
      />
    </Stack>
  )
}
