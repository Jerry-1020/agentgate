<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { request } from '../../../api/evaluations';
import { readModelRef, modelRefError, type EvaluatorModelRef } from '../utils/evaluator-model';
const props = defineProps<{
  modelValue: string;
  editable: boolean;
  models: [string, EvaluatorModelRef][];
}>();
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const custom = ref(false),
  loading = ref(false),
  error = ref('');
const runtime = ref<{ model: string; base_url: string; configured: boolean } | null>(null);
const model = computed(() => readModelRef(props.modelValue));
const isCustom = computed(
  () =>
    custom.value || (!!props.modelValue && !props.models.some(([key]) => key === props.modelValue)),
);
const selectedError = computed(() => (props.modelValue ? modelRefError(props.modelValue) : ''));
function update(field: keyof EvaluatorModelRef, value: string) {
  const m = { provider_id: '', model_id: '', ...model.value, [field]: value.trim() };
  if (!m.credential_ref) delete m.credential_ref;
  emit('update:modelValue', JSON.stringify(m));
}
async function refresh() {
  loading.value = true;
  error.value = '';
  runtime.value = null;
  try {
    const result = await request<{
      connections: { role: string; model: string; base_url: string; configured: boolean }[];
    }>('/model-runtime');
    runtime.value = result.connections.find((c) => c.role === 'LLM 评估器默认连接') ?? null;
  } catch {
    error.value = '无法读取服务端连接状态；可保留模型引用，不能据此认定模型可用。';
  } finally {
    loading.value = false;
  }
}
onMounted(refresh);
</script>
<template>
  <section class="judge-model" aria-label="评审模型配置">
    <header>
      <div><h3>评审模型</h3></div>
      <span class="model-status">{{
        model && !selectedError ? '已选择 · 未测试连接' : '待选择模型'
      }}</span>
    </header>
    <div v-if="editable" class="model-modes" role="group" aria-label="模型选择方式">
      <button
        type="button"
        :class="{ active: !isCustom }"
        :aria-pressed="!isCustom"
        @click="
          custom = false;
          emit('update:modelValue', '');
        "
      >
        已有模型</button
      ><button
        type="button"
        :class="{ active: isCustom }"
        :aria-pressed="isCustom"
        @click="custom = true"
      >
        自定义模型引用
      </button>
    </div>
    <label v-if="editable && !isCustom" class="model-picker"
      >选择评审模型 <em>*</em
      ><select
        :value="modelValue"
        aria-label="评估器模型"
        @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option value="">请选择模型，不自动沿用被测模型</option>
        <option v-for="[key, m] in models" :key="key" :value="key">
          {{ m.model_id }} · {{ m.provider_id }}{{ m.credential_ref ? ' · 指定凭据引用' : '' }}
        </option></select
      ><small v-if="!models.length"
        >暂无已发布评估器的模型引用，可填写自定义引用进行 UX 设计。</small
      ></label
    >
    <div v-if="editable && isCustom" class="model-fields">
      <label
        >提供商 ID <em>*</em
        ><input
          :value="model?.provider_id ?? ''"
          aria-label="评审模型提供商 ID"
          placeholder="与后端注册的 provider_id 一致"
          @input="update('provider_id', ($event.target as HTMLInputElement).value)" /></label
      ><label
        >模型 ID <em>*</em
        ><input
          :value="model?.model_id ?? ''"
          aria-label="评审模型 ID"
          placeholder="填写模型服务接受的 model_id"
          @input="update('model_id', ($event.target as HTMLInputElement).value)" /></label
      ><label
        >凭据引用（选填）<input
          :value="model?.credential_ref ?? ''"
          aria-label="评审模型凭据引用"
          placeholder="credential_ref，不是 API Key"
          @input="update('credential_ref', ($event.target as HTMLInputElement).value)"
      /></label>
    </div>
    <div v-if="model" class="model-summary">
      <div>
        <small>提供商</small><b>{{ model.provider_id || '未填写' }}</b>
      </div>
      <div>
        <small>模型</small><b>{{ model.model_id || '未填写' }}</b>
      </div>
      <div>
        <small>凭据</small><b>{{ model.credential_ref ? '服务端凭据引用' : '服务端默认凭据' }}</b>
      </div>
    </div>
    <p v-if="!editable && !model" class="model-warning">
      当前评估器未提供有效模型引用，复制并编辑后可选择。
    </p>
    <p v-if="selectedError" role="alert" class="model-warning">{{ selectedError }}</p>
    <details class="connection-detail">
      <summary>服务端默认连接信息</summary>
      <button type="button" :disabled="loading" @click="refresh">
        {{ loading ? '读取中…' : '刷新配置状态' }}
      </button>
      <p v-if="error" role="alert">{{ error }}</p>
      <template v-else-if="runtime"
        ><p>
          默认模型：{{ runtime.model || '未配置' }} ·
          {{ runtime.configured ? '服务端已配置' : '服务端未配置' }}
        </p>
        <p>Base URL：{{ runtime.base_url || '未提供' }}</p>
        <p v-if="model && model.model_id !== runtime.model" class="model-warning">
          所选模型与默认模型不同，需确认后端提供商和模型路由支持。
        </p></template
      >
      <p v-else-if="!loading && !error">未提供默认连接信息。</p>
    </details>
  </section>
</template>
<style scoped>
.judge-model {
  margin: 20px 0 0;
  border: 1px solid #dbe5f5;
  border-radius: 12px;
  background: #f8faff;
  padding: 20px;
}
.judge-model header {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 16px;
}
.judge-model h3 {
  margin: 0;
  font-size: 17px;
  color: #263b59;
}
.judge-model header p {
  font-size: 12px;
  color: #74849c;
  margin: 8px 0 16px;
}
.model-status {
  font-size: 11px;
  border-radius: 20px;
  background: #eaf7f2;
  color: #008b76;
  padding: 6px 10px;
  white-space: nowrap;
}
.model-modes {
  display: flex;
  gap: 6px;
  margin-bottom: 14px;
}
.model-modes button {
  border: 1px solid #dce4f1;
  background: white;
  padding: 8px 14px;
  border-radius: 7px;
  color: #687993;
  cursor: pointer;
}
.model-modes .active {
  background: #eaf7f2;
  border-color: #86c9b6;
  color: #008b76;
}
.model-picker,
.model-fields label {
  display: block;
  color: #41526b;
  font-size: 13px;
}
.model-picker select {
  width: 100%;
  margin-top: 8px;
  background: white;
  border: 1px solid #afd4c7;
  border-radius: 8px;
  padding: 13px;
  color: #334b70;
}
.judge-model em {
  color: #d34e62;
  font-style: normal;
}
.model-fields,
.model-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.model-summary {
  margin-top: 16px;
  padding: 14px;
  background: white;
  border: 1px solid #e6ebf3;
  border-radius: 8px;
}
.model-summary small,
.model-summary b {
  display: block;
  overflow-wrap: anywhere;
}
.model-summary small {
  font-size: 11px;
  color: #8796ad;
  margin-bottom: 5px;
}
.model-summary b {
  font-size: 13px;
  color: #405571;
}
.connection-detail {
  margin-top: 14px;
  color: #7686a0;
  font-size: 12px;
}
.connection-detail summary {
  cursor: pointer;
}
.connection-detail p {
  overflow-wrap: anywhere;
}
.connection-detail button {
  border: 1px solid #dce4f1;
  border-radius: 5px;
  background: white;
  color: #008b76;
  margin-top: 10px;
  padding: 6px 10px;
}
.model-footnote {
  font-size: 11px;
  color: #8996ab;
  line-height: 1.7;
  margin-bottom: 0;
}
.model-warning {
  color: #a56a25 !important;
  font-size: 12px;
}
@media (max-width: 700px) {
  .model-fields,
  .model-summary {
    grid-template-columns: 1fr;
  }
  .judge-model header {
    flex-wrap: wrap;
  }
}
</style>
