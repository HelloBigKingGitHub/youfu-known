// 顶栏 - 桌面/移动端统一, 用户信息在右上角
import {
  Avatar,
  Box,
  Button,
  Flex,
  HStack,
  IconButton,
  Menu,
  MenuButton,
  MenuDivider,
  MenuItem,
  MenuList,
  Text,
} from '@chakra-ui/react'
import {
  ChevronDownIcon,
  ExternalLinkIcon,
  HamburgerIcon,
  LockIcon,
  SettingsIcon,
} from '@chakra-ui/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { User } from '../types'

interface Props {
  user: User | null
  currentKBName?: string
  onToggleSidebar: () => void
  onLogout: () => void
  isMobile: boolean
}

export function TopBar({
  user,
  currentKBName,
  onToggleSidebar,
  onLogout,
  isMobile,
}: Props) {
  const navigate = useNavigate()

  const handleLogout = async () => {
    try {
      await api.logout()
    } finally {
      onLogout()
      navigate('/login', { replace: true })
    }
  }

  return (
    <Flex
      h="56px"
      align="center"
      px={{ base: 3, md: 4 }}
      bg="white"
      borderBottom="1px"
      borderColor="gray.200"
      position="sticky"
      top={0}
      zIndex={20}
      gap={3}
      flexShrink={0}
    >
      {isMobile && (
        <IconButton
          aria-label="打开侧栏"
          icon={<HamburgerIcon />}
          variant="ghost"
          onClick={onToggleSidebar}
          minW="44px"
          minH="44px"
        />
      )}
      <Text fontSize="md" fontWeight="bold" color="brand.700" noOfLines={1}>
        youfu-known
      </Text>
      {currentKBName && !isMobile && (
        <Text
          fontSize="sm"
          color="gray.500"
          noOfLines={1}
          flex={1}
          textAlign="center"
        >
          {currentKBName}
        </Text>
      )}
      <Box flex={1} />
      {user ? (
        <Menu>
          <MenuButton
            as={Button}
            rightIcon={<ChevronDownIcon />}
            variant="ghost"
            size="sm"
            minH="44px"
          >
            <HStack spacing={2}>
              <Avatar size="xs" name={user.username} />
              <Text fontSize="sm">{user.username}</Text>
            </HStack>
          </MenuButton>
          <MenuList>
            <MenuItem isDisabled>
              <Text fontSize="xs" color="gray.500">
                {user.role === 'admin' ? '👑 管理员' : '👤 成员'}
              </Text>
            </MenuItem>
            <MenuDivider />
            <MenuItem
              icon={<LockIcon />}
              onClick={() => navigate('/change-password')}
            >
              修改密码
            </MenuItem>
            {user?.role === 'admin' && (
              <MenuItem
                icon={<SettingsIcon />}
                onClick={() => navigate('/admin/users')}
              >
                用户管理
              </MenuItem>
            )}
            <MenuItem
              icon={<ExternalLinkIcon />}
              color="red.500"
              onClick={handleLogout}
            >
              登出
            </MenuItem>
          </MenuList>
        </Menu>
      ) : (
        <Button
          size="sm"
          colorScheme="brand"
          onClick={() => navigate('/login')}
        >
          登录
        </Button>
      )}
    </Flex>
  )
}
