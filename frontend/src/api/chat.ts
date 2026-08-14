import http from './http'
import type {
  ChatResponse,
  ChatSessionDetail,
  ChatSessionInfo,
  Citation,
} from '@/types'

export function chat(
  question: string,
  history: Array<{ role: string; content: string }> = [],
  sessionId?: number | null,
) {
  return http
    .post<ChatResponse>('/chat', { question, history, session_id: sessionId })
    .then((r) => r.data)
}

export interface StreamCallbacks {
  onMeta?: (chunkCount: number) => void
  onDelta?: (fullText: string) => void
  onDone?: (answer: string, citations: Citation[], noAnswer: boolean, sessionId?: number | null) => void
  onError?: (detail: string) => void
}

export function listSessions() {
  return http.get<ChatSessionInfo[]>('/chat/sessions').then((r) => r.data)
}

export function getSession(id: number) {
  return http.get<ChatSessionDetail>(`/chat/sessions/${id}`).then((r) => r.data)
}

export function deleteSession(id: number) {
  return http.delete<{ ok: boolean }>(`/chat/sessions/${id}`).then((r) => r.data)
}

/**
 * 流式问答：用原生 fetch 读 SSE（axios 不支持逐段读取）。
 * 服务端事件：
 *   event: meta   -> {"chunk_count": N, ...}
 *   event: delta  -> "一段文本"
 *   event: done   -> {"answer": "...", "citations": [...], "no_answer": bool}
 *   event: error  -> {"detail": "..."}
 */
export async function chatStream(
  question: string,
  history: Array<{ role: string; content: string }> = [],
  cb: StreamCallbacks = {},
  sessionId?: number | null,
) {
  const resp = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
    },
    body: JSON.stringify({ question, history, session_id: sessionId }),
  })
  if (!resp.ok || !resp.body) {
    cb.onError?.(`请求失败（HTTP ${resp.status}）`)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 事件以空行分隔，处理完整块，剩余的留在 buffer
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''

    for (const block of blocks) {
      const lines = block.split('\n')
      const event = lines.find((l) => l.startsWith('event:'))?.slice(6).trim()
      const dataLine = lines.find((l) => l.startsWith('data:'))?.slice(5).trim()
      if (!event || !dataLine) continue
      let payload: any
      try {
        payload = JSON.parse(dataLine)
      } catch {
        continue
      }
      if (event === 'meta') {
        cb.onMeta?.(payload.chunk_count)
      } else if (event === 'delta') {
        answer += payload
        cb.onDelta?.(answer)
      } else if (event === 'done') {
        cb.onDone?.(payload.answer, payload.citations, payload.no_answer, payload.session_id)
      } else if (event === 'error') {
        cb.onError?.(payload.detail)
      }
    }
  }
}
