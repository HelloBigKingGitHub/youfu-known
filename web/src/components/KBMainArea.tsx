// 选中 KB 后的主区域: 上传 + 文档列表 + 问答
// 响应式: 移动端 padding 减小, heading 字号减小
import { Box, Flex, Heading, Text, VStack } from '@chakra-ui/react'
import { useCallback, useEffect, useState } from 'react'
import type { Document, KB } from '../types'
import { api, ApiError } from '../api'
import { useToast } from '@chakra-ui/react'
import { Uploader } from './Uploader'
import { DocumentList } from './DocumentList'
import { ChatPanel } from './ChatPanel'

interface Props {
  kbId: string
}

export function KBMainArea({ kbId }: Props) {
  const [kb, setKB] = useState<KB | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const toast = useToast()

  const refresh = useCallback(async () => {
    try {
      const detail = await api.getKB(kbId)
      setKB(detail.kb)
      setDocuments(detail.documents)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '加载失败'
      toast({ title: '加载失败', description: msg, status: 'error', duration: 3000 })
    } finally {
      setLoading(false)
    }
  }, [kbId, toast])

  useEffect(() => {
    setLoading(true)
    refresh()
  }, [refresh])

  if (loading || !kb) {
    return (
      <Flex flex={1} align="center" justify="center" h="100%">
        <Text color="gray.500">加载中...</Text>
      </Flex>
    )
  }

  return (
    <Box flex={1} h="100%" overflowY="auto" p={{ base: 3, md: 5, lg: 6 }} bg="gray.50">
      <VStack align="stretch" spacing={{ base: 3, md: 5 }} maxW="960px" mx="auto">
        <Box>
          <Heading size={{ base: 'md', md: 'lg' }}>{kb.name}</Heading>
          {kb.description && (
            <Text color="gray.500" mt={1} fontSize={{ base: 'sm', md: 'md' }}>
              {kb.description}
            </Text>
          )}
          <Text fontSize="sm" color="gray.400" mt={2}>
            {kb.doc_count} 文档 · {kb.chunk_count} chunks
          </Text>
        </Box>

        <Uploader kbId={kbId} onUploaded={refresh} />

        <DocumentList kbId={kbId} documents={documents} onChange={refresh} />

        <ChatPanel kbId={kbId} />
      </VStack>
    </Box>
  )
}
