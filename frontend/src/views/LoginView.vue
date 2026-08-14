<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { listDepartments, type DepartmentInfo } from '@/api/auth'

const router = useRouter()
const auth = useAuthStore()

const tab = ref<'login' | 'register'>('login')
const form = ref({ username: '', password: '', department: '' })
const loading = ref(false)

// 部门下拉选项：注册页公开接口动态拉取，单一来源（后端配置）
const departments = ref<DepartmentInfo[]>([])

async function submit() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  if (tab.value === 'register' && !form.value.department) {
    ElMessage.warning('请选择部门')
    return
  }
  loading.value = true
  try {
    if (tab.value === 'register') {
      await auth.register(form.value.username, form.value.password, form.value.department)
    }
    await auth.login(form.value.username, form.value.password)
    ElMessage.success('登录成功')
    router.push('/chat')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    departments.value = await listDepartments()
    if (departments.value.length) form.value.department = departments.value[0].value
  } catch {
    // 拉不到部门选项时保持为空，提交时会被「请选择部门」拦截
  }
})
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2 class="title">企业知识库 RAG 平台</h2>
      <el-tabs v-model="tab">
        <el-tab-pane label="登录" name="login">
          <el-form @submit.prevent>
            <el-form-item>
              <el-input v-model="form.username" placeholder="用户名" />
            </el-form-item>
            <el-form-item>
              <el-input v-model="form.password" type="password" placeholder="密码" show-password />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="注册" name="register">
          <el-form @submit.prevent>
            <el-form-item>
              <el-input v-model="form.username" placeholder="用户名（至少3位）" />
            </el-form-item>
            <el-form-item>
              <el-input v-model="form.password" type="password" placeholder="密码（至少6位）" show-password />
            </el-form-item>
            <el-form-item>
              <el-select
                v-model="form.department"
                placeholder="请选择部门（决定知识库权限范围）"
                style="width: 100%"
              >
                <el-option
                  v-for="d in departments"
                  :key="d.value"
                  :label="d.label"
                  :value="d.value"
                />
              </el-select>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <el-button type="primary" class="submit" :loading="loading" @click="submit">
        {{ tab === 'login' ? '登录' : '注册并登录' }}
      </el-button>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f2f5;
}
.login-card {
  width: 400px;
}
.title {
  text-align: center;
  margin: 8px 0 20px;
}
.submit {
  width: 100%;
  margin-top: 8px;
}
</style>
