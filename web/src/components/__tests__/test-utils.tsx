// 共享 test wrapper: ChakraProvider 提供 emotion + Chakra UI theme 上下文
//   - 多个组件测试 (AdminUsersPage / LoginPage / 等) 复用同一个 provider
//   - 行为接近浏览器: 真实 ChakraProvider, 不 stub Chakra 渲染
import { ChakraProvider } from '@chakra-ui/react'
import type { ReactElement } from 'react'

export function renderWithChakra(ui: ReactElement) {
  return <ChakraProvider>{ui}</ChakraProvider>
}
