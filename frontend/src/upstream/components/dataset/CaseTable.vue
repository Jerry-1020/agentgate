<script setup lang="ts">
import type { EvaluationCase } from '../../types/dataset'

const props = defineProps<{
  items: EvaluationCase[]
  selectedId: string
  editable: boolean
}>()
const emit = defineEmits<{
  select: [item: EvaluationCase]
  add: []
  copy: [item: EvaluationCase]
  remove: [item: EvaluationCase]
  reorder: [ids: string[]]
}>()

const labels = {
  positive: '正例',
  negative: '负例',
  boundary: '边界',
  easy: '简单',
  medium: '中等',
  hard: '困难',
}

function move(index: number, offset: number) {
  const ids = props.items.map(item => item.id)
  const next = index + offset
  if (next < 0 || next >= ids.length) return
  ;[ids[index], ids[next]] = [ids[next], ids[index]]
  emit('reorder', ids)
}
</script>

<template>
  <section class="dataset-column case-list-panel">
    <div class="dataset-panel-heading">
      <div><span class="step">CASES</span><h2>用例</h2></div>
      <el-button type="primary" size="small" :disabled="!editable" data-testid="add-case" @click="emit('add')">新增用例</el-button>
    </div>
    <div class="case-list">
      <article
        v-for="(item, index) in items"
        :key="item.id"
        class="case-list-item"
        :class="{ selected: item.id === selectedId }"
        :data-testid="`case-item-${item.id}`"
        @click="emit('select', item)"
      >
        <div class="case-list-main">
          <b>{{ item.name }}</b>
          <span>
            <el-tag size="small" effect="plain">{{ labels[item.category] }}</el-tag>
            <el-tag size="small" effect="plain" type="info">{{ labels[item.difficulty] }}</el-tag>
            <small>{{ item.turns.length }} 轮</small>
          </span>
          <small>{{ item.notes || item.tags.join(' · ') || '暂无备注' }}</small>
        </div>
        <div v-if="editable" class="case-row-actions" @click.stop>
          <el-button link size="small" :disabled="index === 0" @click="move(index, -1)">↑</el-button>
          <el-button link size="small" :disabled="index === items.length - 1" @click="move(index, 1)">↓</el-button>
          <el-button link size="small" @click="emit('copy', item)">复制</el-button>
          <el-button link size="small" type="danger" @click="emit('remove', item)">删除</el-button>
        </div>
      </article>
      <el-empty v-if="!items.length" description="草稿中还没有用例" :image-size="80" />
    </div>
  </section>
</template>
