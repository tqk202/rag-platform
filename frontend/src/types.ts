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
}
