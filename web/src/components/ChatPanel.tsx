// 问答面板 - 输入问题 + 答案 + 引用
import {
  Box,
  Button,
  Flex,
  HStack,
  IconButton,
  Input,
  Spinner,
  Text,
  useToast,
  VStack,
} from '@chakra-ui/react'
import { DeleteIcon } from '@chakra-ui/icons'
import { useEffect, useRef, useState } from 'react'
import type { ChatTurn } from '../types'
import { api, ApiError } from '../api'
import { CitationPanel } from './CitationPanel'

interface Props {
  kbId: string
}

export function ChatPanel({ kbId }: Props) {
  const [history, setHistory] = useState<ChatTurn[]>([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const toast = useToast()

  // 新问答追加到末尾, 自动滚到底部 (除非用户已经向上滚去看历史)
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

  const handleSend = async () => {
    const q = question.trim()
    if (!q || sending) return

    const turnId = `t-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setSending(true)
    setQuestion('')
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
      inputRef.current?.focus()
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <Box bg="white" borderRadius="md" border="1px" borderColor="gray.200" p={4}>
      <Flex justify="space-between" align="center" mb={3}>
        <Text fontWeight="semibold">问答</Text>
        <HStack spacing={2}>
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
          <Text fontSize="xs" color="gray.400">
            基于本知识库内容回答, 流式输出开发中
          </Text>
        </HStack>
      </Flex>

      <Box
        ref={listRef}
        onScroll={onScroll}
        maxH="420px"
        overflowY="auto"
        mb={3}
        border="1px"
        borderColor="gray.100"
        borderRadius="md"
        p={3}
        bg="gray.50"
        position="relative"
      >
        {history.length === 0 ? (
          <Text color="gray.400" textAlign="center" py={6}>
            还没有问答记录, 在下方输入问题试试
          </Text>
        ) : (
          <VStack align="stretch" spacing={4}>
            {history.map((t) => (
              <Box key={t.id}>
                <Flex align="center" mb={1}>
                  <Text fontSize="xs" color="brand.600" fontWeight="semibold">
                    Q:
                  </Text>
                  <Text ml={2} fontSize="sm">
                    {t.question}
                  </Text>
                </Flex>
                <Flex align="flex-start">
                  <Text fontSize="xs" color="green.600" fontWeight="semibold" mt={1}>
                    A:
                  </Text>
                  <Box ml={2} flex={1}>
                    {t.error ? (
                      <Text fontSize="sm" color="red.500">
                        {t.error}
                      </Text>
                    ) : t.answer ? (
                      <>
                        <Text fontSize="sm" whiteSpace="pre-wrap">
                          {t.answer}
                        </Text>
                        <CitationPanel citations={t.citations} />
                      </>
                    ) : (
                      <HStack>
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

      <HStack>
        <Input
          ref={inputRef}
          placeholder="输入问题, 回车发送"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          isDisabled={sending}
        />
        <Button
          colorScheme="brand"
          onClick={handleSend}
          isLoading={sending}
          loadingText="发送中"
          isDisabled={!question.trim()}
        >
          发送
        </Button>
      </HStack>
    </Box>
  )
}