// App 根组件 - 路由 + KB 列表加载
import { Flex } from '@chakra-ui/react'
import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import type { KB } from './types'
import { api } from './api'
import { KnowledgeBaseSidebar } from './components/KnowledgeBaseSidebar'
import { KBMainArea } from './components/KBMainArea'
import { EmptyState } from './components/EmptyState'

export function App() {
  const [kbs, setKBs] = useState<KB[]>([])
  const [loading, setLoading] = useState(true)

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

  return (
    <Flex h="100vh" w="100vw" overflow="hidden">
      <KnowledgeBaseSidebar kbs={kbs} loading={loading} onRefresh={refreshKBs} />
      <Routes>
        <Route path="/" element={<RootRedirect kbs={kbs} loading={loading} />} />
        <Route path="/kbs/:kbId" element={<KBRoute onKBDeleted={refreshKBs} />} />
        <Route path="*" element={<EmptyState />} />
      </Routes>
    </Flex>
  )
}

function RootRedirect({ kbs, loading }: { kbs: KB[]; loading: boolean }) {
  if (loading) return null
  if (kbs.length === 0) return <EmptyState />
  return <Navigate to={`/kbs/${kbs[0].id}`} replace />
}

function KBRoute({ onKBDeleted: _onKBDeleted }: { onKBDeleted: () => void }) {
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