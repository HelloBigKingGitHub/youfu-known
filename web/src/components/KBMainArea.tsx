// KB 主区域 shell: 顶部 KB 信息 + 软胶囊 Tab 切换器 + 子路由 Outlet
// 子路由:
//   /kbs/:kbId/manage -> KBManageTab
//   /kbs/:kbId/chat   -> KBChatTab
// 桌面 + 平板保持当前主区域 max-width 960px 居中
// 移动端 padding 减小, Tab 切换器水平排
import {
  Badge,
  Box,
  Flex,
  HStack,
  Heading,
  Spinner,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
} from '@chakra-ui/react'
import { useCallback, useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import type { Document, KB } from '../types'
import { api, ApiError } from '../api'
import { useToast } from '@chakra-ui/react'

interface Props {
  kbId: string
}

export function KBMainArea({ kbId }: Props) {
  const [kb, setKB] = useState<KB | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()

  const refresh = useCallback(async () => {
    try {
      const detail = await api.getKB(kbId)
      setKB(detail.kb)
      setDocuments(detail.documents)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '加载失败'
      toast({ title: '加载失败', description: msg, status: 'error', duration: 3000 })
    } finally {
      setLoading(false)
    }
  }, [kbId, toast])

  useEffect(() => {
    setLoading(true)
    refresh()
  }, [refresh])

  // 根据 URL 决定 Tab 索引
  const tabIndex = location.pathname.endsWith('/chat') ? 1 : 0

  const handleTabChange = (idx: number) => {
    if (idx === 0) navigate(`/kbs/${kbId}/manage`, { replace: true })
    else navigate(`/kbs/${kbId}/chat`, { replace: true })
  }

  if (loading || !kb) {
    return (
      <Flex flex={1} align="center" justify="center" h="100%">
        <HStack spacing={3} color="gray.500">
          <Spinner size="sm" color="brand.500" />
          <Text>加载中...</Text>
        </HStack>
      </Flex>
    )
  }

  return (
    <Box flex={1} h="100%" overflowY="auto" bg="gray.50">
      <Box maxW="960px" mx="auto" p={{ base: 3, md: 5, lg: 6 }}>
        {/* KB 标题区 (固定在两个 tab 之上) */}
        <Box mb={{ base: 4, md: 5 }}>
          <Heading size={{ base: 'md', md: 'lg' }} color="gray.900">
            {kb.name}
          </Heading>
          {kb.description && (
            <Text color="gray.500" mt={1} fontSize={{ base: 'sm', md: 'md' }} noOfLines={2}>
              {kb.description}
            </Text>
          )}
          <HStack spacing={2} mt={3}>
            <Badge
              px={2}
              py={0.5}
              borderRadius="full"
              bg="surface.subtle"
              color="gray.600"
              fontWeight="medium"
              fontSize="xs"
            >
              {kb.doc_count} 文档
            </Badge>
            <Badge
              px={2}
              py={0.5}
              borderRadius="full"
              bg="surface.subtle"
              color="gray.600"
              fontWeight="medium"
              fontSize="xs"
            >
              {kb.chunk_count} chunks
            </Badge>
          </HStack>
        </Box>

        {/* Tab 切换器 */}
        <Tabs
          index={tabIndex}
          onChange={handleTabChange}
          variant="soft-rounded"
          isLazy
          lazyBehavior="keepMounted"
        >
          <Box overflowX="auto" mx={{ base: -3, md: 0 }} px={{ base: 3, md: 0 }}>
            <TabList minW="max-content">
              <Tab>📎 管理</Tab>
              <Tab>💬 问答</Tab>
            </TabList>
          </Box>

          <TabPanels mt={{ base: 4, md: 5 }}>
            <TabPanel px={0}>
              <Outlet context={{ kb, documents, refresh }} />
            </TabPanel>
            <TabPanel px={0}>
              <Outlet context={{ kb, documents, refresh }} />
            </TabPanel>
          </TabPanels>
        </Tabs>
      </Box>
    </Box>
  )
}
