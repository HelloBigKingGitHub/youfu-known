import {
  Avatar,
  Box,
  Button,
  Flex,
  HStack,
  Heading,
  Icon,
  Spacer,
  Spinner,
  Text,
  VStack,
} from '@chakra-ui/react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  FiActivity,
  FiBookOpen,
  FiGrid,
  FiLogOut,
  FiSettings,
} from './icons'

interface NavItem {
  to: string
  label: string
  icon: typeof FiGrid
}

// Inline users icon — mirrors the Fi* pattern from ./icons so the
// sidebar menu item can render without modifying the shared module.
const FiUsers = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    width="1em"
    height="1em"
    {...props}
  >
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
)

const NAV: readonly NavItem[] = [
  { to: '/admin', label: '总览', icon: FiGrid },
  { to: '/admin/kbs', label: '知识库', icon: FiBookOpen },
  { to: '/admin/users', label: '用户管理', icon: FiUsers },
  { to: '/admin/audit', label: '审计日志', icon: FiActivity },
  { to: '/admin/settings', label: '系统设置', icon: FiSettings },
]

export function AdminLayout() {
  const { user, loading, logout } = useAuth()
  const navigate = useNavigate()

  if (loading || !user) {
    return (
      <Flex h="100vh" align="center" justify="center" bg="ink.950">
        <Spinner color="signal.400" size="lg" />
      </Flex>
    )
  }

  const handleLogout = async () => {
    await logout()
    navigate('/admin/login', { replace: true })
  }

  return (
    <Flex minH="100vh" bg="ink.950" align="stretch">
      <Box
        as="aside"
        w={{ base: '0', md: '240px' }}
        bg="ink.900"
        borderRightWidth="1px"
        borderColor="whiteAlpha.100"
        py={6}
        px={4}
        display={{ base: 'none', md: 'flex' }}
        flexDirection="column"
        gap={2}
        position="sticky"
        top={0}
        h="100vh"
      >
        <Heading
          fontFamily="heading"
          color="copper.400"
          fontSize="lg"
          letterSpacing="0.05em"
          mb={4}
          px={2}
        >
          youfu-known
        </Heading>
        <Text px={2} color="whiteAlpha.500" fontSize="xs" letterSpacing="0.08em">
          管理后台
        </Text>
        <VStack align="stretch" spacing={1} mt={4}>
          {NAV.map((item) => (
            <AdminNavLink key={item.to} item={item} />
          ))}
        </VStack>
      </Box>
      <Flex flex={1} direction="column" minW={0}>
        <Flex
          as="header"
          h="56px"
          align="center"
          px={6}
          borderBottomWidth="1px"
          borderColor="whiteAlpha.100"
          bg="ink.900"
          gap={3}
        >
          <Text fontSize="sm" color="whiteAlpha.600">
            欢迎回来
          </Text>
          <Spacer />
          <HStack spacing={3}>
            <Text fontSize="sm" color="whiteAlpha.700">
              {user.username}
            </Text>
            <Avatar size="xs" name={user.username} />
            <Button
              size="sm"
              leftIcon={<Icon as={FiLogOut} />}
              variant="ghost"
              onClick={handleLogout}
            >
              登出
            </Button>
          </HStack>
        </Flex>
        <Box as="main" flex={1} p={{ base: 4, md: 8 }} overflow="auto">
          <Outlet />
        </Box>
      </Flex>
    </Flex>
  )
}

function AdminNavLink({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/admin'}
      style={{ textDecoration: 'none' }}
    >
      {({ isActive }) => (
        <HStack
          spacing={3}
          px={3}
          py={2}
          borderRadius="md"
          color={isActive ? 'copper.300' : 'whiteAlpha.800'}
          bg={isActive ? 'whiteAlpha.100' : 'transparent'}
          _hover={{ bg: 'whiteAlpha.100', color: 'copper.300' }}
          transition="background 120ms ease, color 120ms ease"
        >
          <Icon as={item.icon} boxSize={4} />
          <Text fontSize="sm">{item.label}</Text>
        </HStack>
      )}
    </NavLink>
  )
}
