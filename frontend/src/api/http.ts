import axios from 'axios'

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

// 请求拦截：自动带上 JWT
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：登录/注册接口的 401 是"用户名或密码错误"，交回页面提示；
// 其他接口 401 才是令牌失效，统一清会话并跳登录。
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error.response?.status
    const url: string = error.config?.url ?? ''
    if (status === 401 && !url.includes('/auth/')) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export default http
