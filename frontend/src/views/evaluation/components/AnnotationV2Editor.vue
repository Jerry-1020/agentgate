<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import type { EvaluationRun } from '../../../api/evaluations';
import type { Trace, EvaluationResult } from '../../../api/client';
import { copy, useReviewStore, type AnnotationTask } from '../../../stores/modules/review';
import {
  annotationObjects,
  originalExpectedAnswer,
  normalizeObjectAnnotation,
  type TurnObjectDraft,
} from '../utils/annotation-v2-editor';
import EvaluatorAnnotation from './EvaluatorAnnotation.vue';
import AnnotationV2Feedback from './AnnotationV2Feedback.vue';
import { request } from '../../../api/evaluations';
import type { EvaluatorEvidence } from '../utils/annotation-v2-editor';
import { displayValue } from '../utils/task-report';
const props = defineProps<{
  task: AnnotationTask;
  run: EvaluationRun;
  caseId: string;
  trace: Trace;
  results?: EvaluationResult[];
}>();
const emit = defineEmits<{ back: [] }>();
const review = useReviewStore();
const task = computed(
  () => review.annotationTasks.find((t) => t.id === props.task.id) ?? props.task,
);
const source = computed(() => props.run.manifest.dataset.cases.find((c) => c.id === props.caseId));
const groups = computed(() =>
  annotationObjects.filter((g) => task.value.template.v2?.[g.key].enabled),
);
const turnIds = [
  ...new Set([
    ...(source.value?.turns.map((t) => t.id) ?? []),
    ...Object.keys(props.trace.turn_outcomes),
  ]),
];
const prefix = props.run.id + '/' + props.caseId;
const drafts = ref<TurnObjectDraft[]>(
  turnIds.map((id) => ({
    id,
    objects: Object.fromEntries(
      annotationObjects.map((g) => [
        g.key,
        copy(
          task.value.v2Annotations?.[prefix + '/' + id]?.[g.key] ?? {
            scores: {},
            tags: [],
            note: '',
            ...(g.key === 'dataset' ? { expected: '' } : {}),
          },
        ),
      ]),
    ) as TurnObjectDraft['objects'],
  })),
);
const evaluatorEvidence = ref<EvaluatorEvidence[]>([]);
const evidenceLoading = ref(false),
  evidenceError = ref('');
async function loadEvidence() {
  evidenceLoading.value = true;
  evidenceError.value = '';
  try {
    evaluatorEvidence.value = await request<EvaluatorEvidence[]>(
      `/runs/${encodeURIComponent(props.run.id)}/cases/${encodeURIComponent(props.caseId)}/annotation-evidence`,
    );
  } catch (cause) {
    evidenceError.value = String(cause);
  } finally {
    evidenceLoading.value = false;
  }
}
onMounted(() => {
  if (groups.value.some((g) => g.key === 'evaluator')) void loadEvidence();
});
const baseline = ref(JSON.stringify(drafts.value));
const dirty = computed(() => baseline.value !== JSON.stringify(drafts.value));
const feedbackBusy = ref(false);
const error = ref(''),
  saved = ref('');
function back() {
  if (feedbackBusy.value) return;
  if (dirty.value && !window.confirm('当前标注尚未保存，确定返回会话列表？')) return;
  emit('back');
}
onBeforeRouteLeave(
  () => !feedbackBusy.value && (!dirty.value || window.confirm('当前标注尚未保存，确定离开？')),
);
function beforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value && !feedbackBusy.value) return;
  event.preventDefault();
  event.returnValue = '';
}
onMounted(() => window.addEventListener('beforeunload', beforeUnload));
onUnmounted(() => window.removeEventListener('beforeunload', beforeUnload));
function save() {
  error.value = '';
  saved.value = '';
  const updated = copy(task.value);
  updated.v2Annotations ??= {};
  try {
    for (const turn of drafts.value) {
      const key = prefix + '/' + turn.id;
      const record = { ...updated.v2Annotations[key] };
      for (const group of groups.value) {
        record[group.key] = normalizeObjectAnnotation(
          turn.objects[group.key],
          task.value.template.v2![group.key].criteria.map((d) => d.key),
          task.value.template.min,
          task.value.template.max,
        );
      }
      updated.v2Annotations[key] = record;
    }
    updated.skippedConversations = updated.skippedConversations?.filter((key) => key !== prefix);
    review.saveAnnotationTask(updated);
    baseline.value = JSON.stringify(drafts.value);
    saved.value = '标注已保存';
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  }
}
</script>
<template>
  <section class="v2-editor asset-dialog">
    <div class="editor-heading">
      <div>
        <h1>{{ source?.name ?? '会话标注' }}</h1>
        <p>{{ task.name }} · {{ run.manifest.target.display_name }}</p>
      </div>
      <button class="asset-secondary" @click="back">返回会话列表</button>
    </div>
    <p v-if="!groups.length && !task.template.v2?.agent?.enabled" class="asset-empty">
      此模版未启用标注对象，请先在模版中勾选标注对象。
    </p>
    <p v-if="!drafts.length" class="asset-empty">暂无可标注的会话轮次。</p>
    <section v-for="(turn, index) in drafts" :key="turn.id" class="turn-section">
      <h2>第 {{ index + 1 }} 轮</h2>
      <section
        v-for="group in groups"
        :key="group.key"
        :aria-label="group.title + ' 第' + (index + 1) + '轮'"
        class="object-section"
      >
        <h3>{{ group.title }}</h3>
        <template v-if="group.key === 'evaluator'">
          <p v-if="evidenceLoading">正在读取本次会话的评估器与证据…</p>
          <p v-else-if="evidenceError" role="alert">
            {{ evidenceError }} <button class="asset-secondary" @click="loadEvidence">重试</button>
          </p>
          <EvaluatorAnnotation
            v-else
            :entries="evaluatorEvidence"
            :model-value="turn.objects.evaluator.evaluators ?? {}"
            :criteria="task.template.v2!.evaluator.criteria"
            :tags="task.template.v2!.evaluator.tags"
            :min="task.template.min"
            :max="task.template.max"
            :turn-id="turn.id"
            @update:model-value="turn.objects.evaluator.evaluators = $event"
          />
        </template>
        <div v-else class="annotation-editor">
          <div class="annotation-dialogue">
            <h3>原始会话信息</h3>
            <h4>用户输入</h4>
            <pre>{{
              displayValue(
                trace.turn_outcomes[turn.id]?.input ??
                  source?.turns.find((t) => t.id === turn.id)?.input,
              )
            }}</pre>
            <h4>实际回答</h4>
            <pre>{{
              trace.turn_outcomes[turn.id]
                ? displayValue(trace.turn_outcomes[turn.id].output)
                : '未取得实际回答'
            }}</pre>
            <template v-if="group.key === 'dataset'"
              ><h4>期望回答</h4>
              <pre>{{ originalExpectedAnswer(source?.turns.find((t) => t.id === turn.id)) }}</pre>
            </template>
          </div>
          <div class="annotation-scoring">
            <h3>标注意见</h3>
            <div class="score-fields">
              <label
                v-for="d in task.template.v2![group.key].criteria"
                :key="d.key"
                class="score-field"
              >
                <span>{{ d.text }}（{{ task.template.min }}—{{ task.template.max }}）</span>
                <input
                  v-model.number="turn.objects[group.key].scores[d.key]"
                  type="number"
                  :min="task.template.min"
                  :max="task.template.max"
                  step="any"
                  :aria-label="group.title + ' 第' + (index + 1) + '轮 ' + d.text"
                />
              </label>
            </div>
            <div class="asset-chips">
              <label v-for="tag in task.template.v2![group.key].tags" :key="tag"
                ><input v-model="turn.objects[group.key].tags" type="checkbox" :value="tag" />
                {{ tag }}</label
              >
            </div>
            <label
              >评语<input
                v-model="turn.objects[group.key].note"
                type="text"
                :aria-label="group.title + ' 第' + (index + 1) + '轮 评语'"
            /></label>
            <label v-if="group.key === 'dataset'"
              >人工期望回答<textarea
                v-model="turn.objects.dataset.expected"
                rows="3"
                :aria-label="'第' + (index + 1) + '轮 人工期望回答'"
                placeholder="填写修订后的期望回答"
              />
            </label>
          </div>
        </div>
        <AnnotationV2Feedback
          v-if="group.key === 'dataset'"
          :task="task"
          :run="run"
          :case-id="caseId"
          :trace="trace"
          :dirty="dirty"
          @busy-change="feedbackBusy = $event"
        />
      </section>
      <section
        v-if="task.template.v2?.agent?.enabled"
        class="object-section"
        :aria-label="'智能体人工标注 第' + (index + 1) + '轮'"
      >
        <h3>智能体人工标注（待设计）</h3>
      </section>
    </section>
    <footer class="annotation-save">
      <p v-if="error" class="asset-error" role="alert">{{ error }}</p>
      <p v-else-if="saved && !dirty" role="status">{{ saved }}</p>
      <button
        class="asset-primary"
        :disabled="feedbackBusy || !groups.length || !drafts.length"
        @click="save"
      >
        保存标注
      </button>
    </footer>
  </section>
</template>
<style scoped>
.editor-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 24px 0;
}
h1 {
  margin: 0;
  font-size: 24px;
}
.editor-heading p {
  color: #819188;
}
.turn-section {
  margin-top: 24px;
}
.object-section > h3 {
  font-size: 16px;
  color: #40516a;
}
.annotation-editor {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  background: white;
  border: 1px solid #dce7e1;
  border-radius: 12px;
  margin-bottom: 20px;
  overflow: hidden;
}
.annotation-dialogue,
.annotation-scoring {
  padding: 24px;
  min-width: 0;
}
.annotation-scoring {
  border-left: 1px solid #e4ece7;
  background: #fbfdfc;
}
.annotation-dialogue pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 50vh;
  overflow: auto;
  background: #f4f8f6;
  padding: 18px;
  border-radius: 8px;
  line-height: 1.8;
  font-size: 13px;
}
.score-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
}
.score-field {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.annotation-scoring .score-field input {
  width: calc(3ch + 20px);
  min-width: 0;
  padding: 6px 8px;
  appearance: textfield;
  margin: 0;
}
.score-field input::-webkit-inner-spin-button,
.score-field input::-webkit-outer-spin-button {
  appearance: none;
  margin: 0;
}
.annotation-save {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 16px;
  position: sticky;
  bottom: 0;
  background: white;
  padding: 16px;
  border-top: 1px solid #e4ece7;
}
</style>
