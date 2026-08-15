import http from './http'
import type { DocumentDetail, DocumentInfo } from '@/types'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export function listDocuments(page = 1, pageSize = 20) {
  return http
    .get<Page<DocumentInfo>>('/documents', { params: { page, page_size: pageSize } })
    .then((r) => r.data)
}

export function uploadDocument(file: File, onProgress?: (percent: number) => void) {
  const form = new FormData()
  form.append('file', file)
  return http
    .post<{ document_id: number; message: string }>('/documents/upload', form, {
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded / e.total) * 100))
        }
      },
    })
    .then((r) => r.data)
}

export function deleteDocument(id: number) {
  return http.delete<{ ok: boolean }>(`/documents/${id}`).then((r) => r.data)
}

export function retryDocument(id: number) {
  return http
    .post<{ document_id: number; message: string }>(`/documents/${id}/retry`)
    .then((r) => r.data)
}

export function getDocument(id: number) {
  return http.get<DocumentDetail>(`/documents/${id}`).then((r) => r.data)
}
