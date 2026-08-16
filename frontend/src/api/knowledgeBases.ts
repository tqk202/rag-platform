import http from './http'
import type { KnowledgeBaseInfo } from '@/types'

export function listKnowledgeBases() {
  return http.get<KnowledgeBaseInfo[]>('/knowledge-bases').then((r) => r.data)
}
