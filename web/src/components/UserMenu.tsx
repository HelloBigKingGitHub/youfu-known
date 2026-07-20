// 侧栏顶部用户菜单 - 显示用户名 + 登出/修改密码
import { Button, Menu, MenuButton, MenuDivider, MenuItem, MenuList, Text } from '@chakra-ui/react'
import { ChevronDownIcon, LockIcon } from '@chakra-ui/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { User } from '../types'

interface UserMenuProps {
  user: User | null
  onLogout: () => void
}

export function UserMenu({ user, onLogout }: UserMenuProps) {
  const navigate = useNavigate()
  if (!user) return null

  const handleLogout = async () => {
    try {
      await api.logout()
    } finally {
      onLogout()
      navigate('/login', { replace: true })
    }
  }

  return (
    <Menu>
      <MenuButton
        as={Button}
        rightIcon={<ChevronDownIcon />}
        variant="ghost"
        size="sm"
        w="full"
        justifyContent="space-between"
        minH="44px"
      >
        <Text fontSize="sm" noOfLines={1} textAlign="left">
          👤 {user.username}
        </Text>
      </MenuButton>
      <MenuList>
        <MenuItem icon={<LockIcon />} onClick={() => navigate('/change-password')}>
          修改密码
        </MenuItem>
        <MenuDivider />
        <MenuItem color="red.500" onClick={handleLogout} minH="44px">
          登出
        </MenuItem>
      </MenuList>
    </Menu>
  )
}
