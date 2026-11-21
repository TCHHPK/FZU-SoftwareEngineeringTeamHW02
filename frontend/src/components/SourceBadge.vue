<template>
  <!-- 出处角标：点击弹出原文片段与来源文件，用于证明结论可追溯 -->
  <el-popover placement="top" width="340" trigger="click">
    <template #reference>
      <el-tag size="small" type="info" style="cursor: pointer; margin-left: 6px;">
        {{ badgeText }}
      </el-tag>
    </template>

    <div>
      <p style="margin: 0 0 6px 0;"><b>出处：</b>{{ badgeText }}</p>
      <p v-if="source.source_file"
         style="margin: 0 0 6px 0; color: #909399; font-size: 12px;">
        文件：{{ source.source_file }}
        <span v-if="source.chapter_title">　｜　{{ source.chapter_title }}</span>
      </p>
      <p style="color: #666; font-size: 13px; line-height: 1.6; margin: 0;">
        “{{ source.quote || '（后端未返回原文片段）' }}”
      </p>
      <p v-if="source.chunk_key"
         style="margin: 8px 0 0 0; color: #c0c4cc; font-size: 11px;">
        证据编号：{{ source.chunk_key }}
      </p>
    </div>
  </el-popover>
</template>

<script setup>
import { computed } from 'vue'

// 直接接收后端 Evidence 结构：
// {chunk_key, source_file, chapter_title, page_num, slide_index, quote}
const props = defineProps({
  source: {
    type: Object,
    default: () => ({})
  }
})

// PDF 显示页码、PPT 显示幻灯片序号；两者都没有时退回章节名
const badgeText = computed(() => {
  const s = props.source || {}
  if (s.page_num) return `第 ${s.page_num} 页`
  if (s.slide_index) return `第 ${s.slide_index} 张幻灯片`
  if (s.chapter_title) return s.chapter_title
  return '查看出处'
})
</script>
