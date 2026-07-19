// 新建知识库按钮 + Modal
// 弹 Modal 收集 name + description, 调 api.createKB
import { useState } from 'react'
import {
  Button,
  FormControl,
  FormLabel,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Textarea,
  useDisclosure,
  useToast,
} from '@chakra-ui/react'
import { AddIcon } from '@chakra-ui/icons'
import { api, ApiError } from '../api'

interface Props {
  onCreated: () => void
}

export function NewKnowledgeBaseButton({ onCreated }: Props) {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const toast = useToast()

  const reset = () => {
    setName('')
    setDescription('')
  }

  const handleSubmit = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast({
        title: '名称不能为空',
        status: 'warning',
        duration: 2000,
      })
      return
    }
    setSubmitting(true)
    try {
      await api.createKB(trimmed, description.trim())
      toast({
        title: '知识库已创建',
        status: 'success',
        duration: 2000,
      })
      reset()
      onClose()
      onCreated()
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : '创建失败, 请检查后端'
      toast({
        title: '创建失败',
        description: msg,
        status: 'error',
        duration: 4000,
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <Button
        leftIcon={<AddIcon />}
        colorScheme="brand"
        size="sm"
        w="100%"
        onClick={onOpen}
      >
        新建知识库
      </Button>

      <Modal isOpen={isOpen} onClose={onClose} size="md">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>新建知识库</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={4}>
            <FormControl isRequired mb={3}>
              <FormLabel>名称</FormLabel>
              <Input
                placeholder="例如: 工作笔记"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={64}
                autoFocus
              />
            </FormControl>
            <FormControl>
              <FormLabel>描述</FormLabel>
              <Textarea
                placeholder="可选, 用一句话说明这个知识库放什么"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={256}
                rows={3}
              />
            </FormControl>
          </ModalBody>
          <ModalFooter>
            <Button mr={3} onClick={onClose} variant="ghost">
              取消
            </Button>
            <Button
              colorScheme="brand"
              onClick={handleSubmit}
              isLoading={submitting}
              loadingText="创建中"
            >
              创建
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}