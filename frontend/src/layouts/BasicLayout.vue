<template>
  <el-container style="height: 100vh;">
    <!-- 左侧菜单栏（带毛玻璃特效） -->
    <el-aside width="200px" class="glass-aside">
      <div style="padding: 20px; font-weight: bold; font-size: 18px; color: #303133;">
        课程笔记 Agent
      </div>
      
      <el-menu router :default-active="$route.path" style="background: transparent; border-right: none;">
        <el-menu-item v-if="features.upload !== false" index="/upload">上传课件</el-menu-item>
        <el-menu-item v-if="features.sessions !== false" index="/sessions">历史任务</el-menu-item>
        <el-menu-item v-if="features.self_test !== false" index="/self-tests">智能自测</el-menu-item>
        <el-menu-item v-if="features.wrong_book !== false" index="/wrong-book">错题本</el-menu-item>
        <el-menu-item v-if="features.chat !== false" index="/chat">问答</el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 右侧内容区 -->
    <el-container>
      <el-header style="display: flex; justify-content: flex-end; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.3); background: rgba(255,255,255,0.2); backdrop-filter: blur(5px);">
        <el-button link @click="handleLogout">退出登录</el-button>
      </el-header>
      
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import http from '@/utils/http'
import { ElMessage } from 'element-plus'

const router = useRouter()
const features = ref({})

onMounted(async () => {
  try {
    const res = await http.get('/meta')
    features.value = res?.features || {}
    console.log('功能开关状态:', features.value)
  } catch (e) {
    console.log('获取功能开关失败，默认全部显示')
    features.value = { chat: true, sessions: true, upload: true } 
  }
})

async function handleLogout() {
  try {
    await http.post('/auth/logout')
  } catch (e) {
    // 忽略后端报错，强制前端退出
  }
  localStorage.removeItem('token')
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
/* 左侧菜单毛玻璃样式 */
.glass-aside {
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(10px);
  border-right: 1px solid rgba(255, 255, 255, 0.5);
}
</style>