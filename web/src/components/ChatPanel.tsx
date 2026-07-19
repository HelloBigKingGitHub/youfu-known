// 问答面板 - 现代 SaaS 风格
// 气泡式问答 (用户右对齐蓝色, AI 左对齐灰色)
// 输入框: Textarea + 内嵌发送按钮 + focus-withen 蓝色光晕
// Enter 发送, Shift+Enter 换行, 自动滚到底部 (除非用户向上滚)
import {
  Box,
  Button,
  Flex,
  HStack,
  IconButton,
  Spinner,
  Text,
  Textarea,
  useToast,
  VStack,
} from '@chakra-ui/react'
import { ArrowUpIcon, DeleteIcon } from '@chakra-ui/icons'
import { useEffect, useRef, useState } from 'react'
import type { ChatTurn } from '../types'
import { api, ApiError } from '../api'
import { CitationPanel } from './CitationPanel'

interface Props {
  kbId: string
}

const MAX_TEXTAREA_HEIGHT = 120

export function ChatPanel({ kbId }: Props) {
  const [history, setHistory] = useState<ChatTurn[]>([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const toast = useToast()

  // 自动滚到底部 (除非用户手动向上滚)
  const [autoScroll, setAutoScroll] = useState(true)
  useEffect(() => {
    if (autoScroll && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [history, autoScroll])

  // 检测用户是否手动向上滚 → 关掉 autoScroll
  const onScroll = () => {
    if (!listRef.current) return
    const el = listRef.current
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 20
    setAutoScroll(atBottom)
  }

  const scrollToBottom = () => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
      setAutoScroll(true)
    }
  }

  // Textarea 自适应高度
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    const next = Math.min(ta.scrollHeight, MAX_TEXTAREA_HEIGHT)
    ta.style.height = `${next}px`
  }, [question])

  const handleSend = async () => {
    const q = question.trim()
    if (!q || sending) return

    const turnId = `t-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setSending(true)
    setQuestion('')
    setAutoScroll(true)
    setHistory((h) => [
      ...h,
      { id: turnId, question: q, answer: '', citations: [], createdAt: Date.now() },
    ])

    try {
      const resp = await api.chat(kbId, q)
      setHistory((h) =>
        h.map((t) =>
          t.id === turnId
            ? { ...t, answer: resp.answer, citations: resp.citations }
            : t,
        ),
      )
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '问答失败'
      setHistory((h) =>
        h.map((t) => (t.id === turnId ? { ...t, error: msg } : t)),
      )
      toast({ title: '问答失败', description: msg, status: 'error', duration: 4000 })
    } finally {
      setSending(false)
      textareaRef.current?.focus()
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <Box
      bg="white"
      borderRadius="xl"
      border="1px"
      borderColor="surface.border"
      boxShadow="sm"
      p={{ base: 3, md: 4 }}
    >
      {/* Header */}
      <Flex justify="space-between" align="center" mb={3}>
        <Text fontWeight="semibold" color="gray.700">
          问答
        </Text>
        {history.length > 0 && (
          <IconButton
            aria-label="清空问答"
            icon={<DeleteIcon />}
            size="xs"
            variant="ghost"
            colorScheme="red"
            onClick={() => {
              if (window.confirm('确定清空所有问答记录?')) {
                setHistory([])
              }
            }}
          />
        )}
      </Flex>

      {/* 历史区 */}
      <Box
        ref={listRef}
        onScroll={onScroll}
        maxH={{ base: '50vh', md: '420px' }}
        overflowY="auto"
        mb={3}
        borderRadius="lg"
        bg="surface.sunken"
        border="1px"
        borderColor="surface.border"
        p={{ base: 3, md: 4 }}
        position="relative"
      >
        {history.length === 0 ? (
          <Flex align="center" justify="center" direction="column" py={{ base: 8, md: 10 }} gap={2}>
            <Text fontSize={{ base: '2xl', md: '3xl' }}>💬</Text>
            <Text color="gray.500" fontSize="sm" textAlign="center">
              还没有问答记录
            </Text>
            <Text color="gray.400" fontSize="xs" textAlign="center">
              在下方输入问题试试
            </Text>
          </Flex>
        ) : (
          <VStack align="stretch" spacing={4}>
            {history.map((t) => (
              <Box key={t.id}>
                {/* 用户问题 - 右对齐蓝色气泡 */}
                <Flex justify="flex-end" mb={2}>
                  <Box
                    bg="brand.500"
                    color="white"
                    px={3}
                    py={2}
                    borderRadius="2xl"
                    borderBottomRightRadius="sm"
                    maxW="85%"
                    boxShadow="xs"
                  >
                    <Text fontSize="sm" whiteSpace="pre-wrap" wordBreak="break-word">
                      {t.question}
                    </Text>
                  </Box>
                </Flex>
                {/* AI 回答 - 左对齐灰色气泡 */}
                <Flex justify="flex-start">
                  <Box
                    bg="white"
                    color="gray.800"
                    border="1px"
                    borderColor="surface.border"
                    px={3}
                    py={2}
                    borderRadius="2xl"
                    borderBottomLeftRadius="sm"
                    maxW="85%"
                    boxShadow="xs"
                  >
                    {t.error ? (
                      <Text fontSize="sm" color="red.500">
                        {t.error}
                      </Text>
                    ) : t.answer ? (
                      <>
                        <Text fontSize="sm" whiteSpace="pre-wrap" wordBreak="break-word">
                          {t.answer}
                        </Text>
                        <CitationPanel citations={t.citations} />
                      </>
                    ) : (
                      <HStack spacing={2}>
                        <Spinner size="xs" color="brand.500" />
                        <Text fontSize="sm" color="gray.500">
                          思考中...
                        </Text>
                      </HStack>
                    )}
                  </Box>
                </Flex>
              </Box>
            ))}
          </VStack>
        )}
        {!autoScroll && history.length > 0 && (
          <IconButton
            aria-label="滚到底部"
            icon={<span style={{ fontSize: 18 }}>↓</span>}
            size="sm"
            colorScheme="brand"
            borderRadius="full"
            position="absolute"
            bottom={3}
            right={3}
            boxShadow="md"
            onClick={scrollToBottom}
          />
        )}
      </Box>

      {/* 输入区: 移动端垂直堆叠 (textarea + 按钮行) / 桌面横向 (textarea 左, 按钮右)
          永远对齐 baseline, 修复 iPhone Pro Max 按钮错位 */}
      <Flex
        direction={{ base: 'column', md: 'row' }}
        align={{ base: 'stretch', md: 'flex-end' }}
        gap={2}
        bg="surface.sunken"
        borderRadius="xl"
        border="1px"
        borderColor="surface.border"
        p={2}
        transition="all 0.15s"
        _focusWithin={{
          borderColor: 'brand.300',
          boxShadow: '0 0 0 3px rgba(59, 130, 246, 0.12)',
        }}
      >
        <Textarea
          ref={textareaRef}
          placeholder="输入你的问题... (Enter 发送, Shift+Enter 换行)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          isDisabled={sending}
          flex={1}
          resize="none"
          rows={1}
          minH="40px"
          maxH={`${MAX_TEXTAREA_HEIGHT}px`}
          border="none"
          bg="transparent"
          fontSize="sm"
          py={2}
          _focus={{ boxShadow: 'none' }}
          _focusVisible={{ boxShadow: 'none' }}
          overflow="auto"
          css={{
            scrollbarWidth: 'none',
            '&::-webkit-scrollbar': { display: 'none' },
          }}
        />
        <Flex
          justify={{ base: 'space-between', md: 'flex-end' }}
          align="center"
          w={{ base: 'full', md: 'auto' }}
          gap={2}
        >
          <Text
            fontSize="xs"
            color="gray.400"
            display={{ base: 'block', md: 'none' }}
          >
            Enter 发送 · Shift+Enter 换行
          </Text>
          <Button
            colorScheme="brand"
            size="md"
            onClick={handleSend}
            isLoading={sending}
            isDisabled={!question.trim()}
            leftIcon={<ArrowUpIcon />}
            px={4}
            minH="40px"
          >
            发送
          </Button>
        </Flex>
      </Flex>
    </Box>
  )
}
