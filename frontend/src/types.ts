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
  knowledge_base?: string | null
  chunk_count: number
  created_at: string
}

export interface KnowledgeBaseInfo {
  id: number
  name: string
  department: string
  description?: string | null
  is_active: boolean
  document_count: number
  created_at: string
}

export interface FeedbackInfo {
  id: number
  user_id: number
  username: string
  department: string
  message_id: number
  sentiment: 'like' | 'dislike'
  comment?: string | null
  question?: string | null
  answer?: string | null
  created_at: string
}

export interface TraceInfo {
  id: number
  request_id?: string | null
  user_id?: number | null
  department?: string | null
  knowledge_base?: string | null
  question: string
  rewritten_query?: string | null
  cache_hit: boolean
  retrieved_count: number
  no_answer: boolean
  llm_input_tokens?: number | null
  llm_output_tokens?: number | null
  latency_ms: number
  stage_timing?: string | null
  answer_preview?: string | null
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
  message_id?: number | null
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
  knowledge_base?: string | null
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
