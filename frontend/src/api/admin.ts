import http from './http'
import type {
  AuditLogInfo,
  FeedbackInfo,
  KnowledgeBaseInfo,
  ReconcileResult,
  TraceInfo,
} from '@/types'
import type { Page } from './documents'

export function listAuditLogs(page = 1, pageSize = 20) {
  return http
    .get<Page<AuditLogInfo>>('/admin/audit-logs', {
      params: { page, page_size: pageSize },
    })
    .then((r) => r.data)
}

export function reconcileDocument(id: number) {
  return http
    .post<ReconcileResult>(`/admin/documents/${id}/reconcile`)
    .then((r) => r.data)
}

export function reconcileAll() {
  return http
    .post<{ documents: number; total_orphans_cleaned: number }>(
      '/admin/documents/reconcile',
    )
    .then((r) => r.data)
}

export function createKnowledgeBase(data: {
  name: string
  department: string
  description?: string
}) {
  return http.post<KnowledgeBaseInfo>('/admin/knowledge-bases', data).then((r) => r.data)
}

export function updateKnowledgeBase(
  id: number,
  data: { name?: string; description?: string; is_active?: boolean },
) {
  return http
    .patch<KnowledgeBaseInfo>(`/admin/knowledge-bases/${id}`, data)
    .then((r) => r.data)
}

export function listFeedback(
  page = 1,
  pageSize = 20,
  sentiment?: string,
) {
  return http
    .get<Page<FeedbackInfo>>('/admin/feedback', {
      params: { page, page_size: pageSize, sentiment },
    })
    .then((r) => r.data)
}

export function listTraces(page = 1, pageSize = 20) {
  return http
    .get<Page<TraceInfo>>('/admin/traces', {
      params: { page, page_size: pageSize },
    })
    .then((r) => r.data)
}

export function deleteFeedback(id: number) {
  return http.delete<{ deleted: number }>(`/admin/feedback/${id}`).then((r) => r.data)
}

export function batchDeleteFeedback(ids: number[]) {
  return http.post<{ deleted: number }>('/admin/feedback/batch-delete', { ids }).then((r) => r.data)
}

export function clearAllFeedback() {
  return http.post<{ deleted: number }>('/admin/feedback/clear-all').then((r) => r.data)
}

export function deleteTrace(id: number) {
  return http.delete<{ deleted: number }>(`/admin/traces/${id}`).then((r) => r.data)
}

export function batchDeleteTraces(ids: number[]) {
  return http.post<{ deleted: number }>('/admin/traces/batch-delete', { ids }).then((r) => r.data)
}

export function clearAllTraces() {
  return http.post<{ deleted: number }>('/admin/traces/clear-all').then((r) => r.data)
}

export function cleanupAuditLogs(beforeDays: number) {
  return http
    .post<{ deleted: number }>('/admin/audit-logs/cleanup', { before_days: beforeDays })
    .then((r) => r.data)
}
