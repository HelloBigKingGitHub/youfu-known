// 登录页 - 全屏居中卡片, 移动端优先 (大输入框/大按钮)
import { useState } from 'react'
import { Link as RouterLink, useNavigate, useLocation } from 'react-router-dom'
import {
  Box,
  Button,
  Card,
  CardBody,
  Center,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Link,
  Stack,
  Text,
  VStack,
  useToast,
} from '@chakra-ui/react'
import { api, USER_STORAGE_KEY } from '../api'
import type { User } from '../types'

interface LoginPageProps {
  onLogin: (user: User) => void
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()

  const from = (location.state as { from?: string } | undefined)?.from || '/'

  const handleSubmit = async () => {
    if (!username.trim() || !password) return
    setLoading(true)
    try {
      const resp = await api.login(username.trim(), password)
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(resp.user))
      onLogin(resp.user)
      navigate(from, { replace: true })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '用户名或密码错误'
      toast({
        title: '登录失败',
        description: msg,
        status: 'error',
        duration: 4000,
        position: 'top',
      })
    } finally {
      setLoading(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSubmit()
  }

  return (
    <Center minH="100vh" bg="gray.50" px={4}>
      <Card maxW="400px" w="full" boxShadow="lg" borderRadius="2xl">
        <CardBody p={{ base: 6, md: 8 }}>
          <VStack spacing={6}>
            <VStack spacing={2} align="center">
              <Box
                w="56px"
                h="56px"
                bg="brand.500"
                color="white"
                borderRadius="2xl"
                display="flex"
                alignItems="center"
                justifyContent="center"
                fontSize="2xl"
                fontWeight="bold"
              >
                Y
              </Box>
              <Heading size="lg">youfu-known</Heading>
              <Text fontSize="sm" color="gray.500">
                登录以使用知识库问答
              </Text>
            </VStack>

            <Stack spacing={4} w="full">
              <FormControl>
                <FormLabel fontSize="sm">用户名</FormLabel>
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="admin"
                  size="lg"
                  autoFocus
                  isDisabled={loading}
                />
              </FormControl>
              <FormControl>
                <FormLabel fontSize="sm">密码</FormLabel>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="••••••••"
                  size="lg"
                  isDisabled={loading}
                />
              </FormControl>
            </Stack>

            <Button
              colorScheme="brand"
              size="lg"
              w="full"
              onClick={handleSubmit}
              isLoading={loading}
              loadingText="登录中"
            >
              登录
            </Button>

            <Text fontSize="sm" color="gray.600" textAlign="center">
              还没有账号?{' '}
              <Link
                as={RouterLink}
                to="/register"
                color="brand.600"
                fontWeight="semibold"
              >
                注册
              </Link>
            </Text>

            <Text fontSize="xs" color="gray.400" textAlign="center">
              个人知识库 · 数据本地存储
            </Text>
          </VStack>
        </CardBody>
      </Card>
    </Center>
  )
}
