import http from './http'
import type { UserInfo } from '@/types'

export interface CreateUserPayload {
  username: string
  password: string
  department: string
  role: UserInfo['role']
}

export interface UpdateUserPayload {
  role?: UserInfo['role']
  department?: string
  is_active?: boolean
}

export function listUsers() {
  return http.get<UserInfo[]>('/users').then((r) => r.data)
}

export function createUser(data: CreateUserPayload) {
  return http.post<UserInfo>('/users', data).then((r) => r.data)
}

export function updateUser(id: number, data: UpdateUserPayload) {
  return http.patch<UserInfo>(`/users/${id}`, data).then((r) => r.data)
}
