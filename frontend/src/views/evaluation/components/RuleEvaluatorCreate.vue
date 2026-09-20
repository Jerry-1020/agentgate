<script setup lang="ts">
import { computed, ref } from 'vue';
import { request } from '../../../api/evaluations';
import { evaluatorCatalog, evaluatorDetails } from '../../../stores/review-assets';
const emit = defineEmits<{ close: []; created: [] }>();
const name = ref(''),
  description = ref(''),
  source = ref(''),
  busy = ref(false),
  error = ref(''),
  createdId = ref('');
const enable = ref(true);
const rules = computed(() =>
  evaluatorCatalog.value.filter((e) => e.kind === 'rule' && e.latest_version),
);
const selected = computed(() => evaluatorDetails.value[source.value]?.latest);
async function save() {
  if (busy.value || !name.value.trim() || !selected.value) return;
  busy.value = true;
  error.value = '';
  try {
    if (!createdId.value) {
      const s = selected.value;
      const response = await request<any>('/evaluators', 'POST', {
        name: name.value.trim(),
        description: description.value.trim(),
        draft: {
          kind: 'rule',
          dimension: s.dimension,
          metric: s.metric,
          severity: s.severity,
          implementation_id: s.implementation_id,
          implementation_version: s.implementation_version,
          config: s.config,
          children: [],
          combination: null,
        },
      });
      createdId.value = response.evaluator.id;
    }
    const path = '/evaluators/' + encodeURIComponent(createdId.value);
    const current = await request<any>(path);
    if (!current.latest) await request(path + '/drafts/publish', 'POST');
    if (enable.value) await request(path, 'PATCH', { enabled: true });
    emit('created');
  } catch (e) {
    error.value =
      String(e) +
      (createdId.value ? '；已保留记录 ' + createdId.value + '，重试只发布该记录。' : '');
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <el-dialog
    :model-value="true"
    title="新建规则评估器"
    width="min(640px,94vw)"
    :close-on-click-modal="false"
    :show-close="!busy"
    :close-on-press-escape="!busy"
    @close="emit('close')"
  >
    <fieldset :disabled="busy || !!createdId" class="rule-fields">
      <label class="field"
        >名称<input
          class="input"
          v-model="name"
          aria-label="规则评估器名称"
          maxlength="128" /></label
      ><label class="field"
        >规则实现<select class="input" v-model="source" aria-label="规则实现">
          <option value="">请选择已注册规则</option>
          <option v-for="r in rules" :key="r.id" :value="r.id">
            {{ r.name }} · {{ r.metric }}
          </option>
        </select></label
      ><label class="field"
        >描述<textarea class="input" v-model="description" rows="3" aria-label="规则评估器描述" />
      </label>
    </fieldset>
    <section v-if="selected" class="rule-preview">
      <b>{{ selected.dimension }} · {{ selected.metric }}</b>
      <p>{{ selected.implementation_id }} @ {{ selected.implementation_version }}</p>
      <span>{{ selected.severity === 'blocking' ? '阻断级检查' : '标准检查' }}</span>
    </section>
    <p>
      <label
        ><input type="checkbox" v-model="enable" :disabled="busy || !!createdId" />
        发布后启用</label
      >
    </p>
    <p>发布为只读规则，不上传或执行新代码。</p>
    <p v-if="error" role="alert" class="notice error">{{ error }}</p>
    <template #footer
      ><button class="secondary" :disabled="busy" @click="emit('close')">关闭</button
      ><button class="primary" :disabled="busy || !name.trim() || !selected" @click="save">
        {{ busy ? '正在创建…' : createdId ? '重试发布' : '创建并发布' }}
      </button></template
    ></el-dialog
  >
</template>
<style scoped>
.rule-fields {
  border: 0;
  padding: 0;
  display: grid;
  gap: 16px;
}
.rule-preview {
  margin-top: 20px;
  background: #f0f8f5;
  padding: 16px;
  border-radius: 10px;
}
p {
  font-size: 13px;
  color: #667a73;
}
</style>
