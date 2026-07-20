// 左侧 KB 列表 + 新建/删除按钮
// 响应式: 桌面直接渲染固定侧栏; 移动端由 App.tsx 包装成 Drawer
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Box,
  Button,
  Divider,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  Flex,
  HStack,
  IconButton,
  List,
  ListItem,
  Spinner,
  Text,
  Tooltip,
  useDisclosure,
  useToast,
} from '@chakra-ui/react'
import { DeleteIcon } from '@chakra-ui/icons'
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { KB, User } from '../types'
import { api, ApiError } from '../api'
import { NewKnowledgeBaseButton } from './NewKnowledgeBaseButton'
import { UserMenu } from './UserMenu'

interface Props {
  kbs: KB[]
  loading: boolean
  onRefresh: () => void
  isMobile: boolean
  drawer: {
    isOpen: boolean
    onOpen: () => void
    onClose: () => void
    onToggle?: () => void
  }
  onNavigate: (kbId: string) => void
  user: User | null
  onLogout: () => void
}

export function KnowledgeBaseSidebar({ kbs, loading, onRefresh, isMobile, drawer, onNavigate, user, onLogout }: Props) {
  const navigate = useNavigate()
  const { kbId: activeId } = useParams<{ kbId: string }>()
  const {
    isOpen: isDeleteOpen,
    onOpen: onDeleteOpen,
    onClose: onDeleteClose,
  } = useDisclosure()
  const [pendingDelete, setPendingDelete] = useState<KB | null>(null)
  const [deleting, setDeleting] = useState(false)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const toast = useToast()

  const handleDelete = async () => {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      await api.deleteKB(pendingDelete.id)
      toast({
        title: `已删除 "${pendingDelete.name}"`,
        status: 'success',
        duration: 2000,
      })
      onDeleteClose()
      setPendingDelete(null)
      if (activeId === pendingDelete.id) {
        navigate('/')
      }
      onRefresh()
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '删除失败, 请检查后端'
      toast({ title: '删除失败', description: msg, status: 'error', duration: 4000 })
    } finally {
      setDeleting(false)
    }
  }

  const goKB = (id: string) => {
    navigate(`/kbs/${id}`)
    onNavigate(id)
  }

  // 侧栏内容 (桌面 / Drawer body 共用)
  const body = (
    <Box
      w={{ base: '280px', md: '240px', lg: '280px' }}
      h={{ base: 'auto', md: '100vh' }}
      bg="white"
      borderRight={{ base: 'none', md: '1px' }}
      borderColor="gray.200"
      p={4}
      overflowY="auto"
      flexShrink={0}
    >
      {/* 标题只在桌面显示 (移动端 App.tsx 顶栏已经有) */}
      {!isMobile && (
        <Text fontSize="lg" fontWeight="bold" mb={3} color="brand.700">
          youfu-known
        </Text>
      )}
      <UserMenu user={user} onLogout={onLogout} />
      <NewKnowledgeBaseButton onCreated={onRefresh} />

      <Divider my={4} />

      <Text
        fontSize="xs"
        fontWeight="bold"
        color="gray.500"
        textTransform="uppercase"
        mb={2}
      >
        知识库 ({kbs.length})
      </Text>

      {loading ? (
        <Flex justify="center" py={6}>
          <Spinner size="sm" color="brand.500" />
        </Flex>
      ) : kbs.length === 0 ? (
        <Text fontSize="sm" color="gray.500" py={4}>
          还没有知识库, 点上方按钮新建一个
        </Text>
      ) : (
        <List spacing={1}>
          {kbs.map((kb) => {
            const active = kb.id === activeId
            return (
              <ListItem key={kb.id}>
                <HStack
                  spacing={1}
                  bg={active ? 'brand.50' : 'transparent'}
                  borderRadius="md"
                  _hover={{ bg: active ? 'brand.50' : 'gray.100' }}
                  pr={1}
                  minH={{ base: '44px', md: 'auto' }}
                >
                  <Box
                    flex={1}
                    px={3}
                    py={2}
                    cursor="pointer"
                    onClick={() => goKB(kb.id)}
                    borderLeft="3px solid"
                    borderLeftColor={active ? 'brand.500' : 'transparent'}
                    minH={{ base: '44px', md: 'auto' }}
                  >
                    <Text
                      fontSize="sm"
                      fontWeight={active ? 'semibold' : 'normal'}
                      noOfLines={1}
                    >
                      {kb.name}
                    </Text>
                    <Text fontSize="xs" color="gray.500" noOfLines={1}>
                      {kb.doc_count} 文档 · {kb.chunk_count} chunks
                    </Text>
                  </Box>
                  <Tooltip label="删除知识库" placement="top">
                    <IconButton
                      aria-label="删除"
                      icon={<DeleteIcon />}
                      size="xs"
                      variant="ghost"
                      colorScheme="red"
                      onClick={(e) => {
                        e.stopPropagation()
                        setPendingDelete(kb)
                        onDeleteOpen()
                      }}
                      minW={{ base: '44px', md: 'auto' }}
                      minH={{ base: '44px', md: 'auto' }}
                    />
                  </Tooltip>
                </HStack>
              </ListItem>
            )
          })}
        </List>
      )}

      <AlertDialog
        isOpen={isDeleteOpen}
        leastDestructiveRef={cancelRef}
        onClose={onDeleteClose}
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader fontSize="lg" fontWeight="bold">
              删除知识库?
            </AlertDialogHeader>
            <AlertDialogBody>
              确定要删除知识库 <b>{pendingDelete?.name}</b> 吗? 这会同时
              删除该 KB 下所有文档和向量数据, 不可恢复。
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={cancelRef} onClick={onDeleteClose}>
                取消
              </Button>
              <Button
                colorScheme="red"
                onClick={handleDelete}
                ml={3}
                isLoading={deleting}
                loadingText="删除中"
              >
                删除
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Box>
  )

  if (isMobile) {
    return (
      <Drawer
        isOpen={drawer.isOpen}
        placement="left"
        onClose={drawer.onClose}
        size="xs"
      >
        <DrawerOverlay />
        <DrawerContent>
          <DrawerCloseButton />
          <DrawerHeader borderBottomWidth="1px" py={3}>
            知识库
          </DrawerHeader>
          <DrawerBody p={0}>{body}</DrawerBody>
        </DrawerContent>
      </Drawer>
    )
  }
  return body
}
