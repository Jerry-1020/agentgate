<script setup lang="ts">
import { llmGroupTemplates } from '../utils/evaluator-group';
import { evaluatorTemplates } from '../utils/evaluator-templates';

defineProps<{
  template: (typeof llmGroupTemplates)[number];
  disabled?: boolean;
  action?: 'apply' | 'view';
}>();
const emit = defineEmits<{ apply: [id: string]; view: [id: string] }>();
</script>

<template>
  <article class="llm-group-template-card">
    <span class="asset-chip">预置模板</span>
    <h2 class="group-template-title">{{ template.name }}</h2>
    <p>{{ template.description }}</p>
    <div class="group-template-tags"><span>LLM</span><span>文本</span><span>内容质量</span></div>
    <h4>包含 {{ template.children.length }} 个子评估器</h4>
    <ul class="group-template-children">
      <li v-for="child in template.children" :key="child.templateId">
        <span>{{ evaluatorTemplates.find((item) => item.id === child.templateId)?.name }}</span>
        <strong>{{ child.weight }}%</strong>
      </li>
    </ul>
    <div class="asset-card-actions">
      <button
        :class="action === 'view' ? 'asset-link' : 'llm-template-create-button'"
        :disabled="disabled"
        :aria-label="action === 'view' ? '查看' + template.name + '模板' : undefined"
        @click="action === 'view' ? emit('view', template.id) : emit('apply', template.id)"
      >
        {{ action === 'view' ? '查看详情' : '使用此模版创建' }}
      </button>
    </div>
  </article>
</template>

<style scoped>
.llm-group-template-card {
  align-self: start;
  font-size: 14px;
  line-height: 1.6;
}
.llm-group-template-card .asset-card-actions {
  min-height: 54px;
}
.group-template-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.group-template-tags span {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  border-radius: 3px;
  padding: 3px 6px;
  font-size: 10px;
}
.llm-group-template-card h4 {
  margin: 0;
  color: var(--el-text-color-regular);
  font-size: 12px;
  font-weight: 500;
}
.group-template-children {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.group-template-children li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  border-radius: 5px;
  padding: 8px;
  background: var(--el-fill-color-extra-light);
  color: var(--el-text-color-regular);
  font-size: 12px;
}
.group-template-children strong {
  color: var(--el-color-primary-dark-2);
  font-weight: 500;
}
.asset-link:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 3px;
}
.asset-link:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
