// Tab 2: 智能问答 - 从 Outlet context 拿 kbId, 复用 ChatPanel
import { Box, Text } from '@chakra-ui/react'
import { useOutletContext } from 'react-router-dom'
import type { KB } from '../types'
import { ChatPanel } from './ChatPanel'

interface KBOutletContext {
  kb: KB
}

export function KBChatTab() {
  const { kb } = useOutletContext<KBOutletContext>()

  return (
    <Box>
      <Text fontSize="sm" color="gray.500" mb={4} textAlign="center">
        基于本知识库内容回答, 引用可点击展开
      </Text>
      <ChatPanel kbId={kb.id} />
    </Box>
  )
}
