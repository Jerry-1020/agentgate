<script setup lang="ts">
import { computed, ref } from 'vue';
import { llmGroupTemplates } from '../utils/evaluator-group';
import { evaluatorTemplates } from '../utils/evaluator-templates';

const props = defineProps<{ template: (typeof llmGroupTemplates)[number] }>();
const emit = defineEmits<{ close: [] }>();
const selected = ref<string>(props.template.children[0].templateId);
const children = computed(() =>
  props.template.children.map((child) => ({
    ...child,
    ...evaluatorTemplates.find((item) => item.id === child.templateId)!,
  })),
);
const active = computed(() => children.value.find((child) => child.templateId === selected.value)!);
</script>

<template>
  <el-dialog
    :model-value="true"
    title="预置评估器模板"
    width="min(1100px,94vw)"
    :close-on-click-modal="false"
    @close="emit('close')"
  >
    <section class="template-preview" aria-label="综合评估器模板详情">
      <header class="preview-heading">
        <h2>{{ template.name }} <span>只读</span></h2>
        <p>{{ template.description }}</p>
      </header>
      <div class="preview-layout">
        <aside aria-label="模板子评估器">
          <h3>子评估器</h3>
          <button
            v-for="child in children"
            :key="child.templateId"
            :class="{ active: child.templateId === selected }"
            :aria-label="'查看子评估器 ' + child.name"
            :aria-pressed="child.templateId === selected"
            @click="selected = child.templateId"
          >
            <span>{{ child.name }}</span
            ><strong>{{ child.weight }}%</strong>
          </button>
          <p>权重合计：100%</p>
          <p>综合通过分数：{{ template.threshold }}</p>
        </aside>
        <section class="preview-child">
          <h3>{{ active.name }}</h3>
          <p>{{ active.description }}</p>
          <p class="preview-model">模型在新建评估器时配置。</p>
          <label for="template-system-prompt">System Prompt</label>
          <textarea
            id="template-system-prompt"
            :value="active.instruction"
            readonly
            aria-label="模板 System Prompt"
            rows="17"
          />
        </section>
      </div>
    </section>
    <template #footer>
      <button class="preview-close" @click="emit('close')">关闭</button>
    </template>
  </el-dialog>
</template>

<style scoped>
.template-preview {
  color: var(--el-text-color-primary);
}
.preview-heading {
  padding: 18px 20px;
  background: var(--el-color-primary-dark-2);
  background: color-mix(in srgb, var(--el-color-primary-dark-2) 70%, #000);
  color: #fff;
  border-radius: 8px;
}
.preview-heading h2 {
  margin: 0;
  color: inherit;
  font-size: 18px;
}
.preview-heading span {
  display: inline-block;
  margin-left: 10px;
  padding: 3px 7px;
  border: 1px solid #ffffff50;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 400;
  vertical-align: middle;
}
.preview-heading p {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.8;
}
.preview-layout {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  gap: 24px;
  margin-top: 24px;
}
.preview-layout h3 {
  margin: 0 0 14px;
  font-size: 15px;
}
.preview-layout aside button {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  margin-bottom: 10px;
  padding: 12px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 7px;
  cursor: pointer;
}
.preview-layout aside button.active {
  color: var(--el-color-primary-dark-2);
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}
.preview-layout p {
  font-size: 12px;
  line-height: 1.8;
  color: var(--el-text-color-secondary);
}
.preview-child {
  min-width: 0;
}
.preview-model {
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--el-fill-color-extra-light);
}
.preview-child label {
  display: block;
  margin: 18px 0 10px;
  font-weight: 600;
  font-size: 13px;
}
.preview-child textarea {
  display: block;
  width: 100%;
  padding: 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 7px;
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  line-height: 1.8;
  font-size: 13px;
  resize: vertical;
}
.preview-close {
  padding: 8px 20px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  cursor: pointer;
}
@media (max-width: 720px) {
  .preview-layout {
    grid-template-columns: 1fr;
    gap: 16px;
  }
}
</style>
