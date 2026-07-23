import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Box,
  Button,
  HStack,
  IconButton,
  Input,
  Text,
  VStack,
} from '@chakra-ui/react'
import { CheckIcon, RepeatIcon } from '@chakra-ui/icons'

interface Props {
  onVerify: (verified: boolean) => void
  length?: number
  noise?: 'medium' | 'high'
}

const CHARSET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
const MAX_ATTEMPTS = 3
const FONT_FAMILIES = [
  '"Trebuchet MS"',
  '"Lucida Sans"',
  '"Courier New"',
  '"Georgia"',
  'Verdana',
  'Impact',
  'monospace',
]

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min)
}

function pick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function generateCode(length: number): string {
  let s = ''
  for (let i = 0; i < length; i++) {
    s += CHARSET[Math.floor(Math.random() * CHARSET.length)]
  }
  return s
}

export function Captcha({ onVerify, length = 5, noise = 'medium' }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [code, setCode] = useState('')
  const [userInput, setUserInput] = useState('')
  const [attemptsLeft, setAttemptsLeft] = useState(MAX_ATTEMPTS)
  const [verified, setVerified] = useState(false)
  const [error, setError] = useState('')

  const draw = useCallback(
    (text: string) => {
      const canvas = canvasRef.current
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      const W = canvas.width
      const H = canvas.height

      const gradient = ctx.createLinearGradient(0, 0, W, H)
      gradient.addColorStop(0, '#fafbfd')
      gradient.addColorStop(1, '#e8edf5')
      ctx.fillStyle = gradient
      ctx.fillRect(0, 0, W, H)

      const palette = [
        '#1e3a8a',
        '#5b21b6',
        '#9d174d',
        '#166534',
        '#7c2d12',
        '#854d0e',
        '#0c4a6e',
      ]
      const slotW = W / (text.length + 1)
      for (let i = 0; i < text.length; i++) {
        const ch = text[i]
        const x = slotW * (i + 0.5) + rand(-6, 6)
        const y = H / 2 + rand(-8, 8)
        const angle = rand(-0.35, 0.35)
        const fontSize = 26 + Math.floor(rand(0, 10))
        const fontFamily = pick(FONT_FAMILIES)

        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(angle)
        ctx.font = `bold ${fontSize}px ${fontFamily}, sans-serif`
        ctx.textBaseline = 'middle'
        ctx.textAlign = 'center'
        ctx.fillStyle = pick(palette)
        ctx.shadowColor = 'rgba(0,0,0,0.18)'
        ctx.shadowBlur = 2
        ctx.fillText(ch, 0, 0)
        ctx.restore()
      }

      const lineCount = noise === 'high' ? 6 : 3
      for (let i = 0; i < lineCount; i++) {
        const r = Math.floor(rand(40, 180))
        const g = Math.floor(rand(40, 180))
        const b = Math.floor(rand(40, 180))
        ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${rand(0.2, 0.5)})`
        ctx.lineWidth = rand(0.8, 2)
        ctx.beginPath()
        ctx.moveTo(rand(0, W), rand(0, H))
        ctx.bezierCurveTo(
          rand(0, W), rand(0, H),
          rand(0, W), rand(0, H),
          rand(0, W), rand(0, H),
        )
        ctx.stroke()
      }

      const dotCount = noise === 'high' ? 70 : 35
      for (let i = 0; i < dotCount; i++) {
        const r = Math.floor(rand(30, 120))
        const g = Math.floor(rand(30, 120))
        const b = Math.floor(rand(30, 120))
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${rand(0.2, 0.5)})`
        ctx.beginPath()
        ctx.arc(rand(0, W), rand(0, H), rand(0.8, 2), 0, Math.PI * 2)
        ctx.fill()
      }

      const circleCount = noise === 'high' ? 4 : 2
      for (let i = 0; i < circleCount; i++) {
        const r = Math.floor(rand(40, 180))
        const g = Math.floor(rand(40, 180))
        const b = Math.floor(rand(40, 180))
        ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.45)`
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.arc(rand(0, W), rand(0, H), rand(8, 22), 0, Math.PI * 2)
        ctx.stroke()
      }
    },
    [noise],
  )

  const regenerate = useCallback(() => {
    setCode(generateCode(length))
    setUserInput('')
    setError('')
    setAttemptsLeft(MAX_ATTEMPTS)
    setVerified(false)
    onVerify(false)
  }, [length, onVerify])

  useEffect(() => {
    if (!code) {
      setCode(generateCode(length))
      return
    }
    draw(code)
  }, [code, length, draw])

  useEffect(() => {
    if (import.meta.env.DEV) {
      ;(window as unknown as { __captchaCode?: () => string }).__captchaCode = () => code
    }
  }, [code])

  const handleVerify = () => {
    if (verified || !userInput) return
    const userUpper = userInput.toUpperCase().trim()
    if (userUpper === code) {
      setVerified(true)
      setError('')
      onVerify(true)
      return
    }
    const left = attemptsLeft - 1
    setAttemptsLeft(left)
    setUserInput('')
    if (left <= 0) {
      setError('验证失败, 已自动刷新')
      regenerate()
    } else {
      setError(`验证码错误, 还剩 ${left} 次机会`)
    }
  }

  const borderColor = verified
    ? 'green.400'
    : error
      ? 'red.300'
      : 'gray.300'

  return (
    <VStack align="stretch" spacing={2}>
      <HStack spacing={2} align="center">
        <Box position="relative" flex={1}>
          <canvas
            ref={canvasRef}
            width={200}
            height={60}
            data-testid="captcha-canvas"
            role="img"
            aria-label={`验证码图片, 共 ${length} 个字符`}
            style={{
              border: '2px solid',
              borderColor: `var(--chakra-colors-${borderColor.replace('.', '-')})`,
              borderRadius: '8px',
              cursor: 'pointer',
              width: '100%',
              maxWidth: '200px',
              transition: 'border-color 0.2s',
              display: 'block',
            }}
            onClick={regenerate}
            title="点击刷新验证码"
          />
          {verified && (
            <Box
              position="absolute"
              right={2}
              top={2}
              bg="green.500"
              color="white"
              borderRadius="full"
              w="20px"
              h="20px"
              display="flex"
              alignItems="center"
              justifyContent="center"
              pointerEvents="none"
            >
              <CheckIcon boxSize="12px" />
            </Box>
          )}
        </Box>
        <IconButton
          aria-label="刷新验证码"
          icon={<RepeatIcon />}
          onClick={regenerate}
          variant="outline"
          minH="44px"
          minW="44px"
          data-testid="captcha-refresh"
        />
      </HStack>
      <HStack spacing={2}>
        <Input
          placeholder={`请输入验证码 (${length}位字符)`}
          value={userInput}
          onChange={(e) =>
            setUserInput(e.target.value.toUpperCase().slice(0, length))
          }
          onKeyDown={(e) => e.key === 'Enter' && handleVerify()}
          isDisabled={verified}
          isInvalid={!!error}
          size="md"
          maxLength={length}
          autoComplete="off"
          spellCheck={false}
          data-testid="captcha-input"
        />
        <Button
          onClick={handleVerify}
          isDisabled={verified || !userInput}
          colorScheme={verified ? 'green' : 'blue'}
          size="md"
          minH="44px"
          data-testid="captcha-verify"
        >
          {verified ? '已通过' : '验证'}
        </Button>
      </HStack>
      {error && (
        <Text fontSize="xs" color="red.500" data-testid="captcha-error">
          {error}
        </Text>
      )}
      {verified && (
        <Text fontSize="xs" color="green.500" data-testid="captcha-success">
          ✓ 人机验证通过
        </Text>
      )}
    </VStack>
  )
}