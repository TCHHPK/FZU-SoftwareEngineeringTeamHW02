<template>
  <div style="padding: 40px; max-width: 820px; margin: 0 auto;">
    <h2>{{ appendMode ? '补充材料' : '上传课件' }}</h2>

    <!-- 追加材料时说明当前任务已有的材料，避免用户以为在新建任务 -->
    <el-alert
      v-if="appendMode"
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px;"
    >
      <template #title>
        将追加到《{{ appendCourse }}》（当前已有 {{ appendDocIds.length }} 份材料）
      </template>
      新上传的材料会与已有材料一起重新整理，生成一份合并后的新笔记；原任务保留。
    </el-alert>

    <!-- 可选：排除写错的旧材料。系统不会自动判定哪句对错，由使用者决定带哪几份 -->
    <el-card v-if="appendMode && appendDocs.length" shadow="never" style="margin-bottom: 16px;">
      <div style="font-size: 13px; color: #606266; margin-bottom: 8px;">
        选择本次要参与整理的材料（默认全选）：
      </div>
      <el-checkbox-group v-model="selectedDocIds">
        <el-checkbox
          v-for="d in appendDocs"
          :key="d.doc_id"
          :label="d.doc_id"
          :value="d.doc_id"
          style="display: block; margin-bottom: 4px;"
        >
          {{ d.source_file }}
          <span v-if="d.chunk_count" style="color: #909399; font-size: 12px;">
            （{{ d.chunk_count }} 段）
          </span>
        </el-checkbox>
      </el-checkbox-group>
      <div style="margin-top: 8px;">
        <el-button size="small" text type="primary" @click="selectAllDocs">全选</el-button>
        <el-button size="small" text @click="selectedDocIds = []">全不选</el-button>
        <span style="color: #e6a23c; font-size: 12px;">
          提示：若旧材料里某段表述有误，取消勾选它，本次整理就不会带上。
        </span>
      </div>
    </el-card>

    <el-form label-width="80px" style="margin-top: 12px;">
      <el-form-item label="课程">
        <!-- filterable + allow-create：既能选已有课程，也能直接输入新课程名 -->
        <el-select
          v-model="courseName"
          filterable
          allow-create
          default-first-option
          :disabled="appendMode"
          placeholder="选择或直接输入课程名（如：软件工程）"
          style="width: 100%;"
        >
          <el-option v-for="c in courseOptions" :key="c" :label="c" :value="c" />
        </el-select>
      </el-form-item>

      <el-form-item label="文件">
        <el-upload
          drag
          action="#"
          :auto-upload="false"
          :limit="1"
          :on-change="handleFileChange"
          :on-remove="handleRemove"
          style="width: 100%;"
        >
          <el-icon class="el-icon--upload"><upload-filled /></el-icon>
          <div class="el-upload__text">
            拖拽文件到此处，或 <em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              支持格式：{{ allowedText }}
              <span v-if="maxMb">　｜　单文件不超过 {{ maxMb }} MB</span>
            </div>
          </template>
        </el-upload>
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :loading="uploading" @click="submitUpload">
          {{ appendMode ? '上传并合并整理' : '上传并解析' }}
        </el-button>
        <el-button v-if="appendMode" @click="router.push('/sessions')">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import http from '@/utils/http'

const route = useRoute()
const router = useRouter()

const courseName = ref('')
const courseOptions = ref(['软件工程', '数据结构'])
const fileRaw = ref(null)
const uploading = ref(false)
const allowedExts = ref(['.pdf', '.pptx', '.docx', '.txt', '.md', '.html', '.csv', '.epub'])
const maxMb = ref(50)

const appendSessionId = computed(() => route.query.append || '')
const appendMode = computed(() => !!appendSessionId.value)
const appendCourse = ref('')
const appendDocIds = ref([])
// 追加时可勾选参与整理的材料（默认全选）
const appendDocs = ref([])
const selectedDocIds = ref([])

function selectAllDocs() {
  selectedDocIds.value = appendDocs.value.map(d => d.doc_id)
}

const allowedText = computed(() =>
  allowedExts.value.map(e => e.replace('.', '').toUpperCase()).join(' / ')
)

// 以服务端配置为准，避免前后端格式列表不一致（原实现写死只允许 pdf/ppt/pptx）
onMounted(async () => {
  try {
    const meta = await http.get('/meta')
    if (meta?.allowed_extensions?.length) allowedExts.value = meta.allowed_extensions
    if (meta?.max_upload_mb) maxMb.value = meta.max_upload_mb
  } catch (e) {
    console.warn('读取服务端格式配置失败，使用默认值', e)
  }

  try {
    // 后端真实接口是 /uploads/courses（之前写成 /courses 会走 SPA 回退拿到 HTML）
    const list = await http.get('/uploads/courses')
    const names = (list || [])
      .map(c => (typeof c === 'string' ? c : (c.course_name || c.name)))
      .filter(Boolean)
    if (names.length) courseOptions.value = [...new Set([...names, ...courseOptions.value])]
  } catch (e) {
    console.warn('读取课程列表失败，使用默认选项', e)
  }

  // 追加模式：取原任务的课程名与已有材料
  if (appendSessionId.value) {
    try {
      const session = await http.get(`/sessions/${appendSessionId.value}`)
      appendCourse.value = session.course_name || ''
      appendDocIds.value = session.doc_ids || []
      courseName.value = appendCourse.value
      if (!appendDocIds.value.length) {
        ElMessage.warning('未读到原任务的材料，将按新任务处理')
      }

      // 取材料文件名，供勾选；失败也允许继续（退化为全部带上）
      try {
        const docs = await http.get('/uploads')
        const wanted = new Set(appendDocIds.value)
        appendDocs.value = (docs || []).filter(d => wanted.has(d.doc_id))
        selectAllDocs()
      } catch (err) {
        console.warn('读取材料列表失败，将带上全部已有材料', err)
        selectAllDocs()
      }
    } catch (e) {
      ElMessage.error('读取原任务失败，请回到历史任务重试')
    }
  }
})

function extOf(name) {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

function handleFileChange(file) {
  const ext = extOf(file.name)
  if (!allowedExts.value.includes(ext)) {
    ElMessage.error(`不支持的格式：${ext || '未知'}。可用：${allowedText.value}`)
    fileRaw.value = null
    return
  }
  if (maxMb.value && file.size > maxMb.value * 1024 * 1024) {
    ElMessage.error(`文件过大（${(file.size / 1024 / 1024).toFixed(1)} MB），上限 ${maxMb.value} MB`)
    fileRaw.value = null
    return
  }
  fileRaw.value = file.raw
  ElMessage.success(`已选择：${file.name}`)
}

function handleRemove() {
  fileRaw.value = null
}

async function submitUpload() {
  if (!courseName.value.trim()) return ElMessage.warning('请选择或输入课程名')
  if (!fileRaw.value) return ElMessage.warning('请选择文件')

  const formData = new FormData()
  formData.append('file', fileRaw.value)
  formData.append('course_name', courseName.value.trim())

  uploading.value = true
  try {
    const data = await http.post('/uploads', formData)
    const docId = data?.document?.doc_id
    if (data?.warnings?.length) ElMessage.warning(data.warnings[0])
    if (!docId) {
      ElMessage.error('未能获取文档 ID')
      return
    }

    // 追加模式：带上用户勾选的旧材料 + 新材料；未勾选写错的旧材料就不会参与
    const kept = appendMode.value ? selectedDocIds.value : []
    const docIds = [...new Set([...kept, docId])]

    const sessionData = await http.post('/sessions', {
      doc_ids: docIds,
      course_name: courseName.value.trim(),
      task_type: 'note',
      exam_scope: ''
    })

    const sessionId = typeof sessionData === 'object'
      ? (sessionData.session_id ?? sessionData.id)
      : sessionData

    if (!sessionId) {
      ElMessage.error('未返回任务 ID')
      return
    }
    ElMessage.success(
      docIds.length > 1
        ? `已发起整理：${docIds.length} 份材料合并`
        : '任务已发起，开始生成笔记'
    )
    router.push(`/sessions/${sessionId}/progress`)
  } catch (error) {
    console.error('上传失败', error)
  } finally {
    uploading.value = false
  }
}
</script>

<style scoped>
/* 毛玻璃拖拽上传框 */
:deep(.el-upload-dragger) {
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  background-color: rgba(255, 255, 255, 0.4) !important;
  border: 1px dashed rgba(255, 255, 255, 0.8) !important;
}
:deep(.el-upload-dragger:hover) {
  background-color: rgba(255, 255, 255, 0.6) !important;
}

/* 毛玻璃下拉框 */
:deep(.el-select__wrapper) {
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
  background-color: rgba(255, 255, 255, 0.2) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2) !important;
}

/* 毛玻璃输入框 */
:deep(.el-input__wrapper) {
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
  background-color: rgba(255, 255, 255, 0.2) !important;
}
</style>
