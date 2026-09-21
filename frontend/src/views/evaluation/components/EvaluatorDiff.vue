<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Definition } from '../../../api/evaluations';
const props = defineProps<{ versions: Definition[] }>();
const left = ref(''),
  right = ref('');
const a = computed(() => props.versions.find((v) => v.version === left.value)),
  b = computed(() => props.versions.find((v) => v.version === right.value));
function flatten(value: unknown, path = ''): Record<string, string> {
  if (value && typeof value === 'object' && !Array.isArray(value))
    return Object.assign(
      {},
      ...Object.entries(value).map(([k, v]) => flatten(v, path ? path + '.' + k : k)),
    );
  return { [path]: typeof value === 'string' ? value : (JSON.stringify(value) ?? '未设置') };
}
const changes = computed(() => {
  if (!a.value || !b.value) return [];
  const fields = [
    'kind',
    'dimension',
    'metric',
    'severity',
    'implementation_id',
    'implementation_version',
    'config',
    'children',
    'combination',
  ];
  const x = flatten(Object.fromEntries(fields.map((f) => [f, (a.value as any)[f]]))),
    y = flatten(Object.fromEntries(fields.map((f) => [f, (b.value as any)[f]])));
  return [...new Set([...Object.keys(x), ...Object.keys(y)])]
    .filter((k) => x[k] !== y[k])
    .map((k) => ({ key: k, a: x[k] ?? '未设置', b: y[k] ?? '未设置' }));
});
</script>
<template>
  <details class="section-gap">
    <summary>版本差异</summary>
    <p v-if="versions.length < 2">至少发布两个版本后可比较。</p>
    <template v-else
      ><div class="form-grid">
        <label class="field"
          >原版本<select class="input" v-model="left" aria-label="对比原版本">
            <option value="">请选择</option>
            <option v-for="v in versions" :key="v.version" :value="v.version">
              v{{ v.version }}
            </option>
          </select></label
        ><label class="field"
          >新版本<select class="input" v-model="right" aria-label="对比新版本">
            <option value="">请选择</option>
            <option v-for="v in versions" :key="v.version" :value="v.version">
              v{{ v.version }}
            </option>
          </select></label
        >
      </div>
      <table v-if="a && b && left !== right" class="data-table">
        <thead>
          <tr>
            <th>变化字段</th>
            <th>原版本</th>
            <th>新版本</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, rowIndex1) in changes" :key="rowIndex1">
            <td>{{ r.key }}</td>
            <td>
              <pre>{{ r.a }}</pre>
            </td>
            <td>
              <pre>{{ r.b }}</pre>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="a && b">
        {{
          left === right ? '请选择不同版本' : changes.length ? '仅展示变化字段' : '执行配置无差异'
        }}
      </p></template
    >
  </details>
</template>
<style scoped>
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-width: 300px;
}
</style>
