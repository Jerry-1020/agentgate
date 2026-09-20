<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { EvaluationCase, ValidationIssue } from '../types/index';
import { blankSample } from '../utils/sample-import';
import JsonCodeEditor from '../../../components/JsonCodeEditor.vue';
import ExpectationEditor from './ExpectationEditor.vue';
const props = defineProps<{
  item: EvaluationCase | null;
  editable: boolean;
  saving?: boolean;
  persisted?: boolean;
  validationIssues?: ValidationIssue[];
}>();
const emit = defineEmits<{ save: [item: EvaluationCase]; dirtyChange: [dirty: boolean] }>();
const form = ref<EvaluationCase | null>(null),
  index = ref(0),
  preview = ref(false),
  error = ref(''),
  query = ref('');
const inputs = ref<string[]>([]),
  inputJson = ref<boolean[]>([]),
  outputs = ref<string[]>([]),
  outputJson = ref<boolean[]>([]),
  outputIds = ref<(string | null)[]>([]);
const baseline = ref(''),
  inputField = ref<'query' | 'txt'>('txt');
const turn = computed(() => form.value?.turns[index.value]);
function snapshot() {
  return JSON.stringify([
    form.value,
    inputs.value,
    inputJson.value,
    outputs.value,
    outputJson.value,
    inputField.value,
  ]);
}
const dirty = computed(() => snapshot() !== baseline.value);
watch(dirty, (v) => emit('dirtyChange', v));
watch(
  () => props.item,
  (item) => {
    inputField.value = item?.turns.some((t) => 'txt' in t.input)
      ? 'txt'
      : item?.turns.some((t) => String(t.input.query ?? '').trim())
        ? 'query'
        : 'txt';
    form.value = item ? JSON.parse(JSON.stringify(item)) : null;
    index.value = 0;
    error.value = '';
    inputJson.value =
      item?.turns.map(
        (t) =>
          !(
            Object.keys(t.input).length === 1 && typeof (t.input.query ?? t.input.txt) === 'string'
          ),
      ) ?? [];
    inputs.value =
      item?.turns.map((t, i) =>
        inputJson.value[i]
          ? JSON.stringify(t.input, null, 2)
          : String(t.input.query ?? t.input.txt),
      ) ?? [];
    outputIds.value =
      item?.turns.map(
        (t) =>
          t.expectations.find(
            (e) => e.kind === 'output' && e.path === null && e.condition.kind === 'equals',
          )?.id ?? null,
      ) ?? [];
    outputJson.value = [];
    outputs.value = [];
    item?.turns.forEach((t, i) => {
      const e = t.expectations.find((e) => e.id === outputIds.value[i]);
      const value = e?.condition.kind === 'equals' ? e.condition.expected : undefined;
      outputJson.value.push(value !== undefined && typeof value !== 'string');
      outputs.value.push(
        value === undefined
          ? ''
          : typeof value === 'string'
            ? value
            : JSON.stringify(value, null, 2),
      );
    });
    baseline.value = snapshot();
    emit('dirtyChange', false);
  },
  { immediate: true },
);
function add() {
  form.value!.turns.push(blankSample().turns[0]);
  inputs.value.push('');
  inputJson.value.push(false);
  outputs.value.push('');
  outputJson.value.push(false);
  outputIds.value.push(null);
  index.value = form.value!.turns.length - 1;
}
function remove() {
  if (!form.value || form.value.turns.length < 2) return;
  form.value.turns.splice(index.value, 1);
  for (const list of [
    inputs.value,
    inputJson.value,
    outputs.value,
    outputJson.value,
    outputIds.value,
  ])
    list.splice(index.value, 1);
  index.value = Math.max(0, index.value - 1);
}
function save() {
  error.value = '';
  if (!form.value?.name.trim()) {
    error.value = '请输入样本名称';
    return;
  }
  try {
    const item: EvaluationCase = JSON.parse(JSON.stringify(form.value));
    item.turns.forEach((t, i) => {
      if (!inputs.value[i].trim()) throw Error('第 ' + (i + 1) + ' 轮用户输入不能为空');
      t.input = inputJson.value[i]
        ? JSON.parse(inputs.value[i])
        : { [inputField.value]: inputs.value[i] };
      if (!t.input || typeof t.input !== 'object' || Array.isArray(t.input))
        throw Error('用户输入 JSON 必须为对象');
      const original = t.expectations.find((e) => e.id === outputIds.value[i]);
      t.expectations = t.expectations.filter((e) => e.id !== outputIds.value[i]);
      if (outputs.value[i].trim())
        t.expectations.push({
          ...original,
          id: original?.id ?? crypto.randomUUID(),
          name: original?.name ?? '人工期望输出',
          kind: 'output',
          path: null,
          condition: {
            kind: 'equals',
            expected: outputJson.value[i] ? JSON.parse(outputs.value[i]) : outputs.value[i],
          },
        });
    });
    emit('save', item);
  } catch (e) {
    error.value = '保存失败：' + String(e);
  }
}
defineExpose({ save });
</script>
<template>
  <section class="sample-editor">
    <p v-if="!form" class="empty">选择数据样本，或点击新增样本。</p>
    <template v-else>
      <div class="sample-meta">
        <label
          >输入字段<select v-model="inputField" :disabled="!editable" aria-label="输入字段">
            <option value="txt">txt · 银行智能体</option>
            <option value="query">query · 通用</option>
          </select></label
        ><label
          >样本名称<input v-model="form.name" :disabled="!editable" aria-label="样本名称" /></label
        ><label
          >分类<select v-model="form.category" :disabled="!editable">
            <option value="positive">正例</option>
            <option value="negative">负例</option>
            <option value="boundary">边界</option>
          </select></label
        ><label
          >场景标签<input
            :value="form.tags.join('，')"
            :disabled="!editable"
            @change="
              form.tags = ($event.target as HTMLInputElement).value
                .split(/[,，]/)
                .map((s) => s.trim())
                .filter(Boolean)
            "
        /></label>
      </div>
      <div class="conversation-layout">
        <aside>
          <div class="round-title">
            <b>轮次列表（{{ form.turns.length }}）</b
            ><button @click="preview = !preview">{{ preview ? '编辑' : '对话预览' }}</button>
          </div>
          <input v-model="query" aria-label="搜索轮次内容" placeholder="搜索轮次内容" /><button
            v-for="(t, i) in form.turns"
            v-show="!query || inputs[i].includes(query)"
            :key="t.id"
            class="round"
            :class="{ active: index === i }"
            @click="index = i"
          >
            <b>第 {{ i + 1 }} 轮</b><small>{{ inputs[i] || '未填写内容' }}</small></button
          ><button v-if="editable" class="add-round" @click="add">＋ 添加新轮次</button>
        </aside>
        <div v-if="turn" class="turn-content">
          <div class="message-card user">
            <header>
              <b>用户 · 用户输入</b><span>{{ inputs[index].length }} 字</span>
            </header>
            <pre v-if="preview">{{ inputs[index] }}</pre>
            <template v-else
              ><label
                ><input type="checkbox" v-model="inputJson[index]" :disabled="!editable" />结构化
                JSON 输入</label
              ><JsonCodeEditor
                v-if="inputJson[index]"
                :key="turn.id + 'input'"
                :model-value="inputs[index]"
                :disabled="!editable"
                label="用户输入 JSON"
                @update:model-value="inputs[index] = $event"
              /><textarea
                v-else
                v-model="inputs[index]"
                :disabled="!editable"
                rows="5"
                aria-label="用户输入"
                placeholder="请输入用户提问内容"
              />
            </template>
          </div>
          <div class="message-card expected">
            <header>
              <b>AI · 期望输出</b><span>{{ outputs[index].length }} 字</span>
            </header>
            <pre v-if="preview">{{ outputs[index] || '未设置人工期望' }}</pre>
            <template v-else
              ><label
                ><input type="checkbox" v-model="outputJson[index]" :disabled="!editable" />结构化
                JSON 期望</label
              ><JsonCodeEditor
                v-if="outputJson[index]"
                :key="turn.id + 'output'"
                :model-value="outputs[index]"
                :disabled="!editable"
                label="期望输出 JSON"
                @update:model-value="outputs[index] = $event"
              /><textarea
                v-else
                v-model="outputs[index]"
                :disabled="!editable"
                rows="5"
                aria-label="期望输出"
                placeholder="人工确认的期望输出，不自动复制实际回答"
              />
            </template>
          </div>
          <div class="message-card tools">
            <header><b>工具 · 期望工具调用</b></header>
            <label
              >必需工具（逗号分隔）<input
                :value="turn.required_tools.join('，')"
                :disabled="!editable"
                @change="
                  turn.required_tools = ($event.target as HTMLInputElement).value
                    .split(/[,，]/)
                    .map((s) => s.trim())
                    .filter(Boolean)
                " /></label
            ><label
              >禁止工具（逗号分隔）<input
                :value="turn.forbidden_tools.join('，')"
                :disabled="!editable"
                @change="
                  turn.forbidden_tools = ($event.target as HTMLInputElement).value
                    .split(/[,，]/)
                    .map((s) => s.trim())
                    .filter(Boolean)
                "
            /></label>
          </div>
          <details class="advanced">
            <summary>高级检查 · Skill、规则条件与备注</summary>
            <label>期望 Skill<input v-model="turn.expected_skill" :disabled="!editable" /></label
            ><ExpectationEditor
              :model-value="turn.expectations.filter((e) => e.id !== outputIds[index])"
              :disabled="!editable"
              @update:model-value="
                turn.expectations = [
                  ...turn.expectations.filter((e) => e.id === outputIds[index]),
                  ...$event,
                ]
              "
            /><label>轮次备注<textarea v-model="turn.notes" :disabled="!editable" /></label>
          </details>
          <button v-if="editable && form.turns.length > 1" class="remove-round" @click="remove">
            删除当前轮次（保存后生效）
          </button>
        </div>
      </div>
      <div class="editor-footer">
        <span>{{
          editable
            ? dirty || !persisted
              ? '● 有未保存的修改'
              : '已保存到数据库草稿'
            : '已发布版本 · 只读'
        }}</span
        ><button v-if="editable" class="primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存样本' }}
        </button>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-for="issue in validationIssues" :key="issue.path" class="error">
        {{ issue.path }}：{{ issue.message }}
      </p>
    </template>
  </section>
</template>
<style scoped>
.sample-editor {
  background: #fff;
  border: 1px solid #e0e6f0;
  border-radius: 12px;
  overflow: hidden;
  min-width: 0;
  color: #34435a;
}
.sample-meta {
  padding: 18px;
  display: flex;
  gap: 16px;
  border-bottom: 1px solid #e1e7f1;
}
.sample-meta label {
  flex: 1;
  min-width: 0;
}
.sample-editor label {
  display: block;
  font-size: 12px;
  color: #74829a;
  margin: 8px 0;
}
.sample-editor input:not([type='checkbox']),
.sample-editor select,
.sample-editor textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #dbe2ee;
  border-radius: 7px;
  background: #fff;
  padding: 10px;
  margin-top: 7px;
  color: #34435a;
  font: inherit;
}
.sample-editor textarea:disabled {
  background: #f8fafc;
}
.conversation-layout {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
}
aside {
  padding: 16px;
  background: #f6f8fc;
  border-right: 1px solid #e1e7f1;
}
.round-title {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}
.round-title button {
  border: 0;
  background: white;
  color: #008b76;
}
.round {
  display: block;
  width: 100%;
  text-align: left;
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 16px;
  margin: 8px 0;
  color: #52617b;
}
.round.active {
  background: #eaf7f2;
  color: #008b76;
}
.round small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 6px;
}
.add-round {
  width: 100%;
  border: 1px dashed #bacbe4;
  background: white;
  padding: 12px;
  border-radius: 6px;
  color: #527399;
}
.turn-content {
  padding: 20px;
  background: #fafbfd;
  min-width: 0;
}
.message-card {
  background: #fff;
  border: 1px solid #e1e7f1;
  border-top: 3px solid #89acff;
  border-radius: 10px;
  margin-bottom: 16px;
  padding: 16px;
}
.message-card header {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 16px;
}
.message-card header span {
  font-size: 11px;
  color: #9da7b7;
}
.expected {
  border-top-color: #7ed9b8;
}
.tools {
  border-top-color: #b294ff;
}
.message-card pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
  font-size: 13px;
}
.advanced {
  font-size: 12px;
  padding: 12px;
  color: #70829a;
}
.editor-footer {
  display: flex;
  justify-content: space-between;
  padding: 16px;
  border-top: 1px solid #e1e7f1;
  font-size: 12px;
  color: #8090a7;
}
.error {
  color: #c33;
  padding: 0 16px;
}
.remove-round {
  background: transparent;
  border: 0;
  color: #c55;
  font-size: 12px;
}
.empty {
  padding: 60px;
  text-align: center;
  color: #93a0b3;
}
@media (max-width: 760px) {
  .conversation-layout {
    grid-template-columns: 1fr;
  }
  .sample-meta {
    flex-wrap: wrap;
  }
  .sample-meta label {
    min-width: 180px;
  }
  aside {
    border-right: 0;
    max-height: 220px;
    overflow: auto;
  }
}
</style>
