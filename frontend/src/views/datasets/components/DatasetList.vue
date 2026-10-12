<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { DatasetSummary } from '../types/index';

const props = defineProps<{
  items: DatasetSummary[];
  selectedId: string;
  loading?: boolean;
}>();
const emit = defineEmits<{
  select: [id: string];
  create: [];
  copy: [item: DatasetSummary];
  archive: [item: DatasetSummary];
  import: [];
}>();

const query = ref('');
const group = ref('demo');
function category(item: DatasetSummary) {
  return item.id === 'loan-risk-policy'
    ? 'demo'
    : item.name.startsWith('集成验证-')
      ? 'validation'
      : item.description.startsWith('Regression source Run:')
        ? 'regression'
        : 'business';
}
const filtered = computed(() => {
  const value = query.value.trim().toLowerCase();
  const scoped = props.items.filter(
    (item) => group.value === 'all' || category(item) === group.value,
  );
  if (!value) return scoped;
  return scoped.filter(
    (item) =>
      item.name.toLowerCase().includes(value) || item.description.toLowerCase().includes(value),
  );
});
const currentPage = ref(1);
watch([query, group], () => (currentPage.value = 1));
watch(
  [() => props.selectedId, () => props.items],
  ([id]) => {
    const item = props.items.find((e) => e.id === id);
    if (item && group.value !== 'all' && category(item) !== group.value)
      group.value = category(item);
    const index = filtered.value.findIndex((e) => e.id === id);
    if (index >= 0) currentPage.value = Math.floor(index / 10) + 1;
  },
  { immediate: true },
);
const pageItems = computed(() =>
  filtered.value.slice((currentPage.value - 1) * 10, currentPage.value * 10),
);
</script>

<template>
  <aside class="dataset-column dataset-list-panel">
    <div class="dataset-panel-heading">
      <div>
        <span class="step">DATASETS</span>
        <h2>测评集</h2>
      </div>
    </div>
    <el-input v-model="query" clearable placeholder="搜索测评集" aria-label="搜索测评集" />
    <select class="input" v-model="group" aria-label="测评集分类">
      <option value="all">全部测评集</option>
      <option value="demo">内置业务样例</option>
      <option value="business">业务测评集</option>
      <option value="regression">回归草稿与集合</option>
      <option value="validation">自动集成验证记录</option>
    </select>
    <p class="muted">同名不代表同一资产。按来源、时间与 ID 区分；验证记录可单独筛选。</p>
    <div v-loading="loading" class="dataset-list">
      <button
        v-for="item in pageItems"
        :key="item.id"
        class="dataset-list-item"
        :class="{ selected: item.id === selectedId }"
        :data-testid="`dataset-item-${item.id}`"
        @click="emit('select', item.id)"
      >
        <span
          ><b>{{ item.name }}</b
          ><small>{{ item.description || '暂无描述' }}</small></span
        >
        <span class="dataset-badges">
          <el-tag size="small" effect="plain">v{{ item.version ?? '—' }}</el-tag>
          <el-tag v-if="item.has_draft" size="small" type="warning">草稿</el-tag>
          <small>{{ item.case_count }} 已发布样本{{ item.has_draft ? ' · 另有草稿' : '' }}</small
          ><small
            >{{ new Date(item.created_at).toLocaleString() }} · {{ item.id.slice(0, 8) }}</small
          >
        </span>
      </button>
      <el-empty v-if="!filtered.length" description="暂无测评集" :image-size="72" />
    </div>
    <div class="toolbar">
      <button class="link" :disabled="currentPage <= 1" @click="currentPage--">上一页</button
      ><small>{{ currentPage }} / {{ Math.max(1, Math.ceil(filtered.length / 10)) }}</small
      ><button class="link" :disabled="currentPage * 10 >= filtered.length" @click="currentPage++">
        下一页
      </button>
    </div>
    <div class="dataset-list-actions">
      <el-button size="small" @click="emit('import')">导入 JSON</el-button>
      <el-dropdown v-if="items.find((item) => item.id === selectedId)" trigger="click">
        <el-button size="small">更多</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="emit('copy', items.find((item) => item.id === selectedId)!)"
              >复制测评集</el-dropdown-item
            >
            <el-dropdown-item
              divided
              @click="emit('archive', items.find((item) => item.id === selectedId)!)"
              >归档测评集</el-dropdown-item
            >
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </aside>
</template>
