// 修改密码页 - 与登录页风格一致, 位于主区域内
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  Card,
  CardBody,
  Center,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Stack,
  Text,
  VStack,
  useToast,
} from '@chakra-ui/react'
import { api } from '../api'

export function ChangePasswordPage() {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const toast = useToast()

  const handleSubmit = async () => {
    if (!oldPassword || !newPassword || !confirmPassword) {
      toast({
        title: '请填写完整',
        status: 'warning',
        duration: 3000,
        position: 'top',
      })
      return
    }
    if (newPassword !== confirmPassword) {
      toast({
        title: '新密码不一致',
        description: '两次输入的新密码不同',
        status: 'error',
        duration: 4000,
        position: 'top',
      })
      return
    }
    if (newPassword.length < 6) {
      toast({
        title: '新密码太短',
        description: '密码至少需要 6 位',
        status: 'warning',
        duration: 4000,
        position: 'top',
      })
      return
    }

    setLoading(true)
    try {
      await api.changePassword(oldPassword, newPassword)
      toast({
        title: '密码修改成功',
        status: 'success',
        duration: 3000,
        position: 'top',
      })
      navigate(-1)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '修改失败'
      toast({
        title: '修改失败',
        description: msg,
        status: 'error',
        duration: 4000,
        position: 'top',
      })
    } finally {
      setLoading(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSubmit()
  }

  return (
    <Center h="100%" flex={1} bg="gray.50" p={{ base: 4, md: 8 }}>
      <Card maxW="400px" w="full" boxShadow="lg" borderRadius="2xl">
        <CardBody p={{ base: 6, md: 8 }}>
          <VStack spacing={6}>
            <Heading size="md">修改密码</Heading>
            <Text fontSize="sm" color="gray.500">
              修改后请使用新密码重新登录
            </Text>

            <Stack spacing={4} w="full">
              <FormControl>
                <FormLabel fontSize="sm">当前密码</FormLabel>
                <Input
                  type="password"
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="••••••••"
                  size="lg"
                  isDisabled={loading}
                />
              </FormControl>
              <FormControl>
                <FormLabel fontSize="sm">新密码</FormLabel>
                <Input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="••••••••"
                  size="lg"
                  isDisabled={loading}
                />
              </FormControl>
              <FormControl>
                <FormLabel fontSize="sm">确认新密码</FormLabel>
                <Input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="••••••••"
                  size="lg"
                  isDisabled={loading}
                />
              </FormControl>
            </Stack>

            <Button
              colorScheme="brand"
              size="lg"
              w="full"
              onClick={handleSubmit}
              isLoading={loading}
              loadingText="保存中"
            >
              保存
            </Button>

            <Button variant="ghost" size="sm" w="full" onClick={() => navigate(-1)}>
              取消
            </Button>
          </VStack>
        </CardBody>
      </Card>
    </Center>
  )
}
