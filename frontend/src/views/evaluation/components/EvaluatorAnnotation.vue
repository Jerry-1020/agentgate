<script setup lang="ts">
import type { EvaluatorReview } from '../../../stores/modules/review';
import type { EvaluatorEvidence } from '../utils/annotation-v2-editor';
import { displayValue } from '../utils/task-report';
const props = defineProps<{
  entries: EvaluatorEvidence[];
  modelValue: Record<string, EvaluatorReview>;
  criteria: { key: string; text: string }[];
  tags: string[];
  min: number;
  max: number;
  turnId: string;
}>();
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, EvaluatorReview>] }>();
function value(id: string): EvaluatorReview {
  return props.modelValue[id] ?? { scores: {}, tags: [], note: '', optimizedPrompt: '' };
}
function update(id: string, patch: Partial<EvaluatorReview>) {
  emit('update:modelValue', { ...props.modelValue, [id]: { ...value(id), ...patch } });
}
function score(id: string, key: string, event: Event) {
  const text = (event.target as HTMLInputElement).value;
  update(id, { scores: { ...value(id).scores, [key]: text === '' ? null : Number(text) } });
}
function tag(id: string, name: string, event: Event) {
  update(id, {
    tags: (event.target as HTMLInputElement).checked
      ? [...value(id).tags, name]
      : value(id).tags.filter((t) => t !== name),
  });
}
</script>
<template>
  <p v-if="!entries.length">本次会话没有配置评估器。</p>
  <details
    v-for="entry in entries"
    :key="entry.spec.id"
    class="evaluator-review"
    :open="entry.spec.kind !== 'rule'"
  >
    <summary>
      {{ entry.spec.name }} ·
      {{
        entry.spec.kind === 'rule'
          ? '规则评估器'
          : entry.spec.kind === 'llm_judge'
            ? 'LLM评估器'
            : '组合评估器'
      }}
      · {{ entry.spec.version }}
    </summary>
    <div class="evaluator-columns">
      <div class="evaluator-evidence">
        <details>
          <summary>本次会话配置</summary>
          <pre>{{ displayValue(entry.spec) }}</pre>
        </details>
        <template v-if="entry.spec.kind === 'llm_judge'">
          <h4>LLM系统提示词</h4>
          <p v-if="entry.prompt_source === 'recorded'">实际请求留存</p>
          <p v-else-if="entry.prompt_source === 'reconstructed'">
            根据运行快照重建{{
              entry.request_hash_matches === true
                ? '，与原请求指纹一致'
                : '，无法确认为当时的完整请求'
            }}
          </p>
          <pre>{{ entry.system_prompt ?? '未留存系统提示词，且无法重建' }}</pre>
          <h4>评估请求证据</h4>
          <pre>{{ entry.user_prompt ?? '未留存请求正文' }}</pre>
        </template>
        <h4>评估结果</h4>
        <p v-if="entry.result">
          {{ entry.result.outcome }} · 得分 {{ entry.result.score ?? '—' }}（0—1）
        </p>
        <p>{{ entry.result?.reason ?? '暂无评估结果' }}</p>
        <template v-if="entry.spec.kind === 'rule'">
          <h4>关键证据</h4>
          <div v-for="check in entry.result?.checks ?? []" :key="check.id" class="check-evidence">
            <strong>{{ check.name }} · {{ check.outcome }}</strong>
            <p>{{ check.turn_id ? '所属轮次：' + check.turn_id : '会话整体' }}</p>
            <p>{{ check.reason }}</p>
            <h5>期望</h5>
            <pre>{{ displayValue(check.expected) }}</pre>
            <h5>实际</h5>
            <pre>{{ check.actual_missing ? '实际字段不存在' : displayValue(check.actual) }}</pre>
          </div>
        </template>
        <template v-if="entry.result?.judge_record"
          ><h4>LLM完整响应</h4>
          <pre>{{ entry.result.judge_record.raw_response }}</pre>
        </template>
        <details>
          <summary>完整评估结果</summary>
          <pre>{{ displayValue(entry.result) }}</pre>
        </details>
        <details>
          <summary>完整会话证据</summary>
          <pre>{{ displayValue(entry.evidence) }}</pre>
        </details>
        <template v-if="entry.spec.kind === 'rule'">
          <h4>规则关键代码</h4>
          <p>当前服务中对应实现版本的代码。</p>
          <p v-if="!entry.code.length">该实现的代码暂不可用。</p>
          <div v-for="code in entry.code" :key="code.name">
            <strong>{{ code.name }}</strong>
            <pre><code>{{ code.source }}</code></pre>
          </div>
        </template>
      </div>
      <div class="evaluator-scoring">
        <h4>人工标注 · {{ entry.spec.name }}</h4>
        <label v-for="d in criteria" :key="d.key" class="score-field">
          <span>{{ d.text }}（{{ min }}—{{ max }}）</span>
          <input
            type="number"
            :min="min"
            :max="max"
            step="any"
            :value="value(entry.spec.id).scores[d.key] ?? ''"
            :aria-label="entry.spec.name + ' ' + turnId + ' ' + d.text"
            @input="score(entry.spec.id, d.key, $event)"
          />
        </label>
        <div class="asset-chips">
          <label v-for="name in tags" :key="name"
            ><input
              type="checkbox"
              :checked="value(entry.spec.id).tags.includes(name)"
              @change="tag(entry.spec.id, name, $event)"
            />{{ name }}</label
          >
        </div>
        <label
          >评语<input
            :value="value(entry.spec.id).note"
            :aria-label="entry.spec.name + ' 评语'"
            @input="update(entry.spec.id, { note: ($event.target as HTMLInputElement).value })"
        /></label>
        <label v-if="entry.spec.kind === 'llm_judge'"
          >优化后的提示词
          <textarea
            rows="16"
            :value="value(entry.spec.id).optimizedPrompt"
            :aria-label="entry.spec.name + ' 优化后的提示词'"
            placeholder="填写优化后的提示词，随本次人工标注保存"
            @input="
              update(entry.spec.id, {
                optimizedPrompt: ($event.target as HTMLTextAreaElement).value,
              })
            "
          />
        </label>
      </div>
    </div>
  </details>
</template>
<style scoped>
.evaluator-review {
  background: white;
  border: 1px solid #dce7e1;
  border-radius: 12px;
  margin-bottom: 16px;
  overflow: hidden;
}
.evaluator-review > summary {
  padding: 16px 20px;
  cursor: pointer;
  font-weight: 600;
}
.evaluator-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  border-top: 1px solid #dce7e1;
}
.evaluator-evidence,
.evaluator-scoring {
  padding: 20px;
  min-width: 0;
}
.evaluator-scoring {
  border-left: 1px solid #dce7e1;
  background: #fbfdfc;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 50vh;
  overflow: auto;
  background: #f4f8f6;
  padding: 16px;
  font-size: 13px;
  line-height: 1.7;
}
p {
  color: #748278;
  font-size: 12px;
}
.score-field {
  display: flex;
  gap: 8px;
  align-items: center;
}
.evaluator-scoring .score-field input {
  width: calc(3ch + 24px);
  min-width: 0;
  flex: 0 0 auto;
  padding: 6px 8px;
  margin: 0;
}
.score-field span {
  flex: 1;
}
textarea {
  width: 100%;
  box-sizing: border-box;
}
</style>
