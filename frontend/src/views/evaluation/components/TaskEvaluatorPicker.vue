<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { EvaluatorSummary } from '../../../api/evaluations';
import {
  recommendEvaluators,
  recommendationReason,
  evaluatorRecommendationReasons,
  evaluatorTechnicalChecks,
} from '../utils/evaluator-guidance';
const props = defineProps<{
  evaluators: EvaluatorSummary[];
  cases: any[];
  modelValue: string[];
  staticReport?: {
    id: string;
    status: string;
    findings: {
      id: string;
      reason: string;
      skill_ids: string[];
      suggestions: string[];
      evidence: unknown[];
    }[];
    errors: unknown[];
  } | null;
  staticEnabled: boolean;
  staticAvailable: boolean;
}>();
const emit = defineEmits<{
  'update:modelValue': [ids: string[]];
  static: [];
  cancelAnalysis: [];
}>();
const active = ref(''),
  showReason = ref(false);
const kinds = ['rule', 'llm_judge'] as const;
const expanded = ref<Record<string, boolean>>({ rule: false, llm_judge: false });
const groups = computed(() =>
  Object.fromEntries(kinds.map((kind) => [kind, props.evaluators.filter((e) => e.kind === kind)])),
);
function selectedCount(kind: string) {
  return groups.value[kind].filter((e) => props.modelValue.includes(e.id)).length;
}
const recommended = computed(() => recommendEvaluators(props.evaluators, props.cases));
const current = computed(() => props.evaluators.find((e) => e.id === active.value));
const selected = computed(() => props.evaluators.filter((e) => props.modelValue.includes(e.id)));
watch(
  selected,
  (items) => {
    if (!items.some((e) => e.id === active.value)) active.value = items[0]?.id ?? '';
  },
  { immediate: true },
);
function select(ids: string[]) {
  emit('update:modelValue', ids);
}
function toggle(id: string, on: boolean) {
  select(on ? [...new Set([...props.modelValue, id])] : props.modelValue.filter((x) => x !== id));
}
</script>
<template>
  <section class="task-picker" aria-label="评估器双栏配置">
    <header>
      <h3>评估器</h3>
      <div class="actions">
        <button
          type="button"
          class="secondary"
          :disabled="!staticAvailable"
          @click="emit('static')"
        >
          Skill 静态分析{{ staticEnabled ? ' · 已选' : '' }}</button
        ><button
          type="button"
          class="secondary"
          :disabled="!recommended.length"
          @click="
            select(recommended);
            showReason = true;
            active = recommended[0] ?? '';
          "
        >
          推荐评估器</button
        ><button type="button" class="secondary" @click="emit('cancelAnalysis')">取消分析</button>
      </div>
    </header>
    <div class="picker-body" :class="{ 'with-reason': showReason }">
      <section v-for="kind in kinds" :key="kind">
        <button
          type="button"
          class="category-toggle"
          :aria-label="kind === 'rule' ? '规则评估' : 'LLM 评估'"
          :aria-expanded="expanded[kind]"
          :aria-controls="'evaluator-group-' + kind"
          @click="expanded[kind] = !expanded[kind]"
        >
          <span
            ><strong>{{ kind === 'rule' ? '规则评估' : 'LLM 评估' }}</strong
            ><small>{{ groups[kind].length }} 项 · 已选 {{ selectedCount(kind) }} 项</small></span
          >
          <span class="category-action"
            >{{ expanded[kind] ? '收起' : '展开' }}
            <span aria-hidden="true">{{ expanded[kind] ? '⌃' : '⌄' }}</span></span
          >
        </button>
        <div v-show="expanded[kind]" :id="'evaluator-group-' + kind" class="evaluator-grid">
          <article
            v-for="e in groups[kind]"
            :key="e.id"
            class="evaluator-tile"
            :class="{ selected: modelValue.includes(e.id) }"
          >
            <div class="tile-heading">
              <input
                type="checkbox"
                :aria-label="'选择评估器 ' + e.name"
                :checked="modelValue.includes(e.id)"
                @change="toggle(e.id, ($event.target as HTMLInputElement).checked)"
              />
              <button
                type="button"
                class="link evaluator-name"
                :title="e.name"
                @click="
                  toggle(e.id, true);
                  active = e.id;
                  showReason = true;
                "
              >
                {{ e.name }}
              </button>
            </div>
            <small class="tile-version"
              >v{{ e.latest_version }}{{ recommended.includes(e.id) ? ' · 推荐' : '' }}</small
            >
          </article>
          <p v-if="!groups[kind].length" class="empty-group">暂无已发布且启用的评估器</p>
        </div>
      </section>
      <aside v-if="showReason">
        <button type="button" class="link" @click="showReason = false">收起推荐详情 »</button>
        <label class="reason-selector"
          >已选评估器<select v-model="active" aria-label="推荐详情评估器">
            <option v-if="!selected.length" value="">请先勾选评估器</option>
            <option v-for="e in selected" :key="e.id" :value="e.id">
              {{ e.name }} · v{{ e.latest_version }}
            </option>
          </select></label
        >
        <template v-if="current">
          <h4>{{ current.name }}</h4>
          <section class="reason-card">
            <h5>Skill 静态分析结论</h5>
            <template v-if="staticReport"
              ><span class="report-status">{{
                staticReport.status === 'completed'
                  ? '分析完成'
                  : staticReport.status === 'partial'
                    ? '部分完成'
                    : '分析失败'
              }}</span>
              <p class="scope-label">所选智能体的 Skill 结构风险</p>
              <article v-for="finding in staticReport.findings" :key="finding.id" class="finding">
                <p>{{ finding.reason }}</p>
                <div class="skill-tags">
                  <span v-for="id in finding.skill_ids" :key="id">{{ id }}</span>
                </div>
                <ul v-if="finding.suggestions.length">
                  <li v-for="tip in finding.suggestions" :key="tip">{{ tip }}</li>
                </ul>
                <details v-if="finding.evidence.length">
                  <summary>分析证据</summary>
                  <pre>{{ JSON.stringify(finding.evidence, null, 2) }}</pre>
                </details>
              </article>
              <p v-if="!staticReport.findings.length">
                {{
                  staticReport.status === 'completed' ? '未发现 Skill 结构风险' : '未返回有效结论'
                }}
              </p>
            </template>
            <p v-else>{{ staticEnabled ? '等待分析结果' : '尚未执行静态分析' }}</p>
          </section>
          <section class="reason-card">
            <h5>评估器检查依据</h5>
            <p class="coverage">{{ recommendationReason(current, cases) }}</p>
            <p>
              {{ evaluatorRecommendationReasons[current.implementation_id] ?? current.description }}
            </p>
            <ul>
              <li v-for="check in evaluatorTechnicalChecks(current, cases)" :key="check">
                {{ check }}
              </li>
            </ul>
          </section>
        </template>
      </aside>
      <button
        v-else
        type="button"
        class="reason-open link"
        @click="
          showReason = true;
          active = modelValue[0] ?? '';
        "
      >
        »<br />推荐详情
      </button>
    </div>
  </section>
</template>
<style scoped>
.task-picker {
  border: 1px solid #dce4ef;
  border-radius: 10px;
  background: #fff;
  min-width: 0;
}
.task-picker header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 16px;
  flex-wrap: wrap;
}
.task-picker header h3 {
  margin: 0;
}
.task-picker .actions {
  flex-wrap: wrap;
}
.picker-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 80px;
  border-top: 1px solid #e1e7f0;
  align-items: start;
}
.picker-body.with-reason {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(180px, 0.8fr);
}
.picker-body > section {
  padding: 12px;
  border-right: 1px solid #e1e7f0;
  min-width: 0;
}
.category-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  border: 1px solid #dce4ef;
  border-radius: 8px;
  background: #f8fafc;
  color: #374151;
  padding: 12px;
  text-align: left;
  cursor: pointer;
}
.category-toggle[aria-expanded='true'] {
  border-color: #9ed8cb;
  background: #f0faf7;
}
.category-toggle strong {
  font-size: 14px;
}
.category-toggle small {
  display: block;
  margin-top: 5px;
  color: #8491a4;
  font-size: 11px;
}
.category-action {
  font-size: 12px;
  color: #008b76;
  white-space: nowrap;
}
.evaluator-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 145px), 1fr));
  gap: 8px;
  margin-top: 10px;
  max-height: 380px;
  overflow-y: auto;
  align-content: start;
  padding: 1px;
}
.evaluator-tile {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 76px;
  max-width: 220px;
  box-sizing: border-box;
  padding: 10px;
  border: 1px solid #e0e6ef;
  border-radius: 8px;
  background: #fff;
  min-width: 0;
}
.evaluator-tile.selected {
  border-color: #61bda8;
  background: #f1fbf8;
}
.tile-heading {
  display: flex;
  align-items: flex-start;
  gap: 7px;
}
.tile-heading input {
  flex-shrink: 0;
  margin: 2px 0;
}
.tile-heading .evaluator-name {
  padding: 0;
  min-width: 0;
  font-size: 12px;
  text-align: left;
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.tile-version {
  font-size: 10px;
  color: #8491a4;
  margin-left: 20px;
}
.tile-weight {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  font-size: 11px;
  margin-top: auto;
}
.tile-weight input {
  width: 56px;
  box-sizing: border-box;
  border: 1px solid #dce3ed;
  border-radius: 5px;
  padding: 5px;
  font-size: 12px;
}
.tile-weight input:disabled {
  color: #9aa3b1;
  background: #f7f8fa;
}
.empty-group {
  grid-column: 1/-1;
  font-size: 12px;
  color: #8491a4;
}
.picker-body aside {
  padding: 16px;
  background: #f6f9fd;
  min-width: 0;
  font-size: 12px;
  line-height: 1.8;
}
.reason-open {
  align-self: start;
  margin-top: 25px;
}
.reason-selector {
  display: block;
  margin-top: 12px;
}
.reason-selector select {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 8px;
  border: 1px solid #dce4ef;
  border-radius: 6px;
  background: white;
  color: #374151;
}
.task-picker footer {
  padding: 12px 16px;
  border-top: 1px solid #e1e7f0;
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
}
.category-toggle:focus-visible,
.evaluator-name:focus-visible {
  outline: 2px solid #008b76;
  outline-offset: 2px;
}
@media (max-width: 800px) {
  .picker-body,
  .picker-body.with-reason {
    grid-template-columns: 1fr;
  }
  .picker-body > section {
    border-right: 0;
    border-bottom: 1px solid #e1e7f0;
  }
  .reason-open {
    padding: 12px;
    margin: 0;
  }
}
.reason-card {
  background: #fff;
  border: 1px solid #dce8e3;
  border-radius: 8px;
  padding: 12px;
  margin: 12px 0;
}
.reason-card h5 {
  margin: 0 0 10px;
  color: #087f6c;
  font-size: 13px;
}
.reason-card p {
  margin: 8px 0;
  line-height: 1.7;
}
.reason-card ul {
  padding-left: 18px;
  margin: 8px 0;
}
.reason-card li {
  margin: 6px 0;
}
.reason-card pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 11px;
}
.coverage {
  font-weight: 600;
  color: #344b43;
}
.report-status,
.skill-tags span {
  display: inline-block;
  background: #edf7f3;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
}
.skill-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.finding {
  border-top: 1px solid #e8eeeb;
  margin-top: 10px;
}
.scope-label {
  color: #73867f;
}
.picker-body aside {
  background: #f7faf9;
  max-height: 520px;
  overflow: auto;
}
</style>
