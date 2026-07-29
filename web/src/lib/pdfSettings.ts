// PDF parser 配置类型 (跟后端 Phase C.5 settings endpoint 同步)
//
// 设计原则 (跟 32 commits DDD + 后台管理端 8 阶段 + Phase C.1+C.2+C.3 一致):
//   - 0 改现有类型 (types.ts)
//   - 新加独立模块, 跟 KBSettings.tsx / Uploader.tsx 配套
//   - 0 改 web/package.json (无新依赖)

export type ParserPreference = 'auto' | 'pymupdf' | 'ocr' | 'vision'

export interface KBPdfSettings {
  /** 启用 Tesseract OCR (eng + chi_sim). 默认 opt-in 关. */
  enable_ocr: boolean
  /** 启用 Qwen-VL-Max 多模态 LLM. 默认 opt-in 关 (¥警告). */
  enable_vision_llm: boolean
  /**
   * 解析器偏好. 'auto' = 走 PDFInspector 按 text_ratio 路由 (Phase C.1).
   * 'pymupdf' / 'ocr' / 'vision' = 强制走单一解析器.
   */
  parser_preference: ParserPreference
  /** PDF 缓存上限 (MB). 默认 10GB, LRU 自动清理. */
  pdf_cache_size_mb: number
  /** 多模态 LLM 月度预算 (¥). 0 = 不限制. */
  vision_llm_monthly_limit_yuan: number
}

export const DEFAULT_PDF_SETTINGS: KBPdfSettings = {
  enable_ocr: false,
  enable_vision_llm: false,
  parser_preference: 'auto',
  pdf_cache_size_mb: 10240,
  vision_llm_monthly_limit_yuan: 5000,
}

/** Display labels for parser preference dropdown. */
export const PARSER_LABELS: Record<ParserPreference, string> = {
  auto: '自动 (推荐) - 按 PDF 类型选',
  pymupdf: 'PyMuPDF + pdfplumber (快, 纯文本/表格)',
  ocr: 'Tesseract OCR (慢, 扫描件)',
  vision: 'Qwen-VL-Max 多模态 (最慢, ¥¥, 复杂 layout)',
}

/** Cost warning when enabling vision_llm. */
export const VISION_LLM_WARNING = '⚠️ Qwen-VL-Max API 调用 ¥0.5/页, 1万页 ≈ ¥5000/月'
