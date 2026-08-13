<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

function logout() {
  auth.logout()
  router.push('/login')
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
        <el-button link type="danger" @click="logout">退出</el-button>
      </div>
    </el-aside>
    <el-main class="main">
      <router-view />
    </el-main>
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
