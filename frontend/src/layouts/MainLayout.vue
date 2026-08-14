<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { changePassword } from '@/api/users'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

function logout() {
  auth.logout()
  router.push('/login')
}

// 修改密码（D）
const pwdVisible = ref(false)
const pwdSaving = ref(false)
const pwdForm = reactive({ old: '', next: '', confirm: '' })

function openPwd() {
  pwdForm.old = ''
  pwdForm.next = ''
  pwdForm.confirm = ''
  pwdVisible.value = true
}

async function savePwd() {
  if (!pwdForm.old || !pwdForm.next) {
    ElMessage.warning('请输入原密码和新密码')
    return
  }
  if (pwdForm.next.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.next !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdSaving.value = true
  try {
    await changePassword(pwdForm.old, pwdForm.next)
    ElMessage.success('密码已修改，请重新登录')
    pwdVisible.value = false
    auth.logout()
    router.push('/login')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '修改失败')
  } finally {
    pwdSaving.value = false
  }
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="200px" class="aside">
      <div class="logo">RAG 平台</div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/chat">智能问答</el-menu-item>
        <el-menu-item index="/documents">知识库文档</el-menu-item>
        <el-menu-item v-if="auth.user?.role === 'admin'" index="/admin">管理后台</el-menu-item>
      </el-menu>
      <div class="user-box">
        <span>{{ auth.user?.username }}（{{ auth.user?.department }}）</span>
        <el-button link type="primary" size="small" @click="openPwd">修改密码</el-button>
        <el-button link type="danger" size="small" @click="logout">退出</el-button>
      </div>
    </el-aside>
    <el-main class="main">
      <router-view />
    </el-main>

    <el-dialog v-model="pwdVisible" title="修改密码" width="400">
      <el-form label-width="80px">
        <el-form-item label="原密码">
          <el-input v-model="pwdForm.old" type="password" show-password placeholder="当前密码" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.next" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwdForm.confirm" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="savePwd">确认修改</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #fff;
  border-right: 1px solid #eee;
  display: flex;
  flex-direction: column;
}
.logo {
  font-weight: 700;
  font-size: 18px;
  padding: 18px 20px;
  border-bottom: 1px solid #eee;
}
.user-box {
  margin-top: auto;
  padding: 16px 20px;
  border-top: 1px solid #eee;
  font-size: 13px;
  color: #666;
}
.user-box span {
  display: block;
  margin-bottom: 8px;
}
.main {
  background: #f5f6fa;
}
</style>
