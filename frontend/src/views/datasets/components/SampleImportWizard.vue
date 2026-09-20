<script setup lang="ts">
import { computed, ref } from 'vue';
import SampleEditor from './SampleEditor.vue';
import { datasetApi } from '../../../api/datasets';
import { request } from '../../../api/evaluations';
import { annotationTasks } from '../../../stores/review-assets';
import { parseSampleFile, blankSample } from '../utils/sample-import';
import type { EvaluationCase } from '../types/index';
import type { Trace } from '../../../api/client';
import type { EvaluationRun } from '../../evaluation/types/run';
const props = defineProps<{ datasetId: string; datasetName: string }>();
const emit = defineEmits<{ close: []; manual: []; imported: [] }>();
const method = ref('manual'),
  step = ref(1),
  busy = ref(false),
  error = ref(''),
  items = ref<EvaluationCase[]>([]),
  taskId = ref(''),
  selected = ref<string[]>([]),
  saved = ref(0);
const task = computed(() =>
  annotationTasks.value.find((t) => t.id === taskId.value && !t.deletedAt),
);
const sessions = computed(() => [
  ...new Set(
    Object.keys(task.value?.annotations ?? {}).map((k) => k.split('/').slice(0, 2).join('/')),
  ),
]);
const done = new Set<string>();
function reset() {
  items.value = [];
  error.value = '';
  saved.value = 0;
  done.clear();
}
const manualItem = ref<EvaluationCase>(blankSample(''));
const manualDirty = ref(false);
function next() {
  reset();
  manualItem.value = blankSample('');
  manualDirty.value = false;
  step.value = 2;
}
async function saveManual(item: EvaluationCase) {
  items.value = [item];
  await save();
  if (step.value === 3) manualDirty.value = false;
}
function previous() {
  if (manualDirty.value && !window.confirm('放弃未保存的样本？')) return;
  manualDirty.value = false;
  step.value = 1;
  reset();
}
async function fileChanged(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  reset();
  if (!file) return;
  busy.value = true;
  try {
    items.value = await parseSampleFile(file);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
async function readAnnotations() {
  reset();
  if (!task.value || !selected.value.length) {
    error.value = '请选择标注模板和会话';
    return;
  }
  busy.value = true;
  try {
    const result: EvaluationCase[] = [];
    for (const key of selected.value) {
      const [run, caseId] = key.split('/');
      const trace = await request<Trace>(
        '/runs/' + encodeURIComponent(run) + '/traces/' + encodeURIComponent(caseId),
      );
      const report = await request<{ run: EvaluationRun }>('/runs/' + encodeURIComponent(run));
      const source = report.run.manifest.dataset.cases.find((c) => c.id === caseId);
      if (!source) throw Error('来源评测缺少样本快照，无法保留初始状态');
      const sample = blankSample(task.value.name + ' · ' + caseId.slice(0, 8));
      sample.initial_state = JSON.parse(JSON.stringify(source.initial_state));
      sample.category = source.category;
      sample.difficulty = source.difficulty;
      sample.tags = [...source.tags];
      sample.notes =
        '人工标注来源：模板 ' +
        task.value.id +
        '；评测 ' +
        run +
        '；样本 ' +
        caseId +
        '；Trace ' +
        trace.trace_id;
      sample.turns = source.turns.map((sourceTurn) => {
        const id = sourceTurn.id,
          outcome = trace.turn_outcomes?.[id];
        if (!outcome) throw Error('来源会话轮次缺少 Trace 输入，无法完整导入');
        const a = task.value!.annotations[key + '/' + id];
        if (!outcome.input || typeof outcome.input !== 'object' || Array.isArray(outcome.input))
          throw Error('Trace 输入不是对象，无法安全导入');
        const turn = blankSample().turns[0];
        turn.input = JSON.parse(JSON.stringify(outcome.input));
        if (a) {
          if (Object.values(a.scores).some((s) => s == null || !Number.isFinite(s)))
            throw Error('会话存在未完成评分');
          turn.notes =
            '来源轮次 ' + id + '；人工评分 ' + JSON.stringify(a.scores) + '；备注 ' + a.note;
          sample.tags.push(...a.tags);
          if (a.expected.trim())
            turn.expectations.push({
              id: crypto.randomUUID(),
              name: '人工期望输出',
              kind: 'output',
              path: null,
              condition: { kind: 'equals', expected: a.expected },
            });
        } else turn.notes = '来源轮次 ' + id + '；保留会话上下文，此轮未标注';
        return turn;
      });
      if (!sample.turns.length) throw Error('Trace 未提供轮次，无法导入');
      sample.tags = [...new Set(sample.tags)];
      result.push(sample);
    }
    items.value = result;
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
async function save() {
  if (!items.value.length || busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    let draft = await datasetApi.currentDraft(props.datasetId);
    for (const item of items.value) {
      if (done.has(item.id)) continue;
      if (draft.cases.some((c) => c.id === item.id)) {
        done.add(item.id);
        saved.value = done.size;
        continue;
      }
      draft = await datasetApi.addCase(props.datasetId, item, draft.content_sha256);
      done.add(item.id);
      saved.value = done.size;
    }
    step.value = 3;
    emit('imported');
  } catch (e) {
    error.value =
      String(e) +
      '；已确认保存 ' +
      done.size +
      ' 条。未清除成功记录，可重试；重试先核对服务器样本ID。';
  } finally {
    busy.value = false;
  }
}
function close() {
  if (busy.value) return;
  if (manualDirty.value && !window.confirm('放弃未保存的样本？')) return;
  emit('close');
}
</script>
<template>
  <el-dialog
    :model-value="true"
    title="新增样本"
    width="min(1050px,96vw)"
    :close-on-click-modal="false"
    :show-close="!busy"
    :close-on-press-escape="!busy"
    :before-close="close"
  >
    <div class="sample-wizard">
      <div class="steps">
        <b :class="{ active: step === 1 }">1 选择方式</b><span>—</span
        ><b :class="{ active: step === 2 }">2 配置填写</b><span>—</span
        ><b :class="{ active: step === 3 }">3 完成</b>
      </div>
      <h3>{{ datasetName }} · 新增样本</h3>
      <div v-if="step === 1" class="methods">
        <button
          v-for="m in [
            { id: 'manual', name: '＋ 手动创建', description: '多轮对话、期望输出与工具调用' },
            { id: 'file', name: '⇧ 导入数据集', description: 'JSON / Excel (.xlsx) / CSV / ZIP' },
            {
              id: 'annotation',
              name: '✓ 从标注导入',
              description: '选择标注模板，再选择已标注会话',
            },
          ]"
          :key="m.id"
          :class="{ selected: method === m.id }"
          @click="method = m.id"
        >
          <strong>{{ m.name }}</strong
          ><span>{{ m.description }}</span></button
        ><button disabled><strong>✦ AI 生成数据</strong><span>生成接口尚未接通</span></button>
      </div>
      <template v-if="step === 2">
        <SampleEditor
          v-if="method === 'manual'"
          :item="manualItem"
          :editable="true"
          :saving="busy"
          :persisted="false"
          :validation-issues="[]"
          @save="saveManual"
          @dirty-change="manualDirty = $event"
        />
        <template v-else-if="method === 'file'"
          ><label
            >选择文件<input
              type="file"
              accept=".json,.csv,.xlsx,.zip"
              aria-label="样本导入文件"
              :disabled="busy || saved > 0"
              @change="fileChanged"
          /></label>
          <p>
            CSV 使用 UTF-8，列名：case_name、query、expected（可选）；相同 case_id
            合并为多轮。也支持后端 Cases 表结构（input_json、expectations_json 等）和导出的
            JSON。ZIP 内只能包含上述格式，不含附件；最多1000个样本。
          </p></template
        >
        <template v-else
          ><label
            >标注模板<select
              v-model="taskId"
              aria-label="导入标注模板"
              :disabled="busy || saved > 0"
              @change="
                selected = [];
                reset();
              "
            >
              <option value="">请选择标注模板</option>
              <option
                v-for="t in annotationTasks.filter((t) => !t.deletedAt)"
                :key="t.id"
                :value="t.id"
              >
                {{ t.name }} · {{ t.app.external_target_id }}
              </option>
            </select></label
          >
          <p>
            读取当前页面已保存的人工标注；独立标注服务尚未接通。导入后的样本会保存到数据库，标注源本身仍为页面内存。
          </p>
          <label v-for="key in sessions" :key="key" class="session"
            ><input
              type="checkbox"
              v-model="selected"
              :value="key"
              :disabled="busy || saved > 0"
              @change="reset()"
            />评测 / 会话：{{ key }}</label
          >
          <p v-if="!sessions.length">暂无已保存的标注会话，请先在人工标注中完成评分并保存。</p>
          <button
            class="secondary"
            :disabled="!selected.length || busy || saved > 0"
            @click="readAnnotations"
          >
            读取所选会话
          </button></template
        >
        <p v-if="busy" role="status">正在处理，请勿关闭…</p>
        <table v-if="items.length && method !== 'manual'">
          <thead>
            <tr>
              <th>样本名称</th>
              <th>轮次</th>
              <th>期望检查</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>{{ item.name }}</td>
              <td>{{ item.turns.length }}</td>
              <td>
                {{
                  item.turns.reduce(
                    (n, t) =>
                      n +
                      t.expectations.length +
                      t.required_tools.length +
                      t.forbidden_tools.length,
                    0,
                  )
                }}
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="items.length && method !== 'manual'">
          预览
          {{ items.length }}
          条；导入只新增草稿样本，不覆盖已有样本、不自动发布。批量接口尚未提供，逐条写入并报告成功数量。
        </p>
      </template>
      <div v-if="step === 3" class="complete">
        <h2>✓ {{ method === 'manual' ? '创建完成' : '导入完成' }}</h2>
        <p>{{ saved }} 条样本已保存到数据库草稿，可继续管理、编辑和发布。</p>
      </div>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
    </div>
    <template #footer
      ><button class="secondary" :disabled="busy" @click="close">
        {{ step === 3 ? '返回数据样本' : '取消' }}</button
      ><button v-if="step === 1" class="primary" @click="next">下一步</button
      ><template v-if="step === 2"
        ><button class="secondary" :disabled="busy || saved > 0" @click="previous">上一步</button
        ><button
          v-if="method !== 'manual'"
          class="primary"
          :disabled="busy || !items.length"
          @click="save"
        >
          {{ saved ? '继续导入' : '确认导入到草稿' }}
        </button></template
      ></template
    >
  </el-dialog>
</template>
<style scoped>
.sample-wizard {
  color: #344158;
}
.steps {
  display: flex;
  justify-content: center;
  gap: 20px;
  padding: 25px;
  color: #99a3b4;
  font-size: 14px;
}
.steps .active {
  color: #008b76;
}
.methods {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
.methods button {
  display: flex;
  flex-direction: column;
  gap: 16px;
  text-align: left;
  padding: 28px;
  border: 1px solid #dce4ef;
  border-radius: 10px;
  background: white;
  color: #41516d;
}
.methods button.selected {
  border-color: #008b76;
  background: #f3f6ff;
}
.methods strong {
  font-size: 17px;
}
.methods span {
  font-size: 13px;
}
.methods button:disabled {
  opacity: 0.5;
}
.sample-wizard p {
  font-size: 12px;
  color: #7b8aa0;
  line-height: 1.8;
}
.sample-wizard label {
  display: block;
  margin: 14px 0;
}
.sample-wizard select,
.sample-wizard input[type='file'] {
  display: block;
  width: 100%;
  padding: 12px;
  border: 1px solid #dce4ef;
  border-radius: 8px;
  margin-top: 8px;
}
.session {
  font-size: 12px;
  overflow-wrap: anywhere;
}
.sample-wizard table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 20px;
}
th,
td {
  padding: 12px;
  border-bottom: 1px solid #e4eaf2;
  text-align: left;
  font-size: 13px;
}
.error {
  color: #c33 !important;
}
.complete {
  text-align: center;
  padding: 30px;
}
@media (max-width: 760px) {
  .methods {
    grid-template-columns: 1fr;
  }
  .steps {
    gap: 8px;
    padding: 16px 0;
  }
}
</style>
