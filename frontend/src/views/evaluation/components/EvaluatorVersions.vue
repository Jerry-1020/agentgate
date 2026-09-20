<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { ElMessageBox, ElMessage } from 'element-plus';
import { request, type EvaluatorDetail, type Definition } from '../../../api/evaluations';
const props = defineProps<{
  item: EvaluatorDetail;
  unsaved: boolean;
  disabled: boolean;
  allowCreate?: boolean;
  activeVersion?: string | null;
}>();
const emit = defineEmits<{
  clone: [value: Definition];
  refresh: [];
  removed: [];
  busy: [value: boolean];
  select: [value: Definition | null];
}>();
const versions = ref<Definition[]>([]),
  version = ref(''),
  detail = ref<Definition | null>(props.item.draft ? null : props.item.latest);
watch(
  () => props.activeVersion,
  (v) => {
    if (v) {
      version.value = v;
      detail.value = versions.value.find((x) => x.version === v) ?? detail.value;
    }
  },
);
const loading = ref(false),
  error = ref(''),
  busy = ref(false);
let ticket = 0;
const path = '/evaluators/' + encodeURIComponent(props.item.evaluator.id);
onMounted(async () => {
  try {
    versions.value = await request<Definition[]>(path + '/versions');
    if (props.activeVersion) {
      version.value = props.activeVersion;
      detail.value = versions.value.find((x) => x.version === props.activeVersion) ?? null;
    }
  } catch (e) {
    error.value = String(e);
  }
});
onUnmounted(() => ticket++);
async function view() {
  const current = ++ticket;
  detail.value = null;
  if (!version.value) {
    detail.value = props.item.draft ? null : props.item.latest;
    emit('select', null);
    return;
  }
  loading.value = true;
  error.value = '';
  try {
    const result = await request<Definition>(
      path + '/versions/' + encodeURIComponent(version.value),
    );
    if (current === ticket) {
      detail.value = result;
      emit('select', result);
    }
  } catch (e) {
    if (current === ticket) error.value = String(e);
  } finally {
    if (current === ticket) loading.value = false;
  }
}
async function mutate(action: 'discard' | 'delete' | 'draft') {
  if (busy.value || props.disabled) return;
  if (action === 'draft' && props.unsaved) {
    ElMessage.warning('请先保存当前修改');
    return;
  }
  try {
    if (action !== 'draft')
      await ElMessageBox.confirm(
        action === 'discard'
          ? '丢弃当前草稿及未保存修改？已发布版本不变。'
          : '删除此未发布评估器及其草稿？此操作不可恢复。',
        action === 'discard' ? '丢弃评估器草稿' : '删除未发布评估器',
        {
          confirmButtonText: action === 'discard' ? '确认丢弃' : '确认删除',
          cancelButtonText: '取消',
          type: 'warning',
        },
      );
    busy.value = true;
    emit('busy', true);
    error.value = '';
    if (action === 'draft')
      await request(path + '/drafts', 'POST', { based_on_version: detail.value?.version ?? null });
    else await request(path + (action === 'discard' ? '/drafts/current' : ''), 'DELETE');
    ElMessage.success(
      action === 'draft'
        ? '已基于所选版本创建草稿'
        : action === 'discard'
          ? '草稿已丢弃，已发布版本保留'
          : '未发布评估器已删除',
    );
    if (action === 'delete') emit('removed');
    else emit('refresh');
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') error.value = String(e);
  } finally {
    busy.value = false;
    emit('busy', false);
  }
}
</script>
<template>
  <div class="version-management">
    <div class="toolbar">
      <label class="field"
        >查看版本<select
          class="input"
          aria-label="查看评估器历史版本"
          v-model="version"
          :disabled="disabled || busy || unsaved || loading"
          @change="view"
        >
          <option value="">{{ item.draft ? '当前草稿' : '最新发布版本 · 只读' }}</option>
          <option v-for="v in versions" :key="v.version" :value="v.version">
            v{{ v.version }} · 已发布 · 只读
          </option></select
        ><small v-if="unsaved">保存修改后可切换版本</small></label
      >
      <div v-if="item.evaluator.source !== 'builtin'" class="actions">
        <button
          v-if="item.draft"
          class="secondary"
          :disabled="disabled || busy"
          @click="mutate('discard')"
        >
          丢弃草稿
        </button>
        <button
          v-if="!item.latest"
          class="secondary"
          :disabled="disabled || busy"
          @click="mutate('delete')"
        >
          删除评估器
        </button>
        <span v-else class="muted">已发布评估器不可删除，可停用</span>
      </div>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <section v-if="detail" aria-label="已发布版本详情（只读）">
      <p v-if="loading">正在读取版本…</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <template v-if="allowCreate !== false"
        ><button
          v-if="item.evaluator.source === 'builtin'"
          class="primary"
          :disabled="disabled || busy || loading || unsaved"
          @click="emit('clone', detail)"
        >
          复制为自定义草稿</button
        ><button
          v-else-if="item.draft"
          class="primary"
          :disabled="disabled || busy || unsaved"
          @click="
            version = '';
            view();
          "
        >
          编辑草稿</button
        ><button
          v-else
          class="primary"
          :disabled="disabled || busy || loading || unsaved"
          @click="mutate('draft')"
        >
          基于此版本创建草稿</button
        ><small v-if="item.evaluator.source === 'builtin'" class="muted">
          内置定义只读；复制为自定义草稿后可编辑配置并发布。</small
        ></template
      >
    </section>
  </div>
</template>
<style scoped>
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 40vh;
  overflow: auto;
  font-size: 12px;
}
.version-management {
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 16px;
  margin-bottom: 16px;
}
</style>
