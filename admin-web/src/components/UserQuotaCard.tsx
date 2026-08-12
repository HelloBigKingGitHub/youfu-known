// UserDetail 额度 section (Phase 2.1)
//
// 后端 spec:
//   GET  /api/admin/users/{id}/quota        → QuotaInfo
//   POST /api/admin/users/{id}/quota/reset  (admin only)
//   PATCH /api/admin/users/{id}             body 加 quota_tokens_total / quota_period
//
// 视觉:
//   - 概览卡: 已用 / 总额 / 剩余 + 进度条 + 期间/重置时间 + 超额红色 banner
//   - 修改卡: number input + 保存 / period select / 重置按钮 (AlertDialog 确认)
//   - 用量表: 30 天按日 token (日期倒序)
//
// 风格: 跟 UserDetail 的 FEATURE_DEFS Card 风格一致 (ink.900 + copper.300 + whiteAlpha.*)

import {
  Alert,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  AlertIcon,
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  Flex,
  HStack,
  Heading,
  Input,
  Progress,
  Select,
  SimpleGrid,
  Spinner,
  Stack,
  Stat,
  StatLabel,
  StatNumber,
  Table,
  TableContainer,
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
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, formatApiError } from '../api'
import type { QuotaInfo, QuotaPeriod } from '../api'
import { formatDateTime } from '../lib/format'

const PERIOD_LABEL: Record<QuotaPeriod, string> = {
  monthly: '按月',
  weekly: '按周',
  daily: '按日',
  none: '不限',
}

const PERIOD_OPTIONS: QuotaPeriod[] = ['monthly', 'weekly', 'daily', 'none']

/** 把 token 数格式化成 K / M, 例如 1.2K / 234K / 1.5M (跟 web/ AccountQuota 对齐) */
function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 100_000 ? 0 : 1)}K`
  return String(n)
}

/** "X 天 / X 小时 / X 分钟后重置" (跟 web/ AccountQuota 对齐) */
function formatResetIn(resetAt: string | null): string {
  if (!resetAt) return ''
  const target = new Date(resetAt).getTime()
  if (Number.isNaN(target)) return ''
  const diffMs = target - Date.now()
  if (diffMs <= 0) return '即将重置'
  const minutes = Math.round(diffMs / 60_000)
  if (minutes < 60) return `${minutes} 分钟后重置`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} 小时后重置`
  const days = Math.round(hours / 24)
  return `${days} 天后重置`
}

interface Props {
  userId: string
  username: string
}

export function UserQuotaCard({ userId, username }: Props) {
  const [quota, setQuota] = useState<QuotaInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [totalInput, setTotalInput] = useState<string>('')
  const [savingTotal, setSavingTotal] = useState(false)
  const [savingPeriod, setSavingPeriod] = useState(false)
  const [resetting, setResetting] = useState(false)
  const toast = useToast()
  const resetDialog = useDisclosure()
  const cancelRef = useRef<HTMLButtonElement>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getUserQuota(userId)
      setQuota(data)
      // sync the number input with the latest server value
      setTotalInput(data.tokens_total > 0 ? String(data.tokens_total) : '0')
    } catch (err: unknown) {
      setError(formatApiError(err))
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void reload()
  }, [reload])

  const handleSaveTotal = async () => {
    if (!userId) return
    const parsed = Number(totalInput)
    if (!Number.isFinite(parsed) || parsed < 0) {
      toast({
        title: '保存失败',
        description: '总额必须是非负数字',
        status: 'error',
        duration: 4000,
        isClosable: true,
      })
      return
    }
    setSavingTotal(true)
    try {
      await api.updateUser(userId, { quota_tokens_total: parsed })
      toast({
        title: '已保存',
        description: `用户 ${username} 的总额已更新为 ${formatTokens(parsed)}`,
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
      await reload()
    } catch (err: unknown) {
      toast({
        title: '保存失败',
        description: formatApiError(err),
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setSavingTotal(false)
    }
  }

  const handlePeriodChange = async (
    e: React.ChangeEvent<HTMLSelectElement>,
  ) => {
    if (!userId) return
    const next = e.target.value as QuotaPeriod
    if (!PERIOD_OPTIONS.includes(next)) return
    setSavingPeriod(true)
    try {
      await api.updateUser(userId, { quota_period: next })
      toast({
        title: '已更新',
        description: `周期已切换为 ${PERIOD_LABEL[next]}`,
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
      await reload()
    } catch (err: unknown) {
      toast({
        title: '更新失败',
        description: formatApiError(err),
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setSavingPeriod(false)
    }
  }

  const openResetDialog = () => {
    if (resetting) return
    resetDialog.onOpen()
  }

  const handleResetConfirm = async () => {
    if (!userId) return
    setResetting(true)
    try {
      await api.resetUserQuota(userId)
      toast({
        title: '已重置',
        description: `用户 ${username} 的已用额度已清零`,
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
      resetDialog.onClose()
      await reload()
    } catch (err: unknown) {
      toast({
        title: '重置失败',
        description: formatApiError(err),
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setResetting(false)
    }
  }

  const handleResetDismiss = () => {
    if (resetting) return
    resetDialog.onClose()
  }

  // ---- loading / error ----
  if (loading && !quota) {
    return (
      <Card
        bg="ink.900"
        borderColor="whiteAlpha.100"
        borderWidth="1px"
        data-testid="quota-tab-content"
      >
        <CardHeader pb={2}>
          <Heading size="sm" color="whiteAlpha.900">
            额度
          </Heading>
        </CardHeader>
        <CardBody>
          <Flex h="120px" align="center" justify="center">
            <Spinner color="signal.400" size="md" />
          </Flex>
        </CardBody>
      </Card>
    )
  }

  if (error && !quota) {
    return (
      <Card
        bg="ink.900"
        borderColor="whiteAlpha.100"
        borderWidth="1px"
        data-testid="quota-tab-content"
      >
        <CardHeader pb={2}>
          <Heading size="sm" color="whiteAlpha.900">
            额度
          </Heading>
        </CardHeader>
        <CardBody>
          <Stack spacing={3}>
            <Alert status="error" variant="left-accent">
              <AlertIcon />
              <Text fontSize="sm">{error}</Text>
            </Alert>
            <Button
              size="sm"
              variant="outline"
              colorScheme="copper"
              onClick={() => void reload()}
              w="fit-content"
            >
              重试
            </Button>
          </Stack>
        </CardBody>
      </Card>
    )
  }

  if (!quota) return null

  // ---- derived state ----
  const isUnlimited = quota.tokens_total === 0
  const remaining = quota.tokens_remaining
  const isExhausted =
    !isUnlimited &&
    (remaining === null ? quota.tokens_used >= quota.tokens_total : remaining <= 0)
  const pct = isUnlimited
    ? 0
    : Math.min(
        100,
        Math.round((quota.tokens_used / Math.max(quota.tokens_total, 1)) * 100),
      )
  const resetIn = formatResetIn(quota.reset_at)
  const breakdown = [...(quota.usage_breakdown ?? [])].sort((a, b) =>
    a.date < b.date ? 1 : a.date > b.date ? -1 : 0,
  )

  return (
    <Box data-testid="quota-tab-content">
      <Stack spacing={4}>
        {/* 超额 banner */}
        {isExhausted && (
          <Alert status="error" variant="left-accent" borderRadius="lg">
            <AlertIcon />
            <Box>
              <Text fontSize="sm" fontWeight="bold">
                额度已用完
                {quota.reset_at ? ` · 重置时间 ${formatDateTime(quota.reset_at)}` : ''}
              </Text>
              <Text fontSize="xs" color="whiteAlpha.700">
                {resetIn
                  ? `${resetIn} 后可继续使用`
                  : '请等待额度重置或联系管理员'}
              </Text>
            </Box>
          </Alert>
        )}

        {/* 概览卡 */}
        <Card bg="ink.900" borderColor="whiteAlpha.100" borderWidth="1px">
          <CardHeader pb={2}>
            <HStack justify="space-between" align="center">
              <Heading size="sm" color="whiteAlpha.900">
                概览
              </Heading>
              <Tag
                size="sm"
                colorScheme={isExhausted ? 'red' : 'green'}
                variant="subtle"
                data-testid="quota-status-tag"
              >
                {isExhausted ? '超额' : '正常'}
              </Tag>
            </HStack>
          </CardHeader>
          <CardBody>
            <Stack spacing={4}>
              <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
                <Stat>
                  <StatLabel color="whiteAlpha.600" fontSize="xs">
                    已用
                  </StatLabel>
                  <StatNumber
                    color="copper.300"
                    fontFamily="heading"
                    data-testid="quota-used-tokens"
                  >
                    {formatTokens(quota.tokens_used)}
                  </StatNumber>
                </Stat>
                <Stat>
                  <StatLabel color="whiteAlpha.600" fontSize="xs">
                    总额
                  </StatLabel>
                  <StatNumber
                    color="whiteAlpha.900"
                    fontFamily="heading"
                    data-testid="quota-total-tokens"
                  >
                    {isUnlimited ? '∞' : formatTokens(quota.tokens_total)}
                  </StatNumber>
                </Stat>
                <Stat>
                  <StatLabel color="whiteAlpha.600" fontSize="xs">
                    剩余
                  </StatLabel>
                  <StatNumber
                    color={isExhausted ? 'red.300' : 'signal.300'}
                    fontFamily="heading"
                    data-testid="quota-remaining-tokens"
                  >
                    {isUnlimited ? '∞' : formatTokens(remaining)}
                  </StatNumber>
                </Stat>
              </SimpleGrid>

              {isUnlimited ? (
                <Box
                  h="10px"
                  bg="whiteAlpha.200"
                  borderRadius="full"
                  data-testid="quota-progress"
                />
              ) : (
                <Box>
                  <Progress
                    value={pct}
                    colorScheme={isExhausted ? 'red' : pct > 80 ? 'orange' : 'signal'}
                    size="md"
                    borderRadius="full"
                    bg="whiteAlpha.100"
                    data-testid="quota-progress"
                  />
                  <HStack
                    justify="space-between"
                    mt={2}
                    fontSize="xs"
                    color="whiteAlpha.600"
                  >
                    <Text>已用 {pct}%</Text>
                    <Text>
                      {quota.reset_at
                        ? `重置 ${formatDateTime(quota.reset_at)}`
                        : '无重置时间'}
                    </Text>
                  </HStack>
                </Box>
              )}

              <HStack spacing={6} fontSize="sm" color="whiteAlpha.700" wrap="wrap">
                <HStack spacing={2}>
                  <Text>期间</Text>
                  <Tag size="sm" colorScheme="copper" variant="subtle">
                    {isUnlimited ? '无限额' : PERIOD_LABEL[quota.period] ?? quota.period}
                  </Tag>
                </HStack>
                {resetIn && (
                  <Text color="whiteAlpha.500">· {resetIn}</Text>
                )}
              </HStack>
            </Stack>
          </CardBody>
        </Card>

        {/* 修改卡 */}
        <Card bg="ink.900" borderColor="whiteAlpha.100" borderWidth="1px">
          <CardHeader pb={2}>
            <Heading size="sm" color="whiteAlpha.900">
              修改额度
            </Heading>
          </CardHeader>
          <CardBody>
            <Stack spacing={5}>
              <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                <Box>
                  <Text fontSize="xs" color="whiteAlpha.600" mb={2}>
                    总额 (tokens, 0 = 不限)
                  </Text>
                  <HStack>
                    <Input
                      type="number"
                      min={0}
                      value={totalInput}
                      onChange={(e) => setTotalInput(e.target.value)}
                      bg="ink.800"
                      borderColor="whiteAlpha.200"
                      data-testid="quota-total-input"
                    />
                    <Button
                      colorScheme="copper"
                      onClick={() => void handleSaveTotal()}
                      isLoading={savingTotal}
                      isDisabled={savingTotal || savingPeriod || resetting}
                      data-testid="quota-save-button"
                    >
                      保存
                    </Button>
                  </HStack>
                </Box>
                <Box>
                  <Text fontSize="xs" color="whiteAlpha.600" mb={2}>
                    期间
                  </Text>
                  <Select
                    value={quota.period}
                    onChange={handlePeriodChange}
                    bg="ink.800"
                    borderColor="whiteAlpha.200"
                    isDisabled={savingPeriod || savingTotal || resetting}
                    data-testid="quota-period-select"
                  >
                    {PERIOD_OPTIONS.map((p) => (
                      <option key={p} value={p}>
                        {PERIOD_LABEL[p]}
                      </option>
                    ))}
                  </Select>
                </Box>
              </SimpleGrid>

              <Box>
                <Button
                  size="sm"
                  colorScheme="red"
                  variant="outline"
                  onClick={openResetDialog}
                  isDisabled={resetting || savingTotal || savingPeriod}
                  isLoading={resetting}
                  data-testid="quota-reset-button"
                >
                  重置额度
                </Button>
                <Text mt={2} fontSize="xs" color="whiteAlpha.500">
                  重置后该用户已用 tokens 立即清零, 总额与期间不变。
                </Text>
              </Box>
            </Stack>
          </CardBody>
        </Card>

        {/* 用量表 */}
        <Card bg="ink.900" borderColor="whiteAlpha.100" borderWidth="1px">
          <CardHeader pb={2}>
            <Heading size="sm" color="whiteAlpha.900">
              最近 30 天用量
            </Heading>
          </CardHeader>
          <CardBody>
            {breakdown.length === 0 ? (
              <Flex h="80px" align="center" justify="center">
                <Text fontSize="sm" color="whiteAlpha.500">
                  暂无用量记录
                </Text>
              </Flex>
            ) : (
              <TableContainer>
                <Table size="sm" variant="simple">
                  <Thead>
                    <Tr>
                      <Th color="whiteAlpha.600" fontSize="xs">
                        日期
                      </Th>
                      <Th color="whiteAlpha.600" fontSize="xs" isNumeric>
                        Prompt
                      </Th>
                      <Th color="whiteAlpha.600" fontSize="xs" isNumeric>
                        Completion
                      </Th>
                      <Th color="whiteAlpha.600" fontSize="xs" isNumeric>
                        合计
                      </Th>
                      <Th color="whiteAlpha.600" fontSize="xs" isNumeric>
                        调用次数
                      </Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {breakdown.map((d) => (
                      <Tr key={d.date} data-testid="quota-usage-row">
                        <Td fontSize="sm" fontFamily="mono" color="whiteAlpha.800">
                          {d.date}
                        </Td>
                        <Td fontSize="sm" isNumeric color="whiteAlpha.800">
                          {formatTokens(d.prompt_tokens)}
                        </Td>
                        <Td fontSize="sm" isNumeric color="whiteAlpha.800">
                          {formatTokens(d.completion_tokens)}
                        </Td>
                        <Td
                          fontSize="sm"
                          isNumeric
                          fontWeight="semibold"
                          color="copper.300"
                        >
                          {formatTokens(d.total_tokens)}
                        </Td>
                        <Td fontSize="sm" isNumeric color="whiteAlpha.800">
                          {d.calls}
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </TableContainer>
            )}
          </CardBody>
        </Card>
      </Stack>

      <AlertDialog
        isOpen={resetDialog.isOpen}
        onClose={handleResetDismiss}
        leastDestructiveRef={cancelRef}
        isCentered
      >
        <AlertDialogOverlay>
          <AlertDialogContent
            bg="ink.900"
            borderColor="whiteAlpha.200"
            borderWidth="1px"
          >
            <AlertDialogHeader fontFamily="heading" color="copper.300">
              重置额度
            </AlertDialogHeader>
            <AlertDialogBody color="whiteAlpha.800">
              确定要把用户「{username}」的已用额度清零吗？该操作立即生效, 不可撤销。
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button
                ref={cancelRef}
                variant="ghost"
                onClick={handleResetDismiss}
                isDisabled={resetting}
              >
                取消
              </Button>
              <Button
                colorScheme="red"
                onClick={() => void handleResetConfirm()}
                ml={3}
                isLoading={resetting}
                data-testid="quota-reset-confirm"
              >
                重置
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Box>
  )
}
