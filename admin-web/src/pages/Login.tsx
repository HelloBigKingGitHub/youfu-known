import {
  Alert,
  AlertIcon,
  Button,
  FormControl,
  FormLabel,
  Heading,
  Input,
  InputGroup,
  InputRightElement,
  Stack,
  Text,
} from '@chakra-ui/react'
import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { formatApiError } from '../api'

export function LoginPage() {
  const { login, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const params = new URLSearchParams(location.search)
  const next = params.get('next') || '/admin'

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const user = await login(username.trim(), password)
      if (user.role !== 'admin') {
        // Session is now set on the server but the role check fails.
        // Drop the session immediately so the SPA doesn't briefly
        // render with a member user in auth state.
        await logout()
        setError('当前账号无管理后台权限')
        return
      }
      navigate(next, { replace: true })
    } catch (err: unknown) {
      setError(formatApiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="登录" noValidate>
      <Stack spacing={5}>
      <Heading
        as="h1"
        fontFamily="heading"
        fontSize="2xl"
        color="whiteAlpha.900"
        textAlign="center"
      >
        管理员登录
      </Heading>
      {error && (
        <Alert status="error" variant="left-accent" borderRadius="md">
          <AlertIcon />
          <Text fontSize="sm">{error}</Text>
        </Alert>
      )}
      <FormControl isRequired>
        <FormLabel fontSize="sm" color="whiteAlpha.700">
          用户名
        </FormLabel>
        <Input
          name="username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          bg="ink.800"
          borderColor="whiteAlpha.200"
          _hover={{ borderColor: 'copper.400' }}
          _focusVisible={{ borderColor: 'signal.300', boxShadow: 'none' }}
        />
      </FormControl>
      <FormControl isRequired>
        <FormLabel fontSize="sm" color="whiteAlpha.700">
          密码
        </FormLabel>
        <InputGroup>
          <Input
            name="password"
            type={show ? 'text' : 'password'}
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            bg="ink.800"
            borderColor="whiteAlpha.200"
            _hover={{ borderColor: 'copper.400' }}
            _focusVisible={{ borderColor: 'signal.300', boxShadow: 'none' }}
          />
          <InputRightElement width="4.5rem">
            <Button
              h="1.75rem"
              size="sm"
              variant="ghost"
              onClick={() => setShow((s) => !s)}
              aria-label={show ? '隐藏密码' : '显示密码'}
            >
              {show ? '隐藏' : '显示'}
            </Button>
          </InputRightElement>
        </InputGroup>
      </FormControl>
      <Button
        type="submit"
        colorScheme="signal"
        isLoading={busy}
        loadingText="登录中"
        size="lg"
        fontWeight="semibold"
      >
        登录
      </Button>
      </Stack>
    </form>
  )
}
