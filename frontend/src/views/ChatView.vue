<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DocumentDetailDrawer from '@/components/DocumentDetailDrawer.vue'
import { chatStream, deleteSession, getSession, listSessions, submitFeedback } from '@/api/chat'
import { listKnowledgeBases } from '@/api/knowledgeBases'
import type { ChatMessageInfo, ChatSessionInfo, Citation, KnowledgeBaseInfo } from '@/types'

interface Msg {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  status?: string // 生成中的状态提示（正在检索/生成）
  id?: number // 回答消息 id，点赞/点踩绑定
  feedback?: 'like' | 'dislike' | null
}

const input = ref('')
const loading = ref(false)
const messages = ref<Msg[]>([])

// 会话历史（B）：左侧会话栏 + 当前会话 id
const sessions = ref<ChatSessionInfo[]>([])
const currentSessionId = ref<number | null>(null)
const sessionsLoading = ref(false)

// 多知识库：顶部下拉（空 = 部门内全部知识库）
const knowledgeBases = ref<KnowledgeBaseInfo[]>([])
const currentKb = ref<string | null>(null)

function toMsg(m: ChatMessageInfo): Msg {
  return {
    role: m.role,
    content: m.content,
    citations: m.citations || [],
    id: m.id,
  }
}

async function onFeedback(m: Msg, sentiment: 'like' | 'dislike') {
  if (!m.id) return
  if (m.feedback === sentiment) {
    // 再点同倾向 = 取消
    const res = await submitFeedback(m.id, sentiment)
    m.feedback = null
    ElMessage.success(res.message)
    return
  }
  let comment: string | undefined
  if (sentiment === 'dislike') {
    try {
      const { value } = await ElMessageBox.prompt(
        '对回答哪里不满意？（可选）',
        '反馈',
        {
          confirmButtonText: '提交',
          cancelButtonText: '取消',
          inputPlaceholder: '例如：答案不准确 / 来源不对',
        },
      )
      comment = value?.trim() || undefined
    } catch {
      return // 取消输入 = 不提交
    }
  }
  const res = await submitFeedback(m.id, sentiment, comment)
  m.feedback = res.sentiment
  ElMessage.success(res.message)
}

// 文档详情抽屉（A）：点引文看整篇
const drawerVisible = ref(false)
const drawerDocId = ref<number | null>(null)
const drawerChunkId = ref<number | null>(null)

function showDocument(c: Citation) {
  drawerDocId.value = c.document_id
  drawerChunkId.value = c.chunk_id
  drawerVisible.value = true
}

async function refreshSessions() {
  sessionsLoading.value = true
  try {
    sessions.value = await listSessions()
  } finally {
    sessionsLoading.value = false
  }
}

async function selectSession(session: ChatSessionInfo) {
  const detail = await getSession(session.id)
  currentSessionId.value = session.id
  messages.value = detail.messages.map(toMsg)
  // 继续该会话时沿用它的知识库
  currentKb.value = session.knowledge_base || null
}

async function newSession() {
  currentSessionId.value = null
  messages.value = []
  input.value = ''
}

async function onDeleteSession(session: ChatSessionInfo) {
  await ElMessageBox.confirm(`确定删除会话「${session.title}」吗？`, '提示')
  await deleteSession(session.id)
  if (currentSessionId.value === session.id) await newSession()
  await refreshSessions()
  ElMessage.success('会话已删除')
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

async function send() {
  const q = input.value.trim()
  if (!q || loading.value) return

  messages.value.push({ role: 'user', content: q })
  input.value = ''
  loading.value = true

  const history = messages.value
    .slice(0, -1)
    .map((m) => ({ role: m.role, content: m.content }))
  const idx = messages.value.push({
    role: 'assistant',
    content: '',
    status: '正在检索知识库…',
  }) - 1

  try {
    await chatStream(
      q,
      history,
      {
        onMeta: (n) => {
          messages.value[idx].status = `已检索到 ${n} 条资料，正在生成回答…`
        },
        onDelta: (text) => {
          messages.value[idx].content = text
          messages.value[idx].status = ''
        },
        onDone: async (answer, citations, noAnswer, sessionId, messageId) => {
          messages.value[idx].content = answer
          messages.value[idx].citations = citations
          messages.value[idx].status = noAnswer ? '（未找到相关资料）' : ''
          messages.value[idx].id = messageId ?? undefined
          if (sessionId != null) currentSessionId.value = sessionId
          await refreshSessions() // 新会话出现在列表顶部/标题更新
        },
        onError: (detail) => {
          messages.value[idx].status = ''
          ElMessage.error(detail)
        },
      },
      currentSessionId.value,
      currentKb.value,
    )
  } catch {
    messages.value[idx].status = ''
    ElMessage.error('请求失败，请重试')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    knowledgeBases.value = await listKnowledgeBases()
  } catch {
    // 知识库接口失败不阻塞聊天（空 = 全部）
  }
  await refreshSessions()
  // 刷新不丢：自动恢复最近一次会话
  if (sessions.value.length) {
    await selectSession(sessions.value[0])
  }
})
</script>

<template>
  <div class="chat-wrap">
    <aside class="session-bar">
      <div class="session-head">
        <span>会话</span>
        <el-button link type="primary" @click="newSession">＋ 新会话</el-button>
      </div>
      <div v-loading="sessionsLoading" class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          :class="['session-item', { active: s.id === currentSessionId }]"
          @click="selectSession(s)"
        >
          <span class="session-title">{{ s.title }}</span>
          <span class="session-del" title="删除" @click.stop="onDeleteSession(s)">×</span>
        </div>
        <div v-if="!sessions.length" class="session-empty">暂无历史会话</div>
      </div>
    </aside>

    <div class="chat">
      <div class="kb-bar">
        <span class="kb-label">知识库</span>
        <el-select v-model="currentKb" placeholder="全部知识库" clearable size="small">
          <el-option label="全部知识库" value="" />
          <el-option
            v-for="kb in knowledgeBases"
            :key="kb.id"
            :label="`${kb.name}（${kb.department}）`"
            :value="kb.name"
          />
        </el-select>
      </div>
      <div class="messages">
        <div v-if="!messages.length" class="empty">输入问题开始问答，回答会标注来源文档</div>
        <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
          <div class="bubble">
            <span v-if="!m.content && m.role === 'assistant' && m.status">{{ m.status }}</span>
            {{ m.content }}
            <el-button
              v-if="m.role === 'assistant' && m.content"
              link
              type="primary"
              size="small"
              class="copy-btn"
              @click="copyText(m.content)"
            >
              复制
            </el-button>
          </div>
          <div v-if="m.role === 'assistant' && m.id" class="feedback">
            <el-button
              link
              size="small"
              :type="m.feedback === 'like' ? 'primary' : 'info'"
              @click="onFeedback(m, 'like')"
            >
              有用
            </el-button>
            <el-button
              link
              size="small"
              :type="m.feedback === 'dislike' ? 'danger' : 'info'"
              @click="onFeedback(m, 'dislike')"
            >
              没用
            </el-button>
          </div>
          <div v-if="m.citations?.length" class="citations">
            <el-tag
              v-for="(c, j) in m.citations"
              :key="j"
              size="small"
              class="citation-tag"
              @click="showDocument(c)"
            >
              [{{ j + 1 }}] {{ c.document_title }}
            </el-tag>
          </div>
        </div>
      </div>
      <div class="input-bar">
        <el-input v-model="input" placeholder="输入你的问题，回车发送" @keyup.enter="send" />
        <el-button type="primary" :loading="loading" @click="send">发送</el-button>
      </div>
    </div>

    <DocumentDetailDrawer
      v-model="drawerVisible"
      :document-id="drawerDocId"
      :highlight-chunk-id="drawerChunkId"
    />
  </div>
</template>

<style scoped>
.chat-wrap {
  display: flex;
  height: calc(100vh - 40px);
}
.session-bar {
  width: 220px;
  background: #fff;
  border-right: 1px solid #eee;
  display: flex;
  flex-direction: column;
}
.session-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid #eee;
  font-weight: 600;
  font-size: 14px;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.session-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 9px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #333;
}
.session-item:hover {
  background: #f5f6fa;
}
.session-item.active {
  background: #ecf5ff;
  color: #409eff;
}
.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-del {
  display: none;
  color: #f56c6c;
}
.session-item:hover .session-del {
  display: inline-flex;
}
.session-empty {
  padding: 20px;
  text-align: center;
  color: #999;
  font-size: 13px;
}
.chat {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.kb-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
}
.kb-label {
  font-size: 13px;
  color: #666;
  white-space: nowrap;
}
.feedback {
  margin-top: 4px;
  text-align: left;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.empty {
  text-align: center;
  color: #999;
  margin-top: 80px;
}
.msg {
  margin-bottom: 14px;
}
.msg.user {
  text-align: right;
}
.bubble {
  position: relative;
  display: inline-block;
  max-width: 70%;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fff;
  white-space: pre-wrap;
}
.msg.user .bubble {
  background: #409eff;
  color: #fff;
  text-align: left;
}
.copy-btn {
  margin-left: 8px;
  opacity: 0;
  transition: opacity 0.2s;
}
.bubble:hover .copy-btn {
  opacity: 1;
}
.citations {
  margin-top: 6px;
  text-align: left;
}
.citation-tag {
  margin-right: 6px;
  cursor: pointer;
}
.input-bar {
  display: flex;
  gap: 10px;
  padding: 12px;
  background: #fff;
  border-radius: 8px;
}
</style>
