import { defineStore } from 'pinia'
import { getMe, login as apiLogin, register as apiRegister } from '@/api/auth'
import type { UserInfo } from '@/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: JSON.parse(localStorage.getItem('user') || 'null') as UserInfo | null,
  }),
  actions: {
    async login(username: string, password: string) {
      const { access_token } = await apiLogin({ username, password })
      this.token = access_token
      localStorage.setItem('token', access_token)
      // 登录后必须拉当前用户信息，否则侧边栏/上传按钮/路由守卫的
      // role 判断全部失效（auth.user 为 null）
      const me = await getMe()
      this.setUser(me)
    },
    async register(username: string, password: string, department: string) {
      const user = await apiRegister({ username, password, department })
      this.user = user
    },
    setUser(user: UserInfo) {
      this.user = user
      localStorage.setItem('user', JSON.stringify(user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('token')
      localStorage.removeItem('user')
    },
    // 页面刷新后 token 还在但 user 丢失时，用 /users/me 恢复当前用户
    async restore() {
      if (!this.token || this.user) return
      try {
        const me = await getMe()
        this.setUser(me)
      } catch {
        this.logout()
      }
    },
  },
})
