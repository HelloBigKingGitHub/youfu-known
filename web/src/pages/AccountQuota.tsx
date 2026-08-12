// 我的额度页面 (Phase 2.1)
//
// 后端 spec: GET /api/users/me/quota → QuotaInfo (见 src/api/quota.ts)
//
// 风格: 跟 ChangePasswordPage 一致 (Chakra UI 卡片 + 居中布局),
//       跟 KBSettings.tsx 一致的 toast 风格 (formatApiError)。
//
// 视觉:
//   - 顶部大卡片: 已用 / 总额 + 进度条 + 期间/重置时间
//   - 红色 banner: 超额时显示
//   - 下方表格: 30 天按日 token 用量
import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
  Box,
  Button,
  Card,
  CardBody,
  Center,
  Flex,
  HStack,
  Heading,
  Progress,
  Spinner,
  Stack,
  Stat,
  StatHelpText,
  StatLabel,
  StatNumber,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  VStack,
  useToast,
} from '@chakra-ui/react'
import { ArrowBackIcon } from '@chakra-ui/icons'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type QuotaInfo } from '../api'
import { formatApiError } from '../lib/apiErrors'

const PERIOD_LABEL: Record<QuotaInfo['period'], string> = {
  monthly: '按月',
  weekly: '按周',
  daily: '按日',
  none: '不限',
}

/** 把 token 数格式化成 K / M, 例如 1.2K / 234K / 1.5M */
function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 100_000 ? 0 : 1)}K`
  return String(n)
}

/** 把 ISO datetime 转成 "X 天 / X 小时 / X 分钟后重置" 文案 */
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

/** 把 ISO datetime 转成 "YYYY-MM-DD HH:mm" */
function formatResetAt(resetAt: string | null): string {
  if (!resetAt) return '—'
  const d = new Date(resetAt)
  if (Number.isNaN(d.getTime())) return resetAt
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function AccountQuota() {
  const [quota, setQuota] = useState<QuotaInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()
  const navigate = useNavigate()

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getMyQuota()
      setQuota(data)
    } catch (e: unknown) {
      const msg = formatApiError(e)
      setError(msg)
      toast({
        title: '加载额度失败',
        description: msg,
        status: 'error',
        duration: 4000,
        position: 'top',
      })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void reload()
  }, [reload])

  // ---- loading / error ----
  if (loading && !quota) {
    return (
      <Center h="100%" flex={1} bg="gray.50" p={{ base: 4, md: 8 }}>
        <VStack spacing={3}>
          <Spinner color="brand.500" size="lg" />
          <Text fontSize="sm" color="gray.500">
            正在加载额度信息…
          </Text>
        </VStack>
      </Center>
    )
  }

  if (error && !quota) {
    return (
      <Center h="100%" flex={1} bg="gray.50" p={{ base: 4, md: 8 }}>
        <Card maxW="500px" w="full" boxShadow="lg" borderRadius="2xl">
          <CardBody>
            <VStack spacing={4} align="stretch">
              <Alert status="error" borderRadius="lg">
                <AlertIcon />
                <Box>
                  <AlertTitle fontSize="sm">加载额度失败</AlertTitle>
                  <AlertDescription fontSize="sm">{error}</AlertDescription>
                </Box>
              </Alert>
              <HStack>
                <Button onClick={() => void reload()} colorScheme="brand">
                  重试
                </Button>
                <Button variant="ghost" onClick={() => navigate(-1)}>
                  返回
                </Button>
              </HStack>
            </VStack>
          </CardBody>
        </Card>
      </Center>
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
  const periodText = isUnlimited
    ? '无限额'
    : PERIOD_LABEL[quota.period] ?? quota.period

  // 按日期倒序 (今天在最上面)
  const breakdown = [...(quota.usage_breakdown ?? [])].sort((a, b) =>
    a.date < b.date ? 1 : a.date > b.date ? -1 : 0,
  )

  return (
    <Box flex={1} h="100%" bg="gray.50" overflow="auto" p={{ base: 4, md: 8 }}>
      <VStack spacing={6} align="stretch" maxW="900px" mx="auto">
        <HStack justify="space-between" align="flex-end" flexWrap="wrap" gap={2}>
          <Box>
            <Heading size="md" color="gray.800">
              我的额度
            </Heading>
            <Text fontSize="sm" color="gray.500" mt={1}>
              查看 token 用量与重置时间
            </Text>
          </Box>
          <HStack>
            <Button
              size="sm"
              variant="outline"
              leftIcon={<ArrowBackIcon />}
              onClick={() => navigate(-1)}
            >
              返回
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void reload()}
              isLoading={loading}
            >
              刷新
            </Button>
          </HStack>
        </HStack>

        {/* 超额 banner */}
        {isExhausted && (
          <Alert
            status="error"
            variant="left-accent"
            borderRadius="xl"
            data-testid="quota-exhausted-banner"
          >
            <AlertIcon />
            <Box>
              <AlertTitle fontSize="sm">
                额度已用完, 功能暂停
                {quota.reset_at ? `至 ${formatResetAt(quota.reset_at)}` : ''}
              </AlertTitle>
              <AlertDescription fontSize="sm">
                {resetIn
                  ? `${resetIn} 后可继续使用`
                  : '请等待额度重置或联系管理员'}
              </AlertDescription>
            </Box>
          </Alert>
        )}

        {/* 主卡片 */}
        <Card boxShadow="lg" borderRadius="2xl" bg="white">
          <CardBody p={{ base: 5, md: 7 }}>
            <Stack spacing={5}>
              <Flex
                justify="space-between"
                align={{ base: 'flex-start', md: 'center' }}
                direction={{ base: 'column', md: 'row' }}
                gap={3}
              >
                <Box>
                  <Text fontSize="sm" color="gray.500">
                    周期 · {periodText}
                  </Text>
                  <HStack
                    spacing={2}
                    align="baseline"
                    mt={1}
                    data-testid="quota-summary"
                  >
                    <Text
                      fontSize="3xl"
                      fontWeight="bold"
                      color="gray.900"
                      data-testid="quota-used-tokens"
                    >
                      {formatTokens(quota.tokens_used)}
                    </Text>
                    <Text
                      fontSize="md"
                      color="gray.400"
                      data-testid="quota-total-tokens"
                    >
                      / {isUnlimited ? '∞' : formatTokens(quota.tokens_total)}
                    </Text>
                    <Text fontSize="sm" color="gray.500" ml={2}>
                      tokens
                    </Text>
                  </HStack>
                </Box>
                {!isUnlimited && (
                  <Stat textAlign={{ base: 'left', md: 'right' }}>
                    <StatLabel color="gray.500" fontSize="xs">
                      剩余
                    </StatLabel>
                    <StatNumber
                      color={isExhausted ? 'red.500' : 'brand.600'}
                      fontSize="xl"
                      data-testid="quota-remaining-tokens"
                    >
                      {formatTokens(remaining)}
                    </StatNumber>
                    {!isUnlimited && resetIn && (
                      <StatHelpText fontSize="xs" mb={0}>
                        {resetIn}
                      </StatHelpText>
                    )}
                  </Stat>
                )}
              </Flex>

              {/* 进度条: 无限额时显示静态 100% 灰色条 */}
              <Box>
                {isUnlimited ? (
                  <Box
                    h="10px"
                    bg="gray.200"
                    borderRadius="full"
                    data-testid="quota-unlimited"
                  />
                ) : (
                  <>
                    <Progress
                      value={pct}
                      colorScheme={isExhausted ? 'red' : pct > 80 ? 'orange' : 'brand'}
                      size="md"
                      borderRadius="full"
                      bg="gray.100"
                      data-testid="quota-progress"
                    />
                    <HStack
                      justify="space-between"
                      mt={2}
                      fontSize="xs"
                      color="gray.500"
                    >
                      <Text>已用 {pct}%</Text>
                      <Text>
                        重置时间 {formatResetAt(quota.reset_at)}
                      </Text>
                    </HStack>
                  </>
                )}
                {isUnlimited && (
                  <Text mt={2} fontSize="xs" color="gray.500">
                    当前账号未设置总额上限
                  </Text>
                )}
              </Box>
            </Stack>
          </CardBody>
        </Card>

        {/* 30 天用量明细 */}
        <Card boxShadow="lg" borderRadius="2xl" bg="white">
          <CardBody p={{ base: 4, md: 6 }}>
            <Heading size="sm" mb={4} color="gray.700">
              最近 30 天用量
            </Heading>
            {breakdown.length === 0 ? (
              <Center py={10}>
                <Text fontSize="sm" color="gray.400">
                  暂无用量记录
                </Text>
              </Center>
            ) : (
              <TableContainer>
                <Table size="sm" variant="simple">
                  <Thead>
                    <Tr>
                      <Th color="gray.500" fontSize="xs">
                        日期
                      </Th>
                      <Th color="gray.500" fontSize="xs" isNumeric>
                        Prompt
                      </Th>
                      <Th color="gray.500" fontSize="xs" isNumeric>
                        Completion
                      </Th>
                      <Th color="gray.500" fontSize="xs" isNumeric>
                        合计
                      </Th>
                      <Th color="gray.500" fontSize="xs" isNumeric>
                        调用次数
                      </Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {breakdown.map((d) => (
                      <Tr key={d.date} data-testid="quota-usage-row">
                        <Td fontSize="sm" fontFamily="mono">
                          {d.date}
                        </Td>
                        <Td fontSize="sm" isNumeric>
                          {formatTokens(d.prompt_tokens)}
                        </Td>
                        <Td fontSize="sm" isNumeric>
                          {formatTokens(d.completion_tokens)}
                        </Td>
                        <Td fontSize="sm" isNumeric fontWeight="semibold">
                          {formatTokens(d.total_tokens)}
                        </Td>
                        <Td fontSize="sm" isNumeric>
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
      </VStack>
    </Box>
  )
}
