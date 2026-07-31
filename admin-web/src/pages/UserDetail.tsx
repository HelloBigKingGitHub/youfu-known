import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  Flex,
  HStack,
  Heading,
  Spinner,
  Stack,
  Switch,
  Tag,
  Text,
  useDisclosure,
  useToast,
} from '@chakra-ui/react'
import { useEffect, useState } from 'react'
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

export function UserDetail() {
  const { id } = useParams<{ id: string }>()
  const [user, setUser] = useState<AdminUser | null>(null)
  const [flags, setFlags] = useState<FeatureFlag[]>([])
  const [error, setError] = useState<string | null>(null)
  const [pendingToggle, setPendingToggle] =
    useState<{ feature: string; enabled: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const { isOpen, onOpen, onClose } = useDisclosure()
  const toast = useToast()

  useEffect(() => {
    if (!id) return
    void (async () => {
      try {
        const [users, list] = await Promise.all([
          api.listUsers(),
          api.listUserFeatures(id),
        ])
        setUser(users.find((u) => u.id === id) ?? null)
        setFlags(list)
        setError(null)
      } catch (err: unknown) {
        setError(formatApiError(err))
      }
    })()
  }, [id])

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
          邮箱 {user.email || '—'} · 注册 {formatDateTime(user.created_at)}
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
    </Stack>
  )
}
