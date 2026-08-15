export interface UserInfo {
  id: number
  username: string
  role: 'admin' | 'manager' | 'member'
  department: string
  is_active: boolean
}

export interface DocumentInfo {
  id: number
  title: string
  file_name: string
  status: 'pending' | 'processing' | 'ready' | 'failed'
  failure_reason?: string | null
  version: number
  department: string
  chunk_count: number
  created_at: string
}

export interface Citation {
  chunk_id: number
  document_id: number
  document_title: string
  content: string
  page_no?: number | null
}

export interface ChatResponse {
  answer: string
  citations: Citation[]
  no_answer: boolean
  session_id?: number | null
}

export interface ChatMessageInfo {
  id: number
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  no_answer: boolean
  created_at: string
}

export interface ChatSessionInfo {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export interface ChatSessionDetail extends ChatSessionInfo {
  messages: ChatMessageInfo[]
}

export interface ChunkInfo {
  id: number
  chunk_index: number
  content: string
  page_no?: number | null
}

export interface DocumentDetail extends DocumentInfo {
  chunks: ChunkInfo[]
}

export interface AuditLogInfo {
  id: number
  actor_username: string | null
  department: string | null
  action: string
  object_type: string | null
  object_id: number | null
  detail: string | null
  created_at: string
}

export interface ReconcileResult {
  document_id: number
  orphans_cleaned: number
  missing_in_milvus: number[]
}
