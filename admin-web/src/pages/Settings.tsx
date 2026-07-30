import {
  Alert,
  AlertIcon,
  Box,
  Button,
  FormControl,
  FormHelperText,
  FormLabel,
  Grid,
  GridItem,
  HStack,
  Heading,
  Input,
  NumberDecrementStepper,
  NumberIncrementStepper,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  Spinner,
  Stack,
  Text,
  useToast,
} from '@chakra-ui/react'
import { useEffect, useState, type FormEvent } from 'react'
import { api, formatApiError } from '../api'
import type { AdminSettings, SettingsPatch } from '../api'

interface FieldDef {
  key: keyof SettingsPatch
  label: string
  helper: string
  min: number
  max: number
  step: number
}

const INT_FIELDS: readonly FieldDef[] = [
  {
    key: 'embedding_batch_size',
    label: 'Embedding 批大小',
    helper: '单次 embedding 调用的批大小',
    min: 1,
    max: 100,
    step: 1,
  },
  {
    key: 'chunk_size',
    label: '切块大小',
    helper: '每个 chunk 的最大字符数',
    min: 1,
    max: 100_000,
    step: 50,
  },
  {
    key: 'chunk_overlap',
    label: '切块重叠',
    helper: '相邻 chunk 之间的重叠字符数（必须小于切块大小）',
    min: 0,
    max: 99_999,
    step: 10,
  },
  {
    key: 'max_upload_size_mb',
    label: '最大上传 (MB)',
    helper: '单次上传允许的最大体积',
    min: 1,
    max: 10_240,
    step: 1,
  },
]

export function SettingsPage() {
  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [patch, setPatch] = useState<SettingsPatch>({})
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  useEffect(() => {
    let cancelled = false
    api
      .settings()
      .then((data) => {
        if (!cancelled) {
          setSettings(data)
          setPatch({})
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return (
      <Alert status="error" variant="left-accent">
        <AlertIcon />
        <Text>{error}</Text>
      </Alert>
    )
  }

  if (!settings) {
    return (
      <Box py={20}>
        <Spinner color="signal.400" size="lg" />
      </Box>
    )
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    try {
      const updated = await api.updateSettings(patch)
      setSettings(updated)
      setPatch({})
      toast({
        title: '已保存',
        description: '系统设置已更新',
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
    } catch (err: unknown) {
      toast({
        title: '保存失败',
        description: formatApiError(err),
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setSaving(false)
    }
  }

  const isDirty = Object.values(patch).some((v) => v !== undefined && v !== '')

  return (
    <Box as="form" onSubmit={handleSubmit} noValidate>
      <Stack spacing={6}>
        <Box>
          <Heading fontFamily="heading" color="copper.300" size="lg">
            系统设置
          </Heading>
          <Text mt={1} color="whiteAlpha.600" fontSize="sm">
            修改会在下一个请求生效，运行时立即生效（无需重启）。
          </Text>
        </Box>
        <Box
          bg="ink.900"
          borderWidth="1px"
          borderColor="whiteAlpha.100"
          borderRadius="lg"
          p={6}
        >
          <Stack spacing={6}>
            <FormControl>
              <FormLabel fontSize="sm" color="whiteAlpha.700">主模型</FormLabel>
              <Input
                value={patch.model_name ?? settings.model_name}
                onChange={(e) => setPatch((p) => ({ ...p, model_name: e.target.value }))}
                bg="ink.800"
                borderColor="whiteAlpha.200"
                _hover={{ borderColor: 'copper.400' }}
                _focusVisible={{ borderColor: 'signal.300', boxShadow: 'none' }}
                maxLength={128}
              />
              <FormHelperText color="whiteAlpha.500">
                支持任意模型名；非空字符串。
              </FormHelperText>
            </FormControl>
            <Grid templateColumns={{ base: 'repeat(1, 1fr)', md: 'repeat(2, 1fr)' }} gap={6}>
              {INT_FIELDS.map((field) => {
                const value = (patch[field.key] as number | undefined) ?? settings[field.key]
                return (
                  <GridItem key={field.key}>
                    <FormControl>
                      <FormLabel fontSize="sm" color="whiteAlpha.700">{field.label}</FormLabel>
                      <NumberInput
                        value={value}
                        min={field.min}
                        max={field.max}
                        step={field.step}
                        onChange={(_str, num) => {
                          if (Number.isNaN(num)) return
                          setPatch((p) => ({ ...p, [field.key]: num }))
                        }}
                      >
                        <NumberInputField
                          bg="ink.800"
                          borderColor="whiteAlpha.200"
                          _hover={{ borderColor: 'copper.400' }}
                          _focusVisible={{ borderColor: 'signal.300', boxShadow: 'none' }}
                        />
                        <NumberInputStepper>
                          <NumberIncrementStepper />
                          <NumberDecrementStepper />
                        </NumberInputStepper>
                      </NumberInput>
                      <FormHelperText color="whiteAlpha.500">{field.helper}</FormHelperText>
                    </FormControl>
                  </GridItem>
                )
              })}
            </Grid>
          </Stack>
        </Box>
        <HStack justify="flex-end">
          <Button
            variant="ghost"
            onClick={() => setPatch({})}
            isDisabled={!isDirty || saving}
          >
            重置
          </Button>
          <Button
            type="submit"
            colorScheme="signal"
            isLoading={saving}
            loadingText="保存中"
            isDisabled={!isDirty}
          >
            保存
          </Button>
        </HStack>
      </Stack>
    </Box>
  )
}
