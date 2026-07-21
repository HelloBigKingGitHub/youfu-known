// 注册页 - 全屏居中卡片, 带 Cloudflare Turnstile 防机器人
import { useEffect, useRef, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import {
  Box,
  Button,
  Card,
  CardBody,
  Center,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Heading,
  Input,
  Link,
  Stack,
  Text,
  useToast,
  VStack,
} from '@chakra-ui/react'
import { api } from '../api'

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: unknown) => string
      reset: (widgetId?: string) => void
      remove: (widgetId?: string) => void
      getResponse: (widgetId?: string) => string
    }
  }
}

const USERNAME_RE = /^[a-zA-Z0-9_-]{3,32}$/

export function RegisterPage() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)
  const turnstileRef = useRef<HTMLDivElement>(null)
  const widgetIdRef = useRef<string | null>(null)
  const navigate = useNavigate()
  const toast = useToast()

  useEffect(() => {
    const script = document.createElement('script')
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js'
    script.async = true
    script.defer = true
    document.head.appendChild(script)
    script.onload = () => {
      if (window.turnstile && turnstileRef.current) {
        widgetIdRef.current = window.turnstile.render(
          turnstileRef.current,
          {
            sitekey:
              import.meta.env.VITE_TURNSTILE_SITE_KEY ||
              '1x00000000000000000000AA',
            callback: (token: string) => setTurnstileToken(token),
            'expired-callback': () => setTurnstileToken(null),
          },
        )
      }
    }
    return () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current)
      }
      document.head.removeChild(script)
    }
  }, [])

  const resetTurnstile = () => {
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.reset(widgetIdRef.current)
      setTurnstileToken(null)
    }
  }

  const handleSubmit = async () => {
    if (!username.trim() || !password) return
    if (!USERNAME_RE.test(username.trim())) {
      toast({
        title: '用户名格式不正确',
        status: 'error',
        duration: 3000,
        position: 'top',
      })
      return
    }
    if (password !== confirm) {
      toast({
        title: '两次密码不一致',
        status: 'error',
        duration: 3000,
        position: 'top',
      })
      return
    }
    if (!turnstileToken) {
      toast({
        title: '请先完成人机验证',
        status: 'error',
        duration: 3000,
        position: 'top',
      })
      return
    }
    setLoading(true)
    try {
      await api.register(username.trim(), email, password, turnstileToken)
      toast({
        title: '注册成功, 等待管理员批准',
        status: 'success',
        duration: 4000,
        position: 'top',
      })
      navigate('/login')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '注册失败'
      toast({
        title: '注册失败',
        description: msg,
        status: 'error',
        duration: 4000,
        position: 'top',
      })
      resetTurnstile()
    } finally {
      setLoading(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSubmit()
  }

  const usernameInvalid = !!username && !USERNAME_RE.test(username)
  const confirmInvalid = !!confirm && password !== confirm

  return (
    <Center minH="100vh" bg="gray.50" px={4} py={8}>
      <Card maxW="440px" w="full" boxShadow="lg" borderRadius="2xl">
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
              <Heading size="lg">注册账号</Heading>
              <Text fontSize="sm" color="gray.500">
                注册后需管理员批准才能登录
              </Text>
            </VStack>

            <Stack spacing={4} w="full">
              <FormControl isRequired isInvalid={usernameInvalid}>
                <FormLabel fontSize="sm">用户名</FormLabel>
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="3-32 字符, 字母数字下划线"
                  size="lg"
                  autoFocus
                  isDisabled={loading}
                />
                {usernameInvalid && (
                  <FormErrorMessage>
                    用户名 3-32 字符, 仅支持字母、数字、下划线、连字符
                  </FormErrorMessage>
                )}
              </FormControl>
              <FormControl>
                <FormLabel fontSize="sm">邮箱 (选填)</FormLabel>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="用于接收通知"
                  size="lg"
                  isDisabled={loading}
                />
              </FormControl>
              <FormControl isRequired>
                <FormLabel fontSize="sm">密码</FormLabel>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="8 字符以上"
                  size="lg"
                  isDisabled={loading}
                />
              </FormControl>
              <FormControl isRequired isInvalid={confirmInvalid}>
                <FormLabel fontSize="sm">确认密码</FormLabel>
                <Input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="再次输入"
                  size="lg"
                  isDisabled={loading}
                />
                {confirmInvalid && (
                  <FormErrorMessage>两次密码不一致</FormErrorMessage>
                )}
              </FormControl>
            </Stack>

            {/* Turnstile widget */}
            <Box ref={turnstileRef} w="full" />

            <Button
              colorScheme="brand"
              size="lg"
              w="full"
              onClick={handleSubmit}
              isLoading={loading}
              loadingText="注册中"
              isDisabled={!turnstileToken}
            >
              注册
            </Button>

            <Text fontSize="sm" color="gray.600" textAlign="center">
              已有账号?{' '}
              <Link
                as={RouterLink}
                to="/login"
                color="brand.600"
                fontWeight="semibold"
              >
                登录
              </Link>
            </Text>
          </VStack>
        </CardBody>
      </Card>
    </Center>
  )
}
