<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createUser, listUsers, updateUser } from '@/api/users'
import {
  batchDeleteFeedback,
  batchDeleteTraces,
  clearAllFeedback,
  clearAllTraces,
  cleanupAuditLogs,
  createKnowledgeBase,
  deleteFeedback,
  deleteTrace,
  listAuditLogs,
  listFeedback,
  listTraces,
  updateKnowledgeBase,
} from '@/api/admin'
import { listKnowledgeBases } from '@/api/knowledgeBases'
import type { AuditLogInfo, FeedbackInfo, KnowledgeBaseInfo, TraceInfo, UserInfo } from '@/types'

const tab = ref('users')

// ---------- 用户管理 ----------
const users = ref<UserInfo[]>([])
const loading = ref(false)

const roleLabels: Record<UserInfo['role'], string> = {
  admin: '管理员',
  manager: '部门经理',
  member: '普通成员',
}

const createVisible = ref(false)
const createForm = reactive({
  username: '',
  password: '',
  department: 'default',
  role: 'member' as UserInfo['role'],
})
const creating = ref(false)

async function load() {
  loading.value = true
  try {
    users.value = await listUsers()
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  creating.value = true
  try {
    await createUser({ ...createForm })
    ElMessage.success('用户已创建')
    createVisible.value = false
    createForm.username = ''
    createForm.password = ''
    load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

async function onChangeRole(row: UserInfo, role: UserInfo['role']) {
  await updateUser(row.id, { role })
  ElMessage.success('角色已更新')
  load()
}

async function onChangeDepartment(row: UserInfo, department: string) {
  await updateUser(row.id, { department })
  ElMessage.success('部门已更新')
  load()
}

async function onToggleActive(row: UserInfo, isActive: boolean) {
  await updateUser(row.id, { is_active: isActive })
  ElMessage.success(isActive ? '已启用' : '已禁用')
  load()
}

// ---------- 审计日志 ----------
const auditLogs = ref<AuditLogInfo[]>([])
const auditLoading = ref(false)
const auditTotal = ref(0)
const auditPage = ref(1)
const AUDIT_PAGE_SIZE = 20

const actionLabels: Record<string, string> = {
  'document.upload': '上传',
  'document.update': '升级',
  'document.retry': '重试',
  'document.delete': '删除',
  'feedback.delete': '删除反馈',
  'feedback.batch_delete': '批量删除反馈',
  'feedback.clear': '清空反馈',
  'trace.delete': '删除追踪',
  'trace.batch_delete': '批量删除追踪',
  'trace.clear': '清空追踪',
  'audit.cleanup': '清理审计',
}

async function loadAuditLogs() {
  auditLoading.value = true
  try {
    const page = await listAuditLogs(auditPage.value, AUDIT_PAGE_SIZE)
    auditLogs.value = page.items
    auditTotal.value = page.total
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载审计日志失败')
  } finally {
    auditLoading.value = false
  }
}

function actionLabel(action: string): string {
  return actionLabels[action] ?? action
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function onAuditPageChange(page: number) {
  auditPage.value = page
  loadAuditLogs()
}

// 审计日志只能按时间清理（留痕数据，不提供单删/批量删）
const auditCleanDays = ref(30)
const cleaningAudit = ref(false)

async function onCleanupAudit() {
  const days = auditCleanDays.value
  try {
    await ElMessageBox.confirm(
      `将删除 ${days} 天前的审计日志，不可恢复。近期留痕保留。`,
      '清理审计日志',
      { type: 'warning', confirmButtonText: '确认清理', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  cleaningAudit.value = true
  try {
    const res = await cleanupAuditLogs(days)
    ElMessage.success(`已清理 ${res.deleted} 条`)
    auditPage.value = 1
    loadAuditLogs()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '清理失败')
  } finally {
    cleaningAudit.value = false
  }
}

// ---------- 知识库管理 ----------
const kbList = ref<KnowledgeBaseInfo[]>([])
const kbLoading = ref(false)
const kbCreateVisible = ref(false)
const kbForm = reactive({ name: '', department: 'hr', description: '' })

async function loadKbs() {
  kbLoading.value = true
  try {
    kbList.value = await listKnowledgeBases()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载知识库失败')
  } finally {
    kbLoading.value = false
  }
}

async function onCreateKb() {
  try {
    await createKnowledgeBase({
      name: kbForm.name.trim(),
      department: kbForm.department.trim(),
      description: kbForm.description.trim() || undefined,
    })
    ElMessage.success('知识库已创建')
    kbCreateVisible.value = false
    kbForm.name = ''
    kbForm.description = ''
    loadKbs()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  }
}

async function onToggleKb(row: KnowledgeBaseInfo, active: boolean) {
  try {
    await updateKnowledgeBase(row.id, { is_active: active })
    ElMessage.success(active ? '已启用' : '已停用')
    loadKbs()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '更新失败')
  }
}

// ---------- 回答反馈 ----------
const feedbackList = ref<FeedbackInfo[]>([])
const feedbackLoading = ref(false)
const feedbackTotal = ref(0)
const feedbackPage = ref(1)
const feedbackSentiment = ref('')
const FEEDBACK_PAGE_SIZE = 20

async function loadFeedback() {
  feedbackLoading.value = true
  try {
    const page = await listFeedback(
      feedbackPage.value,
      FEEDBACK_PAGE_SIZE,
      feedbackSentiment.value || undefined,
    )
    feedbackList.value = page.items
    feedbackTotal.value = page.total
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载反馈失败')
  } finally {
    feedbackLoading.value = false
  }
}

function sentimentLabel(s: string): string {
  return s === 'dislike' ? '点踩' : '点赞'
}

const feedbackSelection = ref<FeedbackInfo[]>([])

async function onDeleteFeedback(row: FeedbackInfo) {
  try {
    await ElMessageBox.confirm(
      `确定删除这条反馈（${(row.question ?? '—').slice(0, 24)}…）？删除后不可恢复。`,
      '删除反馈',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteFeedback(row.id)
    ElMessage.success('已删除')
    loadFeedback()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

async function onBatchDeleteFeedback() {
  const ids = feedbackSelection.value.map((r) => r.id)
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${ids.length} 条反馈？删除后不可恢复。`,
      '批量删除反馈',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res = await batchDeleteFeedback(ids)
    ElMessage.success(`已删除 ${res.deleted} 条`)
    feedbackPage.value = 1
    loadFeedback()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

async function onClearAllFeedback() {
  let input: { value: string } | null
  try {
    input = await ElMessageBox.prompt(
      '清空将删除全部反馈记录，不可恢复。请输入 DELETE 确认。',
      '清空全部反馈',
      {
        type: 'warning',
        inputPlaceholder: '输入 DELETE 确认',
        confirmButtonText: '确认清空',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  if (input.value !== 'DELETE') {
    ElMessage.error('确认失败：请输入 DELETE')
    return
  }
  try {
    const res = await clearAllFeedback()
    ElMessage.success(`已清空 ${res.deleted} 条`)
    feedbackPage.value = 1
    loadFeedback()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '清空失败')
  }
}

// ---------- 调用追踪 ----------
const traces = ref<TraceInfo[]>([])
const tracesLoading = ref(false)
const tracesTotal = ref(0)
const tracesPage = ref(1)
const TRACES_PAGE_SIZE = 20

function parseTiming(raw?: string | null): string {
  if (!raw) return '—'
  try {
    const t = JSON.parse(raw)
    const ms = (k: string) => (t[k] != null ? `${t[k]}ms` : '—')
    return `缓存 ${ms('cache_ms')} · 检索 ${ms('retrieve_ms')} · LLM ${ms('llm_ms')}`
  } catch {
    return raw
  }
}

async function loadTraces() {
  tracesLoading.value = true
  try {
    const page = await listTraces(tracesPage.value, TRACES_PAGE_SIZE)
    traces.value = page.items
    tracesTotal.value = page.total
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载调用追踪失败')
  } finally {
    tracesLoading.value = false
  }
}

const tracesSelection = ref<TraceInfo[]>([])

async function onDeleteTrace(row: TraceInfo) {
  try {
    await ElMessageBox.confirm(
      `确定删除这条调用追踪（${row.question.slice(0, 24)}…）？删除后不可恢复。`,
      '删除调用追踪',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteTrace(row.id)
    ElMessage.success('已删除')
    loadTraces()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

async function onBatchDeleteTraces() {
  const ids = tracesSelection.value.map((r) => r.id)
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${ids.length} 条调用追踪？删除后不可恢复。`,
      '批量删除调用追踪',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res = await batchDeleteTraces(ids)
    ElMessage.success(`已删除 ${res.deleted} 条`)
    tracesPage.value = 1
    loadTraces()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

async function onClearAllTraces() {
  let input: { value: string } | null
  try {
    input = await ElMessageBox.prompt(
      '清空将删除全部调用追踪记录，不可恢复。请输入 DELETE 确认。',
      '清空全部调用追踪',
      {
        type: 'warning',
        inputPlaceholder: '输入 DELETE 确认',
        confirmButtonText: '确认清空',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  if (input.value !== 'DELETE') {
    ElMessage.error('确认失败：请输入 DELETE')
    return
  }
  try {
    const res = await clearAllTraces()
    ElMessage.success(`已清空 ${res.deleted} 条`)
    tracesPage.value = 1
    loadTraces()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '清空失败')
  }
}

watch(tab, (t) => {
  if (t === 'kb') loadKbs()
  if (t === 'feedback') loadFeedback()
  if (t === 'traces') loadTraces()
})

onMounted(load)
</script>

<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="用户管理" name="users">
      <div class="toolbar">
        <h3>用户管理</h3>
        <el-button type="primary" @click="createVisible = true">新建用户</el-button>
      </div>

      <el-table :data="users" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column label="角色" width="160">
          <template #default="{ row }">
            <el-select
              :model-value="row.role"
              @change="(v: any) => onChangeRole(row, v)"
            >
              <el-option
                v-for="(label, value) in roleLabels"
                :key="value"
                :label="label"
                :value="value"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="部门" width="140">
          <template #default="{ row }">
            <el-input
              :model-value="row.department"
              @blur="(e: any) => onChangeDepartment(row, e.target.value)"
            />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_active"
              @change="(v: any) => onToggleActive(row, v)"
            />
          </template>
        </el-table-column>
      </el-table>

      <el-dialog v-model="createVisible" title="新建用户" width="420">
        <el-form label-width="80px">
          <el-form-item label="用户名">
            <el-input v-model="createForm.username" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="createForm.password" type="password" show-password />
          </el-form-item>
          <el-form-item label="部门">
            <el-input v-model="createForm.department" />
          </el-form-item>
          <el-form-item label="角色">
            <el-select v-model="createForm.role">
              <el-option label="普通成员" value="member" />
              <el-option label="部门经理" value="manager" />
              <el-option label="管理员" value="admin" />
            </el-select>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="onCreate">
            创建
          </el-button>
        </template>
      </el-dialog>
    </el-tab-pane>

    <el-tab-pane label="审计日志" name="audit">
      <div class="toolbar">
        <h3>审计日志（文档增删改留痕，提问不记录）</h3>
        <div>
          <span class="cleanup-hint">清理 N 天前：</span>
          <el-input-number
            v-model="auditCleanDays"
            :min="1"
            :max="3650"
            size="default"
            style="width: 110px; margin-right: 8px"
          />
          <el-button type="danger" plain :loading="cleaningAudit" @click="onCleanupAudit">
            清理
          </el-button>
          <el-button @click="loadAuditLogs">刷新</el-button>
        </div>
      </div>

      <el-table :data="auditLogs" v-loading="auditLoading" stripe>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="actor_username" label="操作人" width="120" />
        <el-table-column prop="department" label="部门" width="100" />
        <el-table-column label="动作" width="80">
          <template #default="{ row }">{{ actionLabel(row.action) }}</template>
        </el-table-column>
        <el-table-column prop="object_type" label="对象" width="100" />
        <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
      </el-table>

      <div class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="auditTotal"
          :page-size="AUDIT_PAGE_SIZE"
          :current-page="auditPage"
          @current-change="onAuditPageChange"
        />
      </div>
    </el-tab-pane>

    <el-tab-pane label="知识库" name="kb">
      <div class="toolbar">
        <h3>知识库管理</h3>
        <el-button type="primary" @click="kbCreateVisible = true">新建知识库</el-button>
      </div>
      <el-table :data="kbList" v-loading="kbLoading" stripe>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="department" label="部门" width="120" />
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column prop="document_count" label="文档数" width="90" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_active"
              @change="(v: any) => onToggleKb(row, v)"
            />
          </template>
        </el-table-column>
      </el-table>

      <el-dialog v-model="kbCreateVisible" title="新建知识库" width="440">
        <el-form label-width="70px">
          <el-form-item label="名称">
            <el-input v-model="kbForm.name" placeholder="如：薪酬绩效库" />
          </el-form-item>
          <el-form-item label="部门">
            <el-input v-model="kbForm.department" placeholder="如：hr" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="kbForm.description" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="kbCreateVisible = false">取消</el-button>
          <el-button type="primary" @click="onCreateKb">创建</el-button>
        </template>
      </el-dialog>
    </el-tab-pane>

    <el-tab-pane label="回答反馈" name="feedback">
      <div class="toolbar">
        <h3>回答反馈（点踩数据可导出为 badcase 入评测集）</h3>
        <div>
          <el-select
            v-model="feedbackSentiment"
            placeholder="全部倾向"
            clearable
            size="default"
            style="width: 120px; margin-right: 8px"
            @change="() => { feedbackPage = 1; loadFeedback() }"
          >
            <el-option label="点赞" value="like" />
            <el-option label="点踩" value="dislike" />
          </el-select>
          <el-button
            :disabled="!feedbackSelection.length"
            @click="onBatchDeleteFeedback"
          >
            批量删除
          </el-button>
          <el-button type="danger" plain @click="onClearAllFeedback">
            全部删除
          </el-button>
          <el-button @click="loadFeedback">刷新</el-button>
        </div>
      </div>
      <el-table
        :data="feedbackList"
        v-loading="feedbackLoading"
        stripe
        @selection-change="(rows: FeedbackInfo[]) => feedbackSelection = rows"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="用户" width="120" />
        <el-table-column prop="department" label="部门" width="90" />
        <el-table-column label="倾向" width="80">
          <template #default="{ row }">
            <el-tag :type="row.sentiment === 'dislike' ? 'danger' : 'success'" size="small">
              {{ sentimentLabel(row.sentiment) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="answer" label="回答" min-width="260" show-overflow-tooltip />
        <el-table-column prop="comment" label="评论" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="onDeleteFeedback(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="feedbackTotal"
          :page-size="FEEDBACK_PAGE_SIZE"
          :current-page="feedbackPage"
          @current-change="(p: number) => { feedbackPage = p; loadFeedback() }"
        />
      </div>
    </el-tab-pane>

    <el-tab-pane label="调用追踪" name="traces">
      <div class="toolbar">
        <h3>调用追踪（每次问答：耗时 / token / 缓存命中 / 阶段明细）</h3>
        <div>
          <el-button
            :disabled="!tracesSelection.length"
            @click="onBatchDeleteTraces"
          >
            批量删除
          </el-button>
          <el-button type="danger" plain @click="onClearAllTraces">
            全部删除
          </el-button>
          <el-button @click="loadTraces">刷新</el-button>
        </div>
      </div>
      <el-table
        :data="traces"
        v-loading="tracesLoading"
        stripe
        @selection-change="(rows: TraceInfo[]) => tracesSelection = rows"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="trace-detail">
              <p><b>问题：</b>{{ row.question }}</p>
              <p v-if="row.rewritten_query"><b>改写后查询：</b>{{ row.rewritten_query }}</p>
              <p><b>阶段耗时：</b>{{ parseTiming(row.stage_timing) }}</p>
              <p v-if="row.answer_preview"><b>回答预览：</b>{{ row.answer_preview }}</p>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="department" label="部门" width="90" />
        <el-table-column prop="knowledge_base" label="知识库" width="130">
          <template #default="{ row }">{{ row.knowledge_base || '—' }}</template>
        </el-table-column>
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column label="Token 入/出" width="130">
          <template #default="{ row }">
            {{ row.llm_input_tokens ?? '—' }} / {{ row.llm_output_tokens ?? '—' }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="80">
          <template #default="{ row }">{{ row.latency_ms }}ms</template>
        </el-table-column>
        <el-table-column label="缓存" width="80">
          <template #default="{ row }">
            <el-tag :type="row.cache_hit ? 'success' : 'info'" size="small">
              {{ row.cache_hit ? '命中' : '未中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="拒答" width="70">
          <template #default="{ row }">{{ row.no_answer ? '是' : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="onDeleteTrace(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="tracesTotal"
          :page-size="TRACES_PAGE_SIZE"
          :current-page="tracesPage"
          @current-change="(p: number) => { tracesPage = p; loadTraces() }"
        />
      </div>
    </el-tab-pane>
  </el-tabs>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.cleanup-hint {
  font-size: 13px;
  color: #909399;
  margin-right: 4px;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.trace-detail {
  padding: 8px 16px;
  font-size: 13px;
  color: #555;
}
.trace-detail p {
  margin: 4px 0;
}
</style>
