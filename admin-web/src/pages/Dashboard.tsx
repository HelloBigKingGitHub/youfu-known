import {
  Box,
  Flex,
  Grid,
  GridItem,
  HStack,
  Heading,
  Spinner,
  Stack,
  Stat,
  StatLabel,
  StatNumber,
  Text,
  VStack,
} from '@chakra-ui/react'
import { useEffect, useState } from 'react'
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  type TooltipProps,
} from 'recharts'
import { api, formatApiError } from '../api'
import type { DashboardStats } from '../api'
import { formatBytes, formatNumber } from '../lib/format'

const COLORS = ['#e6a95d', '#52c7b5', '#f4c98a', '#2aa18f']

export function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .dashboard()
      .then((data) => {
        if (!cancelled) setStats(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return (
      <Box>
        <Heading size="md" color="red.300" mb={3}>
          加载失败
        </Heading>
        <Text color="whiteAlpha.700">{error}</Text>
      </Box>
    )
  }

  if (!stats) {
    return (
      <Flex h="60vh" align="center" justify="center">
        <Spinner color="signal.400" size="lg" />
      </Flex>
    )
  }

  const docByStatus = Object.entries(stats.documents.by_status || {})
  const kbBreakdown = [
    { name: '共享', value: stats.kbs.shared },
    { name: '私有', value: stats.kbs.private },
  ].filter((item) => item.value > 0)

  return (
    <Stack spacing={8}>
      <Box>
        <Heading fontFamily="heading" color="copper.300" size="lg">
          系统总览
        </Heading>
        <Text color="whiteAlpha.600" mt={1} fontSize="sm">
          实时统计知识库、用户、文档与运行指标
        </Text>
      </Box>
      <Grid templateColumns={{ base: 'repeat(1, 1fr)', md: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' }} gap={4}>
        <StatCard label="知识库" value={stats.kbs.total} sublabel={`共享 ${stats.kbs.shared} · 私有 ${stats.kbs.private}`} />
        <StatCard label="用户" value={stats.users.total} sublabel={`已审核 ${stats.users.approved} · 待审 ${stats.users.pending}`} />
        <StatCard label="文档" value={stats.documents.total} sublabel={`切片 ${formatNumber(stats.chunks)}`} />
        <StatCard label="存储" value={formatBytes(stats.storage_bytes)} sublabel={`近 24h 上传 ${formatNumber(stats.uploaded_24h)}`} />
      </Grid>
      <Grid templateColumns={{ base: 'repeat(1, 1fr)', lg: 'repeat(2, 1fr)' }} gap={6}>
        <GridItem>
          <Panel title="知识库分布">
            {kbBreakdown.length === 0 ? (
              <Text color="whiteAlpha.500" fontSize="sm">暂无数据</Text>
            ) : (
              <Box h="240px">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={kbBreakdown} dataKey="value" nameKey="name" outerRadius={80} innerRadius={48} paddingAngle={2}>
                      {kbBreakdown.map((_, idx) => (
                        <Cell key={idx} fill={COLORS[idx % COLORS.length]} stroke="none" />
                      ))}
                    </Pie>
                    <Tooltip content={<DarkTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
              </Box>
            )}
            <HStack justify="center" spacing={6} mt={2}>
              {kbBreakdown.map((item, idx) => (
                <HStack key={item.name} spacing={2}>
                  <Box w="10px" h="10px" borderRadius="full" bg={COLORS[idx % COLORS.length]} />
                  <Text fontSize="sm" color="whiteAlpha.700">{item.name}</Text>
                  <Text fontSize="sm" color="whiteAlpha.900">{item.value}</Text>
                </HStack>
              ))}
            </HStack>
          </Panel>
        </GridItem>
        <GridItem>
          <Panel title="文档状态">
            {docByStatus.length === 0 ? (
              <Text color="whiteAlpha.500" fontSize="sm">暂无文档</Text>
            ) : (
              <VStack align="stretch" spacing={3} mt={2}>
                {docByStatus.map(([status, count], idx) => {
                  const total = docByStatus.reduce((sum, [, c]) => sum + c, 0) || 1
                  const pct = (count / total) * 100
                  return (
                    <Box key={status}>
                      <HStack justify="space-between" mb={1}>
                        <Text fontSize="sm" color="whiteAlpha.800">{status}</Text>
                        <Text fontSize="sm" color="whiteAlpha.600">{formatNumber(count)}</Text>
                      </HStack>
                      <Box h="8px" bg="whiteAlpha.100" borderRadius="full" overflow="hidden">
                        <Box
                          h="100%"
                          width={`${pct}%`}
                          bg={COLORS[idx % COLORS.length]}
                          transition="width 240ms ease"
                        />
                      </Box>
                    </Box>
                  )
                })}
              </VStack>
            )}
          </Panel>
        </GridItem>
      </Grid>
      <Grid templateColumns={{ base: 'repeat(1, 1fr)', md: 'repeat(2, 1fr)' }} gap={4}>
        <StatCard label="近 24h 对话" value={stats.chat_turns_24h} sublabel="用户提问总量" />
        <StatCard label="近 24h LLM 调用" value={stats.llm_calls_24h} sublabel="模型推理次数" />
      </Grid>
    </Stack>
  )
}

function StatCard({ label, value, sublabel }: { label: string; value: number | string; sublabel?: string }) {
  return (
    <Box
      bg="ink.900"
      borderWidth="1px"
      borderColor="whiteAlpha.100"
      borderRadius="lg"
      p={5}
      transition="border-color 120ms ease, transform 120ms ease"
      _hover={{ borderColor: 'copper.400', transform: 'translateY(-2px)' }}
    >
      <Stat>
        <StatLabel color="whiteAlpha.600" fontSize="xs" letterSpacing="0.08em" textTransform="uppercase">
          {label}
        </StatLabel>
        <StatNumber color="whiteAlpha.900" fontFamily="heading" fontSize="3xl" mt={1}>
          {typeof value === 'number' ? formatNumber(value) : value}
        </StatNumber>
        {sublabel && (
          <Text mt={2} fontSize="sm" color="whiteAlpha.600">
            {sublabel}
          </Text>
        )}
      </Stat>
    </Box>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Box
      bg="ink.900"
      borderWidth="1px"
      borderColor="whiteAlpha.100"
      borderRadius="lg"
      p={5}
      h="100%"
    >
      <Heading size="sm" color="copper.300" fontFamily="heading" mb={4}>
        {title}
      </Heading>
      {children}
    </Box>
  )
}

function DarkTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null
  return (
    <Box bg="ink.800" borderWidth="1px" borderColor="whiteAlpha.200" borderRadius="md" px={3} py={2}>
      <Text fontSize="xs" color="whiteAlpha.600">{payload[0].name}</Text>
      <Text fontSize="sm" color="whiteAlpha.900">{formatNumber(payload[0].value as number)}</Text>
    </Box>
  )
}
