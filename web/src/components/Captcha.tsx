import { useEffect, useRef, useState, useCallback } from 'react'
import { Box, Button, HStack, Input, Text, VStack, useToast } from '@chakra-ui/react'
import { RepeatIcon } from '@chakra-ui/icons'

interface Props {
  onChange: (token: string) => void  // 通过验证后回调 (token 简单就行, 实际后端只看 verify endpoint)
  length?: number  // 默认 5
}

const CHARSET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  // 排除易混的 0/O/1/I/L
const MAX_ATTEMPTS = 3

export function Captcha({ onChange, length = 5 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [code, setCode] = useState('')
  const [userInput, setUserInput] = useState('')
  const [attemptsLeft, setAttemptsLeft] = useState(MAX_ATTEMPTS)
  const [verified, setVerified] = useState(false)
  const [error, setError] = useState('')
  const toast = useToast()

  // 生成随机码 + 画 canvas
  const generate = useCallback(() => {
    let s = ''
    for (let i = 0; i < length; i++) {
      s += CHARSET[Math.floor(Math.random() * CHARSET.length)]
    }
    setCode(s)
    setUserInput('')
    setError('')
    setAttemptsLeft(MAX_ATTEMPTS)
    setVerified(false)
    onChange('')
    // 等下次 tick 画
    setTimeout(() => draw(s), 50)
  }, [length, onChange])

  const draw = (text: string) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const w = canvas.width
    const h = canvas.height
    // 背景
    const gradient = ctx.createLinearGradient(0, 0, w, h)
    gradient.addColorStop(0, '#f0f7ff')
    gradient.addColorStop(1, '#dcecfe')
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, w, h)
    // 字符
    const charW = w / (text.length + 1)
    ctx.font = 'bold 32px sans-serif'
    ctx.textBaseline = 'middle'
    for (let i = 0; i < text.length; i++) {
      const ch = text[i]
      const x = charW * (i + 0.5)
      const y = h / 2 + (Math.random() - 0.5) * 6
      const angle = (Math.random() - 0.5) * 0.5
      ctx.save()
      ctx.translate(x, y)
      ctx.rotate(angle)
      // 随机颜色 (深色, 不易混背景)
      const colors = ['#1e3a8a', '#5b21b6', '#9d174d', '#166534', '#7c2d12']
      ctx.fillStyle = colors[Math.floor(Math.random() * colors.length)]
      ctx.fillText(ch, 0, 0)
      ctx.restore()
    }
    // 干扰线
    for (let i = 0; i < 4; i++) {
      ctx.strokeStyle = `rgba(0,0,0,${0.1 + Math.random() * 0.15})`
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(Math.random() * w, Math.random() * h)
      ctx.bezierCurveTo(
        Math.random() * w, Math.random() * h,
        Math.random() * w, Math.random() * h,
        Math.random() * w, Math.random() * h
      )
      ctx.stroke()
    }
    // 干扰点
    for (let i = 0; i < 30; i++) {
      ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.2})`
      ctx.fillRect(Math.random() * w, Math.random() * h, 2, 2)
    }
  }

  useEffect(() => {
    generate()
  }, [generate])

  const handleVerify = () => {
    if (verified) return
    if (userInput.toUpperCase() === code) {
      setVerified(true)
      setError('')
      onChange('verified-' + Date.now())  // 给后端的伪 token
      toast({ title: '验证成功', status: 'success', duration: 1500, position: 'top' })
    } else {
      const left = attemptsLeft - 1
      setAttemptsLeft(left)
      setUserInput('')
      if (left <= 0) {
        setError('验证失败, 已刷新')
        generate()
      } else {
        setError(`错误, 还剩 ${left} 次机会`)
      }
    }
  }

  return (
    <VStack align="stretch" spacing={2}>
      <HStack spacing={2}>
        <Box position="relative" flex={1}>
          <canvas
            ref={canvasRef}
            width={200}
            height={56}
            style={{
              border: '1px solid',
              borderColor: verified ? 'green.300' : 'gray.300',
              borderRadius: '8px',
              cursor: 'pointer',
              width: '100%',
              maxWidth: '200px',
            }}
            onClick={generate}
            title="点击刷新"
          />
          {verified && (
            <Box position="absolute" right={2} top={2}>
              <Text fontSize="xs" color="green.500" fontWeight="bold">✓</Text>
            </Box>
          )}
        </Box>
        <Button
          size="md"
          variant="ghost"
          onClick={generate}
          aria-label="刷新验证码"
          minH="44px"
          minW="44px"
        >
          <RepeatIcon />
        </Button>
      </HStack>
      <HStack spacing={2}>
        <Input
          placeholder={`输入验证码 (${length}位字符)`}
          value={userInput}
          onChange={e => setUserInput(e.target.value.toUpperCase().slice(0, length))}
          onKeyDown={e => e.key === 'Enter' && handleVerify()}
          isDisabled={verified}
          isInvalid={!!error}
          size="md"
          maxLength={length}
        />
        <Button
          onClick={handleVerify}
          isDisabled={verified || !userInput}
          colorScheme={verified ? 'green' : 'blue'}
          size="md"
          minH="44px"
        >
          {verified ? '✓' : '验证'}
        </Button>
      </HStack>
      {error && (
        <Text fontSize="xs" color="red.500">{error}</Text>
      )}
      {verified && (
        <Text fontSize="xs" color="green.500">✓ 人机验证通过</Text>
      )}
    </VStack>
  )
}
