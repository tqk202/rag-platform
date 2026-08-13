<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteDocument, listDocuments, uploadDocument } from '@/api/documents'
import { useAuthStore } from '@/stores/auth'
import type { DocumentInfo } from '@/types'

const auth = useAuthStore()
const docs = ref<DocumentInfo[]>([])
const total = ref(0)
const loading = ref(false)

// 只有经理/管理员能上传和删除；普通成员只读
const canManage = computed(() => auth.user?.role === 'manager' || auth.user?.role === 'admin')

const statusMap: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  ready: '已就绪',
  failed: '失败',
}

async function load() {
  loading.value = true
  try {
    const page = await listDocuments(1, 50)
    docs.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

async function onFileChange(file: File) {
  try {
    const res = await uploadDocument(file)
    ElMessage.success(res.message)
    load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '上传失败')
  }
}

async function onDelete(doc: DocumentInfo) {
  await ElMessageBox.confirm(`确定删除「${doc.file_name}」吗？`, '提示')
  await deleteDocument(doc.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <h3>知识库文档（共 {{ total }} 份）</h3>
      <el-upload
        v-if="canManage"
        :show-file-list="false"
        :auto-upload="false"
        :on-change="(file: any) => onFileChange(file.raw)"
      >
        <el-button type="primary">上传文档</el-button>
      </el-upload>
    </div>
    <el-table :data="docs" v-loading="loading" stripe>
      <el-table-column prop="file_name" label="文件名" />
      <el-table-column prop="department" label="部门" width="120" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'ready' ? 'success' : row.status === 'failed' ? 'danger' : 'info'"
          >
            {{ statusMap[row.status] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="切片数" width="100" />
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column prop="created_at" label="上传时间" width="180" />
      <el-table-column v-if="canManage" label="操作" width="120">
        <template #default="{ row }">
          <el-button link type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
</style>
