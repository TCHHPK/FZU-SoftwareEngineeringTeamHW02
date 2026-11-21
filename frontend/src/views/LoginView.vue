<template>
  <div class="login-page">
    <div class="bg-orb orb-1"></div>
    <div class="bg-orb orb-2"></div>
    <h1 class="main-project-title">大学生课程课件笔记整理与知识梳理 Agent</h1>
    <el-card class="login-card">
      <h2 class="login-title">登录系统</h2>

      <el-form :model="form" @submit.prevent="handleLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="请输入账号" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input 
            v-model="form.password" 
            type="password" 
            placeholder="请输入密码" 
            show-password 
            size="large"
            @keyup.enter="handleLogin" 
          />
        </el-form-item>
        <el-button 
          type="primary" 
          native-type="submit" 
          size="large" 
          style="width: 100%;" 
          :loading="loading"
        >
          登录
        </el-button>
      </el-form>

      <div style="text-align: center; margin-top: 15px; font-size: 14px;">
        <span style="color: #666;">没有账号？</span>
        <el-link type="primary" @click="$router.push('/register')">去注册</el-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/utils/http'

const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function handleLogin() {
  if (!form.username || !form.password) return ElMessage.warning('请输入账号和密码')
  
  loading.value = true
  try {
    // 直接拿返回的数据
    const res = await http.post('/auth/login', form)
    
    ElMessage.success('登录成功！')
    if (res.token) localStorage.setItem('token', res.token)
    router.push('/upload')
  } catch (error) {
    console.error(error)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  background-image: url('@/assets/login-bg.jpg');
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  background-color: #e0eafc;
  position: relative;
  overflow: hidden;
}

/* 扫光动画 */
.login-page::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background: linear-gradient(115deg, transparent 30%, rgba(255, 255, 255, 0.4) 50%, transparent 70%) 0 0 / 250% 100%;
  animation: shine 6s linear infinite;
}
@keyframes shine {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* 大标题 */
.main-project-title {
  color: #1a2a6c;
  text-align: center;
  letter-spacing: 2px;
  text-shadow: 0 4px 10px rgba(255, 255, 255, 0.8);
  z-index: 10;
  margin-bottom: 30px;
  font-size: 32px;
  font-weight: 800;
}

/* 浮动光球 */
.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  z-index: 1;
  opacity: 0.6;
  animation: floatOrb 8s ease-in-out infinite alternate;
}
.orb-1 { background: #a1c4fd; width: 300px; height: 300px; top: 10%; left: 15%; }
.orb-2 { background: #c2e9fb; width: 400px; height: 400px; bottom: 10%; right: 15%; animation-delay: -4s; }
@keyframes floatOrb {
  0%   { transform: translate(0) scale(1); }
  100% { transform: translate(30px, -30px) scale(1.1); }
}

/* 玻璃卡片 */
.login-card {
  backdrop-filter: blur(15px);
  -webkit-backdrop-filter: blur(15px);
  z-index: 10;
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: 12px;
  width: 400px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15) !important;
  background: rgba(255, 255, 255, 0.4) !important;
}

.login-title {
  text-align: center;
  margin-bottom: 25px;
  font-size: 24px;
  color: #303133;
  font-weight: 600;
}

/* 透明输入框 */
:deep(.el-form-item) { background: transparent !important; }
:deep(.el-input) { --el-input-bg-color: transparent !important; background: transparent !important; }
:deep(.el-input__wrapper) {
  padding: 1px 11px;
  background: transparent !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.8) !important;
}
:deep(.el-input__wrapper.is-focus) {
  background: rgba(255, 255, 255, 0.2) !important;
  box-shadow: inset 0 0 0 1px #409eff !important;
}
:deep(.el-input__inner) { color: #333 !important; background: transparent !important; }
</style>