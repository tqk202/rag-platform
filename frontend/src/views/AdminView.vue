<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createUser, listUsers, updateUser } from '@/api/users'
import type { UserInfo } from '@/types'

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

onMounted(load)
</script>

<template>
  <div>
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
