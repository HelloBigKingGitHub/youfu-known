// 引用列表 - 可展开查看原文片段
import { Badge, Box, Collapse, HStack, IconButton, Text, VStack } from '@chakra-ui/react'
import { ChevronDownIcon, ChevronRightIcon } from '@chakra-ui/icons'
import { useState } from 'react'
import type { Citation } from '../types'

interface Props {
  citations: Citation[]
}

export function CitationPanel({ citations }: Props) {
  if (citations.length === 0) return null

  return (
    <Box mt={3} bg="gray.50" borderRadius="md" p={3} border="1px" borderColor="gray.200">
      <Text fontSize="xs" fontWeight="bold" color="gray.500" mb={2}>
        引用 ({citations.length})
      </Text>
      <VStack align="stretch" spacing={1}>
        {citations.map((c) => (
          <CitationItem key={c.n} citation={c} />
        ))}
      </VStack>
    </Box>
  )
}

function CitationItem({ citation: c }: { citation: Citation }) {
  const [open, setOpen] = useState(false)
  return (
    <Box>
      <HStack
        spacing={2}
        cursor="pointer"
        onClick={() => setOpen(!open)}
        _hover={{ bg: 'gray.100' }}
        borderRadius="sm"
        px={2}
        py={{ base: 2, md: 1 }}
        flexWrap="wrap"
        minH={{ base: '44px', md: 'auto' }}
      >
        <IconButton
          aria-label={open ? '收起' : '展开'}
          icon={open ? <ChevronDownIcon /> : <ChevronRightIcon />}
          size="xs"
          variant="ghost"
        />
        <Badge colorScheme="brand">[{c.n}]</Badge>
        <Text fontSize="sm" color="gray.700" noOfLines={1} flex={1}>
          {c.doc_filename}
          <Text as="span" color="gray.400" fontSize="xs">
            {' '}#chunk{c.chunk_idx}
          </Text>
        </Text>
        <Text fontSize="xs" color="gray.500">
          score: {c.score.toFixed(2)}
        </Text>
      </HStack>
      <Collapse in={open} animateOpacity>
        <Box
          mt={1}
          ml={9}
          p={2}
          bg="white"
          borderRadius="sm"
          border="1px"
          borderColor="gray.200"
          fontSize="sm"
          color="gray.700"
          whiteSpace="pre-wrap"
          maxH="240px"
          overflowY="auto"
        >
          {c.text || '(无原文)'}
        </Box>
      </Collapse>
    </Box>
  )
}