<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getDocument } from '@/api/documents'
import type { DocumentDetail } from '@/types'

const props = defineProps<{
  modelValue: boolean
  documentId: number | null
  highlightChunkId?: number | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const detail = ref<DocumentDetail | null>(null)
const loading = ref(false)
const chunkEls = ref<Record<number, HTMLElement>>({})

const statusMap: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  ready: '已就绪',
  failed: '失败',
}

// 打开或切换目标文档时重新拉取
watch(
  () => [props.modelValue, props.documentId] as const,
  async ([visible, docId]) => {
    if (!visible || !docId) return
    loading.value = true
    chunkEls.value = {}
    try {
      detail.value = await getDocument(docId)
    } catch (e: any) {
      ElMessage.error(e.response?.data?.detail || '加载文档失败')
    } finally {
      loading.value = false
    }
    await nextTick()
    scrollToHighlight()
  },
)

// 抽屉已开、切到同文档另一条引文时，滚动到新目标
watch(
  () => props.highlightChunkId,
  (id) => {
    if (props.modelValue && id != null) {
      nextTick(() => {
        const el = chunkEls.value[id]
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      })
    }
  },
)

// 从引文打开时，定位并高亮被引切片
function scrollToHighlight() {
  const id = props.highlightChunkId
  const el = id != null ? chunkEls.value[id] : undefined
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function setChunkRef(el: unknown, id: number) {
  if (el) chunkEls.value[id] = el as HTMLElement
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    :title="detail?.file_name || '文档详情'"
    size="55%"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div v-loading="loading">
      <template v-if="detail">
        <div class="meta">
          <el-tag size="small">{{ detail.department }}</el-tag>
          <el-tag size="small" :type="detail.status === 'ready' ? 'success' : detail.status === 'failed' ? 'danger' : 'info'">
            {{ statusMap[detail.status] }}
          </el-tag>
          <el-tag v-if="detail.version > 1" size="small" type="info">v{{ detail.version }}</el-tag>
          <span class="meta-text">共 {{ detail.chunk_count }} 切片</span>
          <span class="meta-text">上传于 {{ detail.created_at }}</span>
        </div>

        <div
          v-for="c in detail.chunks"
          :key="c.id"
          :ref="(el: unknown) => setChunkRef(el, c.id)"
          :class="['chunk', { highlight: c.id === highlightChunkId }]"
        >
          <div class="chunk-head">
            切片 #{{ c.chunk_index }}
            <span v-if="c.page_no">· 第 {{ c.page_no }} 页</span>
          </div>
          <p class="chunk-content">{{ c.content }}</p>
        </div>
        <el-empty v-if="!detail.chunks.length" description="暂无切片" />
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.meta {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.meta-text {
  font-size: 13px;
  color: #666;
}
.chunk {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
}
.chunk.highlight {
  border-color: #409eff;
  background: #ecf5ff;
}
.chunk-head {
  font-size: 12px;
  color: #999;
  margin-bottom: 6px;
}
.chunk-content {
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
  margin: 0;
}
</style>
