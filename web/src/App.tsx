// App 根组件 - 响应式布局 (桌面 row / 手机 column)
// 认证: /login /register 公开, 其余路由需登录
import {
  Box,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  Flex,
  useBreakpointValue,
  useDisclosure,
} from '@chakra-ui/react'
import { useCallback, useEffect, useState } from 'react'
import {
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from 'react-router-dom'
import type { KB, User } from './types'
import { api, USER_STORAGE_KEY } from './api'
import { AdminUsersPage } from './components/AdminUsersPage'
import { ChangePasswordPage } from './components/ChangePasswordPage'
import { EmptyState } from './components/EmptyState'
import { KBChatTab } from './components/KBChatTab'
import { KBMainArea } from './components/KBMainArea'
import { KBManageTab } from './components/KBManageTab'
import { KnowledgeBaseSidebar } from './components/KnowledgeBaseSidebar'
import { LoginPage } from './components/LoginPage'
import { RegisterPage } from './components/RegisterPage'
import { RequireAuth } from './components/RequireAuth'
import { TopBar } from './components/TopBar'

export function App() {
  const [user, setUser] = useState<User | null>(null)

  // 从 localStorage 恢复登录用户 (仅用于显示, token 在 HttpOnly cookie)
  useEffect(() => {
    const raw = localStorage.getItem(USER_STORAGE_KEY)
    if (raw) {
      try {
        setUser(JSON.parse(raw))
      } catch {
        localStorage.removeItem(USER_STORAGE_KEY)
      }
    }
  }, [])

  const handleLogin = useCallback((u: User) => {
    setUser(u)
  }, [])

  const handleLogout = useCallback(() => {
    localStorage.removeItem(USER_STORAGE_KEY)
    setUser(null)
  }, [])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage onLogin={handleLogin} />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<RequireAuth />}>
        <Route
          path="/*"
          element={
            <AuthenticatedApp user={user} onLogout={handleLogout} />
          }
        />
      </Route>
    </Routes>
  )
}

interface AuthenticatedAppProps {
  user: User | null
  onLogout: () => void
}

function AuthenticatedApp({ user, onLogout }: AuthenticatedAppProps) {
  const [kbs, setKBs] = useState<KB[]>([])
  const [loading, setLoading] = useState(true)

  const drawer = useDisclosure()
  const isMobile = useBreakpointValue({ base: true, md: false })
  const { kbId } = useParams<{ kbId: string }>()

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

  const currentKB = kbs.find((kb) => kb.id === kbId)

  // 移动端选中 KB 后自动关闭 Drawer
  const handleNavigate = useCallback(
    (_kbId: string) => {
      if (isMobile) drawer.onClose()
    },
    [isMobile, drawer],
  )

  return (
    <Flex
      direction="column"
      h="100vh"
      w="100vw"
      overflow="hidden"
      bg="gray.50"
    >
      <TopBar
        user={user}
        currentKBName={currentKB?.name}
        onToggleSidebar={drawer.onOpen}
        onLogout={onLogout}
        isMobile={!!isMobile}
      />
      <Flex flex={1} overflow="hidden">
        {/* 桌面端侧栏固定 */}
        {!isMobile && (
          <KnowledgeBaseSidebar
            kbs={kbs}
            loading={loading}
            onRefresh={refreshKBs}
            isMobile={false}
            onNavigate={handleNavigate}
            user={user}
          />
        )}

        {/* 移动端侧栏进 Drawer */}
        {isMobile && (
          <Drawer
            isOpen={drawer.isOpen}
            placement="left"
            onClose={drawer.onClose}
            size="xs"
          >
            <DrawerOverlay />
            <DrawerContent>
              <DrawerCloseButton />
              <DrawerHeader borderBottomWidth="1px" py={3}>
                知识库
              </DrawerHeader>
              <DrawerBody p={0}>
                <KnowledgeBaseSidebar
                  kbs={kbs}
                  loading={loading}
                  onRefresh={refreshKBs}
                  isMobile={true}
                  onNavigate={handleNavigate}
                  user={user}
                />
              </DrawerBody>
            </DrawerContent>
          </Drawer>
        )}

        {/* 主区域 */}
        <Box flex={1} overflow="auto">
          <Routes>
            <Route
              path="/"
              element={<RootRedirect kbs={kbs} loading={loading} />}
            />
            <Route
              path="/kbs/:kbId"
              element={<KBShell onKBDeleted={refreshKBs} />}
            >
              <Route index element={<Navigate to="manage" replace />} />
              <Route path="manage" element={<KBManageTab />} />
              <Route path="chat" element={<KBChatTab />} />
            </Route>
            <Route
              path="/change-password"
              element={<ChangePasswordPage />}
            />
            <Route path="/admin/users" element={<AdminUsersPage />} />
            <Route path="*" element={<EmptyState />} />
          </Routes>
        </Box>
      </Flex>
    </Flex>
  )
}

function RootRedirect({
  kbs,
  loading,
}: {
  kbs: KB[]
  loading: boolean
}) {
  if (loading) return null
  if (kbs.length === 0) return <EmptyState />
  return <Navigate to={`/kbs/${kbs[0].id}`} replace />
}

function KBShell({
  onKBDeleted: _onKBDeleted,
}: {
  onKBDeleted: () => void
}) {
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
