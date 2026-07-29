// KB 配置 Drawer (Phase PDF-C.4 新加)
//
// 风格:
//   - 跟 Uploader.tsx / AdminUsersPage.tsx 同款 (Chakra UI + formatApiError)
//   - 跟 AdminUsersPage.tsx toast 风格一致 (Phase 1 后台管理端)
//
// 硬约束 (跟 32 commits DDD + 后台管理端 8 阶段 + Phase C.1+C.2+C.3 一致):
//   - 0 改 AdminUsersPage.tsx / 任何 web/src/components/Admin* 文件
//   - 0 改 web/package.json (无新 npm 包)
//   - 后端 endpoint /api/kbs/{id}/settings 由 Phase C.5 实施, 阶段 C.4 走 api.ts mock
import {
  Button,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  FormControl,
  FormLabel,
  HStack,
  NumberDecrementStepper,
  NumberIncrementStepper,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  Select,
  Spinner,
  Switch,
  Text,
  VStack,
  useToast,
} from '@chakra-ui/react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { formatApiError } from '../lib/apiErrors'
import {
  DEFAULT_PDF_SETTINGS,
  PARSER_LABELS,
  VISION_LLM_WARNING,
  type KBPdfSettings,
  type ParserPreference,
} from '../lib/pdfSettings'

interface Props {
  kbId: string
  isOpen: boolean
  onClose: () => void
  onSaved?: (settings: KBPdfSettings) => void
}

export function KBSettings({ kbId, isOpen, onClose, onSaved }: Props) {
  const toast = useToast()
  const [settings, setSettings] = useState<KBPdfSettings>(DEFAULT_PDF_SETTINGS)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!isOpen) return
    let cancelled = false
    setLoading(true)
    api
      .kbSettings(kbId)
      .then((data) => {
        if (!cancelled) setSettings(data)
      })
      .catch(() => {
        if (!cancelled) setSettings(DEFAULT_PDF_SETTINGS)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [kbId, isOpen])

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.updateKBSettings(kbId, settings)
      toast({
        title: '设置已保存',
        description: '下次上传 PDF 时生效',
        status: 'success',
        duration: 3000,
      })
      onSaved?.(settings)
      onClose()
    } catch (e) {
      toast({
        title: '保存失败',
        description: formatApiError(e, '保存 KB 设置失败'),
        status: 'error',
        duration: 5000,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer isOpen={isOpen} onClose={onClose} size="md" placement="right">
      <DrawerOverlay />
      <DrawerContent>
        <DrawerCloseButton />
        <DrawerHeader>知识库 PDF 解析设置</DrawerHeader>
        <DrawerBody>
          {loading ? (
            <HStack spacing={3} color="gray.500" py={6}>
              <Spinner size="sm" color="brand.500" />
              <Text>加载中...</Text>
            </HStack>
          ) : (
            <VStack spacing={6} align="stretch">
              <FormControl display="flex" alignItems="center">
                <FormLabel mb={0} flex={1}>
                  启用 Tesseract OCR (扫描件)
                </FormLabel>
                <Switch
                  isChecked={settings.enable_ocr}
                  onChange={(e) =>
                    setSettings({ ...settings, enable_ocr: e.target.checked })
                  }
                />
              </FormControl>
              <Text fontSize="xs" color="gray.500" pl={1}>
                扫描件 PDF 自动 OCR (eng + chi_sim)
              </Text>

              <FormControl display="flex" alignItems="center">
                <FormLabel mb={0} flex={1}>
                  启用 Qwen-VL-Max 多模态
                </FormLabel>
                <Switch
                  isChecked={settings.enable_vision_llm}
                  onChange={(e) =>
                    setSettings({ ...settings, enable_vision_llm: e.target.checked })
                  }
                />
              </FormControl>
              <Text fontSize="xs" color="orange.500" pl={1}>
                {VISION_LLM_WARNING}
              </Text>

              <FormControl>
                <FormLabel>解析器偏好</FormLabel>
                <Select
                  value={settings.parser_preference}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      parser_preference: e.target.value as ParserPreference,
                    })
                  }
                >
                  {(Object.keys(PARSER_LABELS) as ParserPreference[]).map((p) => (
                    <option key={p} value={p}>
                      {PARSER_LABELS[p]}
                    </option>
                  ))}
                </Select>
              </FormControl>

              <FormControl>
                <FormLabel>PDF 缓存大小 (MB)</FormLabel>
                <NumberInput
                  value={settings.pdf_cache_size_mb}
                  min={1024}
                  max={102400}
                  step={1024}
                  onChange={(_, val) =>
                    setSettings({
                      ...settings,
                      pdf_cache_size_mb: val || 10240,
                    })
                  }
                >
                  <NumberInputField />
                  <NumberInputStepper>
                    <NumberIncrementStepper />
                    <NumberDecrementStepper />
                  </NumberInputStepper>
                </NumberInput>
                <Text fontSize="xs" color="gray.500" pl={1}>
                  超过上限时 LRU 自动清理 (默认 10GB)
                </Text>
              </FormControl>

              <FormControl>
                <FormLabel>多模态 LLM 月度预算 (¥)</FormLabel>
                <NumberInput
                  value={settings.vision_llm_monthly_limit_yuan}
                  min={0}
                  max={100000}
                  step={500}
                  onChange={(_, val) =>
                    setSettings({
                      ...settings,
                      vision_llm_monthly_limit_yuan: val || 5000,
                    })
                  }
                >
                  <NumberInputField />
                  <NumberInputStepper>
                    <NumberIncrementStepper />
                    <NumberDecrementStepper />
                  </NumberInputStepper>
                </NumberInput>
              </FormControl>
            </VStack>
          )}

          <HStack mt={8} justify="flex-end">
            <Button variant="ghost" mr={3} onClick={onClose} isDisabled={saving}>
              取消
            </Button>
            <Button
              colorScheme="brand"
              onClick={handleSave}
              isLoading={saving}
              isDisabled={loading}
            >
              保存
            </Button>
          </HStack>
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  )
}
