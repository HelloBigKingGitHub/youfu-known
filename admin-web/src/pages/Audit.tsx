import {
  Alert,
  AlertIcon,
  Box,
  Flex,
  HStack,
  Heading,
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
} from '@chakra-ui/react'
import { useEffect, useMemo, useState } from 'react'
import { api, formatApiError } from '../api'
import type { AuditEntry } from '../api'
import { formatDateTime } from '../lib/format'

type Filter = 'all' | 'login' | 'chat'

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  useEffect(() => {
    let cancelled = false
    api
      .audit(200)
      .then((data) => {
        if (!cancelled) setEntries(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    if (!entries) return []
    if (filter === 'all') return entries
    return entries.filter((entry) => entry.type === filter)
  }, [entries, filter])

  if (error) {
    return (
      <Alert status="error" variant="left-accent">
        <AlertIcon />
        <Text>{error}</Text>
      </Alert>
    )
  }

  if (!entries) {
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
          审计日志
        </Heading>
        <Text mt={1} color="whiteAlpha.600" fontSize="sm">
          最近 200 条登录与对话记录，按时间倒序展示。
        </Text>
      </Box>
      <HStack>
        <Select
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          maxW="200px"
          bg="ink.800"
          borderColor="whiteAlpha.200"
          _hover={{ borderColor: 'copper.400' }}
        >
          <option value="all">全部</option>
          <option value="login">登录</option>
          <option value="chat">对话</option>
        </Select>
        <Text color="whiteAlpha.500" fontSize="sm">
          共 {filtered.length} 条
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
              <Th>类型</Th>
              <Th>用户</Th>
              <Th>知识库</Th>
              <Th>内容</Th>
              <Th>时间</Th>
            </Tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr>
                <Td colSpan={5}>
                  <Text textAlign="center" color="whiteAlpha.500" py={6}>
                    暂无记录
                  </Text>
                </Td>
              </Tr>
            ) : (
              filtered.map((entry) => (
                <Tr key={entry.id} _hover={{ bg: 'whiteAlpha.50' }}>
                  <Td>
                    <Tag
                      size="sm"
                      colorScheme={entry.type === 'login' ? 'orange' : 'cyan'}
                      variant="subtle"
                    >
                      {entry.type === 'login' ? '登录' : entry.type === 'chat' ? '对话' : entry.type}
                    </Tag>
                  </Td>
                  <Td>
                    <Text color="whiteAlpha.800">{entry.username || '系统'}</Text>
                  </Td>
                  <Td>
                    <Text color="whiteAlpha.700" fontSize="sm">{entry.kb_id || '—'}</Text>
                  </Td>
                  <Td maxW="520px">
                    <Text
                      color="whiteAlpha.800"
                      fontSize="sm"
                      noOfLines={2}
                      title={entry.question || JSON.stringify(entry.detail) || ''}
                    >
                      {entry.question || JSON.stringify(entry.detail) || '—'}
                    </Text>
                  </Td>
                  <Td>
                    <Text color="whiteAlpha.700" fontSize="sm">{formatDateTime(entry.created_at)}</Text>
                  </Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Box>
    </Stack>
  )
}
