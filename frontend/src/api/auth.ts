import http from './http'
import type { UserInfo } from '@/types'

export interface LoginPayload {
  username: string
  password: string
}

export interface RegisterPayload {
  username: string
  password: string
  department: string
}

export function login(data: LoginPayload) {
  return http
    .post<{ access_token: string; token_type: string }>('/auth/login', data)
    .then((r) => r.data)
}

export function register(data: RegisterPayload) {
  return http.post<UserInfo>('/auth/register', data).then((r) => r.data)
}

export function getMe() {
  return http.get<UserInfo>('/users/me').then((r) => r.data)
}
