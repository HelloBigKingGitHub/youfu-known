// 未选 KB 时显示的空状态
import { Center, Text, VStack, Icon } from '@chakra-ui/react'
import { ChevronRightIcon } from '@chakra-ui/icons'

export function EmptyState() {
  return (
    <Center h="100%" flex={1} bg="gray.50" p={6}>
      <VStack spacing={3} maxW="500px">
        <Icon as={ChevronRightIcon} boxSize={{ base: 8, md: 10 }} color="gray.400" />
        <Text fontSize={{ base: 'md', md: 'lg' }} color="gray.500" textAlign="center">
          请在左侧新建或选择一个知识库
        </Text>
        <Text fontSize="sm" color="gray.400" textAlign="center">
          上传文档后即可基于知识库内容问答
        </Text>
      </VStack>
    </Center>
  )
}