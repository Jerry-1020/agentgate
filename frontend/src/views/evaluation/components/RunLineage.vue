<script setup lang="ts">
import { ref } from 'vue';
import { request } from '../../../api/evaluations';
const props = defineProps<{ runId: string }>();
const data = ref<any>(null),
  busy = ref(false),
  error = ref('');
function caseLink(n: any) {
  const edge = data.value?.edges.find(
    (e: any) => e.target_id === n.id && e.relation === 'contains_case',
  );
  const dataset = data.value?.nodes.find((d: any) => d.id === edge?.source_id);
  return dataset
    ? '#datasets/' +
        encodeURIComponent(dataset.external_id) +
        '?version=' +
        encodeURIComponent(dataset.version) +
        '&case=' +
        encodeURIComponent(n.external_id)
    : '';
}
const labels: Record<string, string> = {
  dataset: '评测集',
  case: '用例',
  evaluator: '评估器',
  agent: '智能体',
  skill: 'Skill',
  run: '任务',
};
async function load() {
  busy.value = true;
  error.value = '';
  try {
    data.value = await request('/runs/' + encodeURIComponent(props.runId) + '/lineage');
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <details @toggle="($event.target as HTMLDetailsElement).open && !data && !busy && load()">
    <summary>关联资产</summary>
    <p v-if="busy">正在查询…</p>
    <p v-if="error" role="alert">{{ error }} <button class="link" @click="load">重试</button></p>
    <table v-if="data" class="data-table">
      <thead>
        <tr>
          <th>资产类型</th>
          <th>名称</th>
          <th>本次引用版本</th>
          <th>内容指纹</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="n in data.nodes.filter((n: any) => n.kind !== 'run')" :key="n.id">
          <td>{{ labels[n.kind] ?? n.kind }}</td>
          <td>
            <a
              v-if="n.kind === 'dataset'"
              class="link"
              :href="'#datasets/' + n.external_id + '?version=' + n.version"
              >{{ n.label }}</a
            ><a
              v-else-if="n.kind === 'evaluator'"
              class="link"
              :href="
                '#evaluators/' +
                encodeURIComponent(n.external_id) +
                '?version=' +
                encodeURIComponent(n.version)
              "
              >{{ n.label }}</a
            ><a v-else-if="n.kind === 'case' && caseLink(n)" class="link" :href="caseLink(n)">{{
              n.label
            }}</a
            ><span v-else>{{ n.label }}</span>
          </td>
          <td>{{ n.version ?? '—' }}</td>
          <td>
            <span :title="n.content_sha256">{{ n.content_sha256?.slice(0, 12) ?? '—' }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </details>
</template>
