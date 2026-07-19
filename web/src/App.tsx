// App 根组件 - 响应式布局 (桌面 row / 手机 column)
// 移动端: 顶栏 (汉堡 + 标题) + 抽屉式侧栏 + 主区域
// 桌面: 固定侧栏 + 主区域 (原样)
import {
  Box,
  Flex,
  IconButton,
  Text,
  useBreakpointValue,
  useDisclosure,
} from '@chakra-ui/react'
import { HamburgerIcon } from '@chakra-ui/icons'
import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import type { KB } from './types'
import { api } from './api'
import { KnowledgeBaseSidebar } from './components/KnowledgeBaseSidebar'
import { KBMainArea } from './components/KBMainArea'
import { KBManageTab } from './components/KBManageTab'
import { KBChatTab } from './components/KBChatTab'
import { EmptyState } from './components/EmptyState'

export function App() {
  const [kbs, setKBs] = useState<KB[]>([])
  const [loading, setLoading] = useState(true)

  // 移动端 Drawer 控制
  const drawer = useDisclosure()
  const isMobile = useBreakpointValue({ base: true, md: false })

  const refreshKBs = useCallback(async () => {
    setLoading(true)
    try {
      const list = await api.listKBs()
      setKBs(list)
    } catch {
      setKBs([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshKBs()
  }, [refreshKBs])

  // 移动端选中 KB 后自动关闭 Drawer
  const handleNavigate = useCallback(
    (_kbId: string) => {
      // 真正的跳转由 <Link> 触发, 这里只关 Drawer
      if (isMobile) drawer.onClose()
      // 路由跳转用 navigate() 在 sidebar 里做
    },
    [isMobile, drawer],
  )

  return (
    <Flex h="100vh" w="100vw" overflow="hidden" direction={{ base: 'column', md: 'row' }}>
      {/* 移动端顶栏 - 只有移动端显示 */}
      {isMobile && (
        <Flex
          h="56px"
          align="center"
          px={3}
          borderBottom="1px"
          borderColor="gray.200"
          bg="white"
          flexShrink={0}
          gap={3}
        >
          <IconButton
            aria-label="打开侧栏"
            icon={<HamburgerIcon />}
            size="md"
            variant="ghost"
            onClick={drawer.onOpen}
            minW="44px"
            minH="44px"
          />
          <Text fontSize="md" fontWeight="bold" color="brand.700">
            youfu-known
          </Text>
        </Flex>
      )}

      {/* 侧栏: 桌面直接渲染, 移动端传入 drawer props 渲染为 Drawer */}
      <KnowledgeBaseSidebar
        kbs={kbs}
        loading={loading}
        onRefresh={refreshKBs}
        isMobile={!!isMobile}
        drawer={drawer}
        onNavigate={handleNavigate}
      />

      {/* 主区域: 移动端可滚动 */}
      <Box flex={1} h={{ base: 'calc(100vh - 56px)', md: '100vh' }} overflow="auto">
        <Routes>
          <Route path="/" element={<RootRedirect kbs={kbs} loading={loading} />} />
          <Route path="/kbs/:kbId" element={<KBShell onKBDeleted={refreshKBs} />}>
            <Route index element={<Navigate to="manage" replace />} />
            <Route path="manage" element={<KBManageTab />} />
            <Route path="chat" element={<KBChatTab />} />
          </Route>
          <Route path="*" element={<EmptyState />} />
        </Routes>
      </Box>
    </Flex>
  )
}

function RootRedirect({ kbs, loading }: { kbs: KB[]; loading: boolean }) {
  if (loading) return null
  if (kbs.length === 0) return <EmptyState />
  return <Navigate to={`/kbs/${kbs[0].id}`} replace />
}

function KBShell({ onKBDeleted: _onKBDeleted }: { onKBDeleted: () => void }) {
  const { kbId } = useParams<{ kbId: string }>()
  const navigate = useNavigate()
  const [exists, setExists] = useState<boolean | null>(null)

  useEffect(() => {
    if (!kbId) return
    api
      .getKB(kbId)
      .then(() => setExists(true))
      .catch(() => {
        setExists(false)
        navigate('/', { replace: true })
      })
  }, [kbId, navigate])

  if (!kbId || exists === false) return null
  if (exists === null) return null
  return <KBMainArea kbId={kbId} />
}
