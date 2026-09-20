<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import {
  scoringDrafts,
  extractedTemplates,
  loadReviewAssets,
  assetsLoading,
  assetsError,
  copy,
  validateCriteria,
  exportUx,
  type ScoringTemplate,
} from '../../../stores/review-assets';
import '../../../styles/review-assets.scss';
const props = defineProps<{ initialId?: string }>(),
  emit = defineEmits<{ dirtyChange: [value: boolean] }>();
const query = ref(''),
  filter = ref('all'),
  detail = ref<ScoringTemplate | null>(null),
  edit = ref<ScoringTemplate | null>(null),
  error = ref('');
const templates = computed(() => [...scoringDrafts.value, ...extractedTemplates.value]);
const filtered = computed(() =>
  templates.value.filter(
    (t) =>
      (filter.value === 'all' || (filter.value === 'preview') === t.preview) &&
      `${t.name} ${t.dimension} ${t.metric}`.toLowerCase().includes(query.value.toLowerCase()),
  ),
);
watch(edit, (v) => emit('dirtyChange', !!v));
function openEdit(source?: ScoringTemplate) {
  detail.value = null;
  edit.value = source
    ? {
        ...copy(source),
        id: crypto.randomUUID(),
        name: source.name + '（UX 副本）',
        version: 'UX',
        preview: true,
        evaluatorId: undefined,
      }
    : {
        id: crypto.randomUUID(),
        name: '',
        description: '',
        instruction: '',
        criteria: [{ key: '', text: '' }],
        dimension: 'answer',
        metric: '',
        version: 'UX',
        preview: true,
      };
  error.value = '';
}
function save() {
  const t = edit.value;
  if (!t) return;
  error.value =
    !t.name.trim() || !t.instruction.trim() || !t.dimension.trim() || !t.metric.trim()
      ? '请填写名称、提示词、评估维度与指标。'
      : validateCriteria(t.criteria, true);
  if (error.value) return;
  scoringDrafts.value.unshift(copy(t));
  detail.value = copy(t);
  edit.value = null;
}
function closeEdit() {
  if (edit.value && !window.confirm('放弃未保存的评分模板？')) return;
  edit.value = null;
}
onMounted(async () => {
  await loadReviewAssets();
  if (props.initialId) {
    try {
      detail.value =
        templates.value.find((t) => t.id === decodeURIComponent(props.initialId!)) ?? null;
    } catch {
      error.value = '评分模板地址无效。';
    }
  }
});
</script>
<template>
  <section class="review-assets" aria-label="评分模板管理">
    <div class="asset-heading">
      <div>
        <h1>评分模板</h1>
        <p>独立维护提示词与评估维度，裁判引用模板决定如何评分。</p>
      </div>
      <div class="actions">
        <button class="asset-secondary" :disabled="assetsLoading" @click="loadReviewAssets">
          刷新</button
        ><button class="asset-primary" @click="openEdit()">＋ 新建评分模板</button>
      </div>
    </div>
    <p class="asset-note">
      已发布内容从 LLM 评估器配置提取，只读展示。新建与复制为 UX
      草稿，刷新后清除；不会修改后端裁判。模型连接不属于评分模板。
    </p>
    <p v-if="assetsError" class="asset-error" role="alert">{{ assetsError }}</p>
    <div class="asset-filters">
      <input
        v-model="query"
        aria-label="搜索评分模板"
        placeholder="搜索模板名称、评估维度或指标"
      /><select v-model="filter" aria-label="评分模板来源">
        <option value="all">全部来源</option>
        <option value="server">后端已发布</option>
        <option value="preview">UX 草稿</option>
      </select>
    </div>
    <p v-if="assetsLoading" class="asset-empty">读取评分模板…</p>
    <div v-else class="asset-grid">
      <article v-for="t in filtered" :key="t.id" class="asset-card">
        <span :class="['asset-chip', { preview: t.preview }]">{{
          t.preview ? 'UX 草稿 · 未入库' : '后端已发布 · v' + t.version
        }}</span>
        <h2>{{ t.name }}</h2>
        <p>{{ t.description || '暂无描述' }}</p>
        <div class="asset-chips">
          <span class="asset-chip">{{ t.dimension }}</span
          ><span class="asset-chip">{{ t.criteria.length }} 项评分标准</span>
        </div>
        <div class="asset-card-actions">
          <button class="asset-link" @click="detail = t">查看模板</button
          ><button class="asset-link" @click="openEdit(t)">复制为 UX 草稿</button>
        </div>
      </article>
    </div>
    <p v-if="!assetsLoading && !filtered.length" class="asset-empty">暂无匹配的评分模板</p>
  </section>
  <el-dialog
    :model-value="!!detail"
    @close="detail = null"
    title="评分模板详情"
    width="min(850px,95vw)"
    class="asset-dialog"
    ><template v-if="detail"
      ><h2>{{ detail.name }}</h2>
      <p class="asset-small">
        {{
          detail.preview
            ? 'UX 草稿，未入库'
            : '来源评估器：' + detail.evaluatorId + ' · v' + detail.version
        }}
      </p>
      <section class="asset-panel">
        <h3>模型提示词</h3>
        <pre>{{ detail.instruction || '未提供' }}</pre>
      </section>
      <section class="asset-panel">
        <h3>评估维度 · {{ detail.dimension }}</h3>
        <p>指标：{{ detail.metric }}</p>
        <article v-for="c in detail.criteria" :key="c.key">
          <h4>{{ c.key }}</h4>
          <pre>{{ c.text }}</pre>
        </article>
      </section></template
    ><template #footer
      ><button class="asset-secondary" @click="detail = null">关闭</button
      ><button
        v-if="detail"
        class="asset-secondary"
        @click="exportUx(detail, 'scoring-template-ux.json')"
      >
        导出查看快照</button
      ><button v-if="detail" class="asset-primary" @click="openEdit(detail)">
        复制并编辑
      </button></template
    ></el-dialog
  >
  <el-dialog
    :model-value="!!edit"
    :before-close="closeEdit"
    title="新建评分模板"
    width="min(920px,96vw)"
    :close-on-click-modal="false"
    class="asset-dialog"
    ><template v-if="edit"
      ><div class="asset-form-grid">
        <label
          >模板名称 *<input v-model="edit.name" maxlength="128" aria-label="评分模板名称" /></label
        ><label
          >评估维度 *<input
            v-model="edit.dimension"
            aria-label="评分模板评估维度"
            placeholder="例如 answer" /></label
        ><label
          >评估指标 *<input
            v-model="edit.metric"
            aria-label="评分模板指标"
            placeholder="例如 answer_quality" /></label
        ><label>描述<input v-model="edit.description" maxlength="512" /></label>
      </div>
      <label
        >模型提示词 *<textarea
          v-model="edit.instruction"
          rows="6"
          aria-label="评分模板提示词"
          placeholder="说明裁判应依据哪些证据判断；不要填写 API Key。"
        />
      </label>
      <section class="asset-panel">
        <h3>评分标准 · {{ edit.criteria.length }} 项</h3>
        <div v-for="(c, i) in edit.criteria" :key="i" class="criterion-row">
          <input
            v-model="c.key"
            :aria-label="'评分标准标识 ' + (i + 1)"
            placeholder="例如 correctness"
          /><textarea
            v-model="c.text"
            :aria-label="'评分标准说明 ' + (i + 1)"
            rows="2"
            placeholder="写明评分依据"
          /><button @click="edit.criteria.splice(i, 1)" :aria-label="'删除评分标准 ' + (i + 1)">
            移除
          </button>
        </div>
        <button class="asset-link" @click="edit.criteria.push({ key: '', text: '' })">
          ＋ 添加评分标准
        </button>
      </section>
      <p class="asset-small">
        通过分数、输入范围和模型连接在裁判系统配置；此处只定义评分内容。
      </p></template
    ><template #footer
      ><p v-if="error" role="alert" class="asset-error">{{ error }}</p>
      <div class="asset-footer">
        <span class="asset-footnote">UX 草稿 · 未写入数据库</span
        ><button class="asset-secondary" @click="closeEdit">取消</button
        ><button class="asset-primary" @click="save">保存 UX 草稿</button>
      </div></template
    ></el-dialog
  >
</template>
