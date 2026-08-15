import http from './http'
import type { AuditLogInfo, ReconcileResult } from '@/types'
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
