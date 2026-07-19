// 类型定义 - 严格按后端 REST API envelope 协议
// 后端统一返回 { code: number, data?: T, message?: string, detail?: any }
// 成功: code === 0, data 存在
// 失败: code !== 0, message + 可选 detail

export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface KB {
  id: string
  name: string
  description: string
  created_at: string
  doc_count: number
  chunk_count: number
}

export interface KBDetail {
  kb: KB
  documents: Document[]
}

export interface Document {
  id: string
  kb_id: string
  filename: string
  ext: string
  size_bytes: number
  status: DocumentStatus
  error: string
  chunk_count: number
  created_at: string
  processed_at: string | null
}

export interface DocumentStatusInfo {
  doc_id: string
  status: DocumentStatus
  error: string
  chunk_count: number
}

export interface UploadResult {
  uploaded: Array<{
    doc_id: string
    filename: string
    status: DocumentStatus
  }>
}

export interface Citation {
  n: number
  doc_id: string
  doc_filename: string
  chunk_idx: number
  score: number
  text: string
}

export interface ChatResponse {
  answer: string
  citations: Citation[]
}

export interface HealthInfo {
  status: string
  version: string
}

// 前端内部用的问答历史项
export interface ChatTurn {
  id: string
  question: string
  answer: string
  citations: Citation[]
  createdAt: number
  error?: string
}