// 引用列表 - 整体默认折叠, 点按钮展开所有引用项
import { Badge, Box, Button, Collapse, HStack, IconButton, Text, VStack } from '@chakra-ui/react'
import { ChevronDownIcon, ChevronRightIcon } from '@chakra-ui/icons'
import { useState } from 'react'
import type { Citation } from '../types'

interface Props {
  citations: Citation[]
}

export function CitationPanel({ citations }: Props) {
  const [expanded, setExpanded] = useState(false)
  if (citations.length === 0) return null

  return (
    <Box mt={3} bg="surface.sunken" borderRadius="lg" border="1px" borderColor="surface.border" overflow="hidden">
      <Button
        variant="ghost"
        size="sm"
        w="full"
        justifyContent="flex-start"
        leftIcon={expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
        onClick={() => setExpanded(!expanded)}
        fontWeight="semibold"
        color="gray.600"
        borderRadius={0}
        px={3}
        py={2}
        _hover={{ bg: 'gray.100' }}
      >
        引用 ({citations.length})
      </Button>
      <Collapse in={expanded} animateOpacity unmountOnExit>
        <VStack align="stretch" spacing={1} px={3} pb={3}>
          {citations.map((c) => (
            <CitationItem key={c.n} citation={c} />
          ))}
        </VStack>
      </Collapse>
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