// 鉴权守卫 - 启动时校验 /api/auth/me, 未登录跳 /login
import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Center, Spinner, useToast } from '@chakra-ui/react'
import { api, USER_STORAGE_KEY } from '../api'

export function RequireAuth() {
  const [authState, setAuthState] = useState<'loading' | 'authed' | 'unauthed'>('loading')
  const location = useLocation()
  const toast = useToast()

  useEffect(() => {
    api
      .me()
      .then(() => setAuthState('authed'))
      .catch(() => {
        // 只有之前登录过才提示会话过期; 首次访问直接静默跳转
        if (localStorage.getItem(USER_STORAGE_KEY)) {
          toast({
            title: '会话过期',
            description: '请重新登录',
            status: 'warning',
            duration: 4000,
            isClosable: true,
            position: 'top',
          })
        }
        setAuthState('unauthed')
      })
  }, [toast])

  if (authState === 'loading') {
    return (
      <Center h="100vh">
        <Spinner size="lg" color="brand.500" />
      </Center>
    )
  }

  if (authState === 'unauthed') {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }

  return <Outlet />
}
