<template>
  <div class="register-page">
    <el-card class="register-card">
      <h2 class="register-title">注册账号</h2>

      <el-form :model="form" @submit.prevent="handleRegister">
        <el-form-item>
          <el-input v-model="form.username" placeholder="请输入用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password size="large" />
        </el-form-item>
        <el-button type="primary" native-type="submit" size="large" style="width: 100%;" :loading="loading">
          注册
        </el-button>
      </el-form>

      <div style="text-align: center; margin-top: 15px; font-size: 14px;">
        <span style="color: #666;">已有账号？</span>
        <el-link type="primary" @click="$router.push('/login')">去登录</el-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/utils/http' // 👈 使用总机

const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function handleRegister() {
  if (!form.username || !form.password) return ElMessage.warning('请输入账号和密码')
  
  loading.value = true
  try {
    // 调用注册接口
    await http.post('/auth/register', form)
    
    // 因为拦截器处理过，能走到这里说明肯定是成功的
    ElMessage.success('注册成功，请登录！')
    router.push('/login')
  } catch (error) {
    // 拦截器已经弹红字了，这里不用写提示
    console.error(error)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-page {
  width: 100vw;
  height: 100vh;
  display: flex;
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
.register-page::before {
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

/* 玻璃卡片 */
.register-card {
  backdrop-filter: blur(15px);
  -webkit-backdrop-filter: blur(15px);
  z-index: 10;
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: 12px;
  width: 400px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15) !important;
  background: rgba(255, 255, 255, 0.4) !important;
}

.register-title {
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