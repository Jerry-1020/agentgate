<script setup lang="ts">
import type { DatasetVersion } from '../../types/dataset'

defineProps<{
  versions: DatasetVersion[]
  activeId: string
  busy?: boolean
}>()
const emit = defineEmits<{
  select: [version: DatasetVersion]
  createDraft: [base: number|null]
  publish: []
  discard: []
  export: [version: number]
  exportExcel: [version: number]
}>()
</script>

<template>
  <div class="version-toolbar">
    <div class="version-tabs" aria-label="评测集版本">
      <button
        v-for="item in versions"
        :key="item.id"
        :class="{ active: item.id === activeId }"
        :data-testid="`version-${item.status}-${item.version ?? 'draft'}`"
        @click="emit('select', item)"
      >
        <span>{{ item.status === 'draft' ? '编辑草稿' : `已发布 v${item.version}` }}</span>
        <small>{{ item.status === 'draft' ? (item.based_on_version == null ? '尚未发布' : `基于 v${item.based_on_version}`) : '已发布 · 只读' }}</small>
      </button>
    </div>
    <div class="version-actions">
      <template v-if="versions.find(item => item.id === activeId)?.status === 'draft'">
        <el-button size="small" @click="emit('discard')">放弃草稿</el-button>
        <el-button type="success" size="small" :loading="busy" data-testid="publish-draft" @click="emit('publish')">发布</el-button>
      </template>
      <template v-else>
        <el-button
          size="small"
          v-if="!versions.some(item => item.status === 'draft')"
          :disabled="busy"
          data-testid="create-draft"
          @click="emit('createDraft', versions.find(item => item.id === activeId)?.version ?? null)"
        >{{versions.find(item => item.id === activeId)?.version ? `基于 v${versions.find(item => item.id === activeId)?.version} 创建草稿` : '创建空白草稿'}}</el-button>
        <el-button v-if="versions.find(item=>item.id===activeId)?.version" size="small" @click="emit('exportExcel', versions.find(item=>item.id===activeId)!.version!)">导出 Excel</el-button>
        <el-button
          v-if="versions.find(item => item.id === activeId)?.version"
          size="small"
          @click="emit('export', versions.find(item => item.id === activeId)!.version!)"
        >导出 JSON</el-button>
      </template>
    </div>
  </div>
</template>
