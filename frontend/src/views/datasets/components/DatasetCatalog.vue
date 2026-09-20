<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { DatasetSummary } from '../types/index';
const props = defineProps<{ items: DatasetSummary[]; loading?: boolean }>();
const emit = defineEmits<{
  select: [id: string];
  edit: [id: string];
  archive: [item: DatasetSummary];
  restore: [item: DatasetSummary];
  remove: [item: DatasetSummary];
}>();
const query = ref(''),
  status = ref('all'),
  page = ref(1);
const filtered = computed(() =>
  props.items
    .filter(
      (item) =>
        !item.archived &&
        (['all', 'archived'].includes(status.value) ||
          (status.value === 'unpublished'
            ? item.version === null
            : status.value === 'changes'
              ? item.version !== null && item.has_draft
              : !item.has_draft && item.version !== null)) &&
        `${item.name} ${item.description} ${item.id}`
          .toLowerCase()
          .includes(query.value.trim().toLowerCase()),
    )
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)),
);
watch([query, status], () => (page.value = 1));
watch(
  () => filtered.value.length,
  () => (page.value = Math.min(page.value, Math.max(1, Math.ceil(filtered.value.length / 10)))),
);
const rows = computed(() => filtered.value.slice((page.value - 1) * 10, page.value * 10));
</script>
<template>
  <section class="dataset-catalog" v-loading="loading" data-testid="dataset-catalog">
    <div class="catalog-filters">
      <el-input
        v-model="query"
        clearable
        placeholder="搜索评测集名称或 ID"
        aria-label="搜索评测集"
      />
      <select v-model="status" class="input" aria-label="评测集状态">
        <option value="all">全部评测集</option>
        <option value="unpublished">未发布</option>
        <option value="changes">有待发布修改</option>
      </select>
    </div>
    <div class="catalog-grid">
      <article
        v-for="item in rows"
        :key="item.id"
        class="dataset-tile"
        :data-testid="`dataset-item-${item.id}`"
      >
        <button class="tile-open" @click="emit('select', item.id)">
          <div class="tile-top">
            <span class="tile-icon">▤</span>
            <h2>{{ item.name }}</h2>
            <span class="version-badge">{{
              item.version === null ? '草稿' : 'v' + item.version
            }}</span>
          </div>
          <p>{{ item.description || '暂无备注' }}</p>
          <el-tag :type="item.archived ? 'info' : item.has_draft ? 'warning' : 'success'">{{
            item.archived
              ? '已归档'
              : item.version === null
                ? '未发布草稿'
                : item.has_draft
                  ? '有待发布修改'
                  : '已发布'
          }}</el-tag>
          <p>
            {{ item.version === null ? '草稿 · 点击管理样本' : item.case_count + ' 条已发布样本'
            }}{{ item.version !== null && item.has_draft ? ' · 有待发布修改' : '' }}
          </p>
          <div class="tile-bottom">
            <small>更新于 {{ new Date(item.updated_at).toLocaleString() }}</small>
          </div>
        </button>
        <div class="tile-actions">
          <el-dropdown trigger="click"
            ><button class="link" :aria-label="item.name + '更多操作'">…</button
            ><template #dropdown
              ><el-dropdown-menu
                ><el-dropdown-item @click="emit('select', item.id)">查看详情</el-dropdown-item
                ><el-dropdown-item :disabled="!item.has_draft" @click="emit('edit', item.id)"
                  >编辑草稿</el-dropdown-item
                ><el-dropdown-item divided @click="emit('remove', item)"
                  >删除</el-dropdown-item
                ></el-dropdown-menu
              ></template
            ></el-dropdown
          >
        </div>
      </article>
    </div>
    <el-empty v-if="!loading && !filtered.length" description="暂无符合条件的评测集" />
    <div class="catalog-pagination">
      <span>共 {{ filtered.length }} 个</span
      ><button class="link" :disabled="page <= 1" @click="page--">上一页</button
      ><span>{{ page }} / {{ Math.max(1, Math.ceil(filtered.length / 10)) }}</span
      ><button class="link" :disabled="page * 10 >= filtered.length" @click="page++">下一页</button>
    </div>
  </section>
</template>
<style scoped>
.dataset-catalog {
  padding: 24px;
}
.catalog-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 20px;
}
.dataset-tile {
  position: relative;
  border: 1px solid #dce5e3;
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: white;
}
.dataset-tile:hover {
  border-color: #0aae92;
  box-shadow: 0 4px 14px #00836f12;
}
.tile-open {
  border: 0;
  background: transparent;
  text-align: left;
  padding: 24px 20px 18px;
  cursor: pointer;
  flex: 1;
  color: inherit;
  width: 100%;
}
.tile-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-right: 12px;
}
.tile-top h2 {
  flex: 1;
  font-size: 16px;
  margin: 0;
}
.version-badge {
  font-size: 11px;
  color: #2ab585;
  white-space: nowrap;
}
.tile-bottom {
  border-top: 1px solid #e4eaf3;
  padding-top: 14px;
  margin-top: 24px;
  font-size: 11px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
  color: #3975dc;
}
.tile-open h2 {
  font-size: 18px;
  margin: 14px 0 10px;
  overflow-wrap: anywhere;
}
.tile-open p {
  font-size: 14px;
  color: #64748b;
  overflow-wrap: anywhere;
}
.tile-open small {
  color: #64748b;
}
.tile-icon {
  color: #009e85;
  background: #e6f6f2;
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 24px;
}
.tile-actions {
  position: absolute;
  top: 12px;
  right: 16px;
  display: flex;
}
.tile-actions button {
  font-size: 24px;
  padding: 0 8px;
}
.catalog-filters {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}
.catalog-filters .el-input {
  max-width: 420px;
}
.catalog-filters select {
  width: 220px;
}
.catalog-table {
  overflow: auto;
}
table {
  width: 100%;
  min-width: 680px;
}
td small {
  display: block;
  color: #6b7280;
  margin-top: 6px;
  max-width: 320px;
}
td:last-child {
  white-space: nowrap;
}
td:last-child button + button {
  margin-left: 14px;
}
.catalog-pagination {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 16px;
  margin-top: 20px;
}
@media (max-width: 760px) {
  .catalog-filters {
    flex-wrap: wrap;
  }
}
</style>
