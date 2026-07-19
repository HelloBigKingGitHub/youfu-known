// Tab 1: 知识库管理 (上传 + 文档列表)
// 从 Outlet context 拿 documents + refresh + kbId, 复用现有 Uploader / DocumentList
import { Box, Heading, Text, VStack } from '@chakra-ui/react'
import { useOutletContext } from 'react-router-dom'
import type { Document, KB } from '../types'
import { Uploader } from './Uploader'
import { DocumentList } from './DocumentList'

interface KBOutletContext {
  kb: KB
  documents: Document[]
  refresh: () => void
}

export function KBManageTab() {
  const { kb, documents, refresh } = useOutletContext<KBOutletContext>()

  return (
    <VStack align="stretch" spacing={{ base: 4, md: 5 }}>
      <Box>
        <Heading as="h2" size={{ base: 'sm', md: 'md' }} mb={1} color="gray.700">
          上传文档
        </Heading>
        <Text fontSize="sm" color="gray.500">
          拖文件到下方区域, 或点击选择文件。上传完成后后台会自动解析和分块。
        </Text>
      </Box>
      <Uploader kbId={kb.id} onUploaded={refresh} />

      <Box>
        <Heading as="h2" size={{ base: 'sm', md: 'md' }} mb={1} color="gray.700">
          文档列表
        </Heading>
        <Text fontSize="sm" color="gray.500">
          {documents.length > 0
            ? `共 ${documents.length} 个文档, 文档就绪后即可在问答页提问`
            : '还没有文档, 上传后会显示在这里'}
        </Text>
      </Box>
      <DocumentList kbId={kb.id} documents={documents} onChange={refresh} />
    </VStack>
  )
}
