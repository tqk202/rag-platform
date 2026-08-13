import { defineStore } from 'pinia'
import { login as apiLogin, register as apiRegister } from '@/api/auth'
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
  },
})
