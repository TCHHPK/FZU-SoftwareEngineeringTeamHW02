import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

// 创建 axios 实例
const http = axios.create({
  baseURL: '/api', // 因为我们配了 Vite 代理，所以这里统一写 /api
  timeout: 120000, // 整理笔记需要时间，超时设长一点（2分钟）
  withCredentials: true
})

// 请求拦截器（发出去之前先检查）
http.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器（收到回复后统一处理）
http.interceptors.response.use(
  res => {
    // 如果是下载文件（blob），直接返回，不走统一格式解析
    if (res.config.responseType === 'blob') {
      return res.data
    }
    
    const body = res.data
    if (body && body.code === 0) {
      return body.data // 成功，直接把数据给页面
    }
    
    // 如果 code 不是 0，说明后端返回了业务错误
    ElMessage.error(body?.message || '请求失败')
    return Promise.reject(new Error(body?.message || '请求失败'))
  },
  err => {
    // 处理 HTTP 错误状态码
    if (err.response?.status === 401) {
      // 401：无权限（未登录或登录过期）
      localStorage.removeItem('token')
      ElMessage.error('登录已过期，请重新登录')
      router.push('/login')
    } else if (err.response?.status === 422) {
      // 422：参数校验失败
      ElMessage.error('请求参数错误，请检查输入')
    } else if (err.response?.status === 500) {
      // 500：后端服务器错误
      ElMessage.error('服务器内部错误，请联系管理员')
    } else {
      // 其他错误
      const msg = err.response?.data?.message || err.message || '网络错误'
      ElMessage.error(msg)
    }
    return Promise.reject(err)
  }
)

export default http