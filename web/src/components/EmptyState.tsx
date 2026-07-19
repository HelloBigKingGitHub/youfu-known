// 未选 KB 时显示的空状态
import { Center, Text, VStack, Icon } from '@chakra-ui/react'
import { ChevronRightIcon } from '@chakra-ui/icons'

export function EmptyState() {
  return (
    <Center h="100vh" flex={1} bg="gray.50">
      <VStack spacing={3}>
        <Icon as={ChevronRightIcon} boxSize={10} color="gray.400" />
        <Text fontSize="lg" color="gray.500">
          请在左侧新建或选择一个知识库
        </Text>
        <Text fontSize="sm" color="gray.400">
          上传文档后即可基于知识库内容问答
        </Text>
      </VStack>
    </Center>
  )
}