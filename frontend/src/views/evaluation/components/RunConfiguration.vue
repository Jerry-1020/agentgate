<script setup lang="ts">
import { computed, ref } from 'vue';
import { pretty } from '../../../api/evaluations';
const props = defineProps<{ manifest: object }>();
const selected = ref<any>(null);
const config = computed(() => props.manifest as Record<string, any>);
const templateLabels1: Record<string, string> = { rule: '规则', llm_judge: 'LLM', hybrid: '复合' };
</script>
<template>
  <div data-testid="run-configuration">
    <table class="data-table">
      <tbody>
        <tr>
          <th>智能体 / 版本</th>
          <td>{{ config.target.display_name }} · {{ config.target.ref.external_version_id }}</td>
        </tr>
        <tr>
          <th>测评集 / 版本</th>
          <td>
            <a
              class="link"
              :href="
                '#datasets/' + config.dataset.dataset_id + '?version=' + config.dataset.version
              "
              >{{ config.dataset.dataset_name }} · v{{ config.dataset.version }}</a
            >
          </td>
        </tr>
        <tr>
          <th>执行用例</th>
          <td>
            {{
              config.selected_case_ids
                ?.map(
                  (id: string) => config.dataset.cases.find((c: any) => c.id === id)?.name ?? id,
                )
                .join('、') || `全部用例（${config.dataset.cases.length} 条）`
            }}
          </td>
        </tr>
        <tr>
          <th>主评估器</th>
          <td>
            <span
              v-for="id in config.primary_evaluator_ids"
              :key="id"
              style="display: inline-block; margin-right: 16px"
              ><button
                class="link"
                @click="selected = config.evaluator_specs.find((e: any) => e.id === id)"
              >
                {{ config.evaluator_specs.find((e: any) => e.id === id)?.name ?? id }} · v{{
                  config.evaluator_specs.find((e: any) => e.id === id)?.version
                }}
              </button></span
            >
          </td>
        </tr>
        <tr>
          <th>执行参数</th>
          <td>
            并发 {{ config.max_parallel_cases ?? '未记录' }} · 超时
            {{ config.timeout_seconds ?? '未记录' }} 秒 · 重试
            {{ config.max_retries ?? '未记录' }} 次
          </td>
        </tr>
      </tbody>
    </table>
    <details>
      <summary>评估器版本与定义</summary>
      <pre>{{ pretty(config.evaluator_specs) }}</pre>
    </details>
    <details>
      <summary>指标与通过条件</summary>
      <pre>{{ pretty({ metric_plan: config.metric_plan, gate_spec: config.gate_spec }) }}</pre>
    </details>
    <details>
      <summary>完整任务配置快照</summary>
      <pre>{{ pretty(config) }}</pre>
    </details>
    <el-dialog
      :model-value="!!selected"
      @close="selected = null"
      title="本次引用的评估器版本"
      width="min(720px,92vw)"
      append-to-body
      ><template v-if="selected"
        ><h3>{{ selected.name }} · v{{ selected.version }}</h3>
        <p>
          {{ templateLabels1[selected.kind] }} · {{ selected.dimension }} · {{ selected.metric }}
        </p>
        <p>实现：{{ selected.implementation_id }} · {{ selected.implementation_version }}</p>
        <h4>执行配置</h4>
        <pre>{{ pretty(selected.config) }}</pre>
        <div v-if="selected.children?.length">
          <h4>子评估器与权重</h4>
          <pre>{{ pretty(selected.children) }}</pre>
        </div>
        <p class="muted">来自本次任务的不可变快照，不是最新草稿。</p>
        <a
          class="link"
          :href="
            '#evaluators/' +
            encodeURIComponent(selected.id) +
            '?version=' +
            encodeURIComponent(selected.version)
          "
          @click="selected = null"
          >查看此评估器版本</a
        ></template
      ></el-dialog
    >
  </div>
</template>
<style scoped>
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
}
td {
  overflow-wrap: anywhere;
}
th {
  min-width: 110px;
}
details {
  margin-top: 12px;
}
summary {
  cursor: pointer;
}
</style>
