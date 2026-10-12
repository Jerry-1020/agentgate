<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { request, type EvaluationRun } from '../../../api/evaluations';
import type { Trace } from '../../../api/client';
import { copy, useReviewStore, type AnnotationTask } from '../../../stores/modules/review';
import type { RawCase } from '../utils/annotation-feedback';
import { annotatedV2Case, hasV2Expected } from '../utils/annotation-v2-feedback';
import { annotationV2Status } from '../utils/annotation-v2-editor';
const props = defineProps<{
  task: AnnotationTask;
  run: EvaluationRun;
  caseId: string;
  trace: Trace;
  dirty: boolean;
}>();
const emit = defineEmits<{ busyChange: [value: boolean] }>();
const review = useReviewStore();
const busy = ref(false),
  error = ref(''),
  destination = ref('');
watch(busy, (value) => emit('busyChange', value), { flush: 'sync' });
const task = computed(
  () => review.annotationTasks.find((t) => t.id === props.task.id) ?? props.task,
);
const prefix = computed(() => props.run.id + '/' + props.caseId);
const source = computed(() => props.run.manifest.dataset.cases.find((c) => c.id === props.caseId));
type Draft = { version: number | null; status: string; content_sha256: string; cases: RawCase[] };
type Detail = { dataset: { archived: boolean }; versions: Draft[] };
const plan = ref<{
  mode: 'new' | 'writeback';
  name: string;
  datasetId: string;
  hash: string | null;
  basedOn: number;
  item: RawCase;
  snapshot: string;
} | null>(null);
const receiptKey = computed(() => 'v2/' + prefix.value);
const snapshot = () =>
  JSON.stringify([task.value.template, task.value.v2Annotations, task.value.skippedConversations]);
function validateSaved() {
  if (props.dirty) throw Error('请先保存当前会话标注。');
  if (task.value.skippedConversations?.includes(prefix.value))
    throw Error('免标注会话不能导出或回写。');
  if (
    annotationV2Status(
      task.value,
      prefix.value,
      source.value?.turns.map((t) => t.id) ?? [],
      props.run.manifest.evaluator_specs?.map((e) => e.id),
    ) !== '已标注'
  )
    throw Error('请先完整填写并保存该会话已启用的标注对象。');
}
async function preview(mode: 'new' | 'writeback') {
  if (busy.value) return;
  error.value = '';
  destination.value = '';
  busy.value = true;
  try {
    validateSaved();
    if (
      mode === 'writeback' &&
      !hasV2Expected(task.value, prefix.value, source.value?.turns.map((t) => t.id) ?? [])
    )
      throw Error('请在测评集人工标注中填写并保存人工期望回答，再回写。');
    const frozen = copy(task.value);
    const stamp = snapshot();
    const historical = await request<{
      case: RawCase;
      dataset_id: string;
      dataset_version: number;
    }>(`/runs/${encodeURIComponent(props.run.id)}/cases/${encodeURIComponent(props.caseId)}`);
    let original = historical.case;
    let hash: string | null = null;
    let basedOn = historical.dataset_version;
    if (mode === 'writeback') {
      const detail = await request<Detail>(
        `/datasets/${encodeURIComponent(historical.dataset_id)}`,
      );
      if (detail.dataset.archived) throw Error('原测评集已归档，不能回写。');
      const draft = detail.versions.find((v) => v.status === 'draft');
      const latest = detail.versions
        .filter((v) => v.version !== null)
        .sort((a, b) => b.version! - a.version!)[0];
      const current = (draft ?? latest)?.cases.find((c) => c.id === props.caseId);
      if (!current) throw Error('原测评集已删除该样本，请导出为新测评集草稿。');
      if (
        JSON.stringify(current.turns.map((t) => [t.id, t.input])) !==
        JSON.stringify(original.turns.map((t) => [t.id, t.input]))
      )
        throw Error('原样本输入或轮次已变化，请导出新测评集后人工合并。');
      original = current;
      hash = draft?.content_sha256 ?? null;
      basedOn = latest?.version ?? basedOn;
    }
    const item = annotatedV2Case(original, props.trace, frozen, prefix.value);
    if (mode === 'new') {
      item.id = props.run.id + '-' + props.caseId;
      item.name += ' · 人工标注';
    }
    plan.value = {
      mode,
      name: task.value.name + ' · 人工回归',
      datasetId:
        mode === 'new' ? (task.value.exports?.[receiptKey.value] ?? '') : historical.dataset_id,
      hash,
      basedOn,
      item,
      snapshot: stamp,
    };
  } catch (cause) {
    error.value = String(cause);
  } finally {
    busy.value = false;
  }
}
async function apply() {
  const current = plan.value;
  if (!current || busy.value) return;
  error.value = '';
  busy.value = true;
  try {
    validateSaved();
    if (snapshot() !== current.snapshot) throw Error('标注在预览后发生变化，请取消后重新预览。');
    if (current.mode === 'new' && !current.datasetId) {
      if (!current.name.trim()) throw Error('请输入测评集名称。');
      const created = await request<{ dataset: { id: string } }>('/datasets', 'POST', {
        name: current.name.trim(),
        description: 'V2人工标注导出，请审核草稿后发布。',
      });
      current.datasetId = created.dataset.id;
    }
    if (current.mode === 'new') {
      const updated = copy(task.value);
      updated.exports = { ...updated.exports, [receiptKey.value]: current.datasetId };
      review.saveAnnotationTask(updated);
    }
    const detail = await request<Detail>(`/datasets/${encodeURIComponent(current.datasetId)}`);
    if (detail.dataset.archived) throw Error('目标测评集已归档。');
    let draft = detail.versions.find((v) => v.status === 'draft');
    if (current.mode === 'writeback' && (draft?.content_sha256 ?? null) !== current.hash)
      throw Error('草稿在预览后发生变化，请取消并重新预览。');
    if (!draft) {
      if (current.mode === 'new') throw Error('导出草稿已发布或删除，请进入测评集查看。');
      const latest = detail.versions
        .filter((v) => v.version !== null)
        .sort((a, b) => b.version! - a.version!)[0];
      if (latest?.version !== current.basedOn) throw Error('原测评集已有新版本，请重新预览。');
      draft = await request<Draft>(
        `/datasets/${encodeURIComponent(current.datasetId)}/drafts`,
        'POST',
        { based_on_version: current.basedOn },
      );
      current.hash = draft.content_sha256;
    }
    await request(
      `/datasets/${encodeURIComponent(current.datasetId)}/drafts/cases`,
      'POST',
      current.item,
    );
    destination.value = current.datasetId;
    plan.value = null;
  } catch (cause) {
    error.value = String(cause);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <section class="v2-feedback">
    <div class="feedback-actions">
      <button class="asset-secondary" :disabled="busy || dirty" @click="preview('new')">
        导出为新测评集草稿
      </button>
      <button class="asset-secondary" :disabled="busy || dirty" @click="preview('writeback')">
        回写原测评集期望
      </button>
    </div>
    <p v-if="dirty">请先保存当前标注后再导出或回写。</p>
    <p v-if="error" class="asset-error" role="alert">{{ error }}</p>
    <p v-if="destination" role="status">
      已写入测评集草稿。<a :href="'#/datasets/' + encodeURIComponent(destination)">查看测评集</a>
    </p>
    <el-dialog
      :model-value="!!plan"
      title="确认人工标注回写内容"
      width="760px"
      :close-on-click-modal="!busy"
      :close-on-press-escape="!busy"
      :show-close="!busy"
      @update:model-value="!busy && (plan = null)"
    >
      <template v-if="plan">
        <p>
          {{
            plan.mode === 'new'
              ? '将当前会话导出为独立测评集草稿。'
              : '仅更新原测评集草稿中的当前样本，已发布版本不变。'
          }}
        </p>
        <p>人工期望回答生成相等检查；评分、标签、评语及优化提示词作为样本备注保留。</p>
        <label v-if="plan.mode === 'new'"
          >测评集名称<input
            v-model="plan.name"
            aria-label="导出测评集名称"
            :disabled="busy || !!plan.datasetId"
        /></label>
        <pre>{{ JSON.stringify(plan.item, null, 2) }}</pre>
        <p v-if="error" class="asset-error" role="alert">{{ error }}</p>
      </template>
      <template #footer
        ><button class="asset-secondary" :disabled="busy" @click="plan = null">取消</button
        ><button class="asset-primary" :disabled="busy" @click="apply">
          {{ busy ? '写入中…' : '确认写入草稿' }}
        </button></template
      >
    </el-dialog>
  </section>
</template>
<style scoped>
.v2-feedback {
  margin: 20px 0;
}
.feedback-actions {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
p {
  font-size: 13px;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 50vh;
  overflow: auto;
  background: #f4f8f6;
  padding: 16px;
}
</style>
