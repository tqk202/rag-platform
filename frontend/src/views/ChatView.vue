<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { chatStream } from '@/api/chat'
import type { Citation } from '@/types'

interface Msg {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  status?: string // 生成中的状态提示（正在检索/生成）
}

const input = ref('')
const loading = ref(false)
const messages = ref<Msg[]>([])

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
    await chatStream(q, history, {
      onMeta: (n) => {
        messages.value[idx].status = `已检索到 ${n} 条资料，正在生成回答…`
      },
      onDelta: (text) => {
        messages.value[idx].content = text
        messages.value[idx].status = ''
      },
      onDone: (answer, citations, noAnswer) => {
        messages.value[idx].content = answer
        messages.value[idx].citations = citations
        messages.value[idx].status = noAnswer ? '（未找到相关资料）' : ''
      },
      onError: (detail) => {
        messages.value[idx].status = ''
        ElMessage.error(detail)
      },
    })
  } catch {
    messages.value[idx].status = ''
    ElMessage.error('请求失败，请重试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="chat">
    <div class="messages">
      <div v-if="!messages.length" class="empty">输入问题开始问答，回答会标注来源文档</div>
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div class="bubble">
          <span v-if="!m.content && m.role === 'assistant' && m.status">{{ m.status }}</span>
          {{ m.content }}
        </div>
        <div v-if="m.citations?.length" class="citations">
          <el-tag v-for="(c, j) in m.citations" :key="j" size="small" class="citation-tag">
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
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 40px);
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
.citations {
  margin-top: 6px;
  text-align: left;
}
.citation-tag {
  margin-right: 6px;
}
.input-bar {
  display: flex;
  gap: 10px;
  padding: 12px;
  background: #fff;
  border-radius: 8px;
}
</style>
