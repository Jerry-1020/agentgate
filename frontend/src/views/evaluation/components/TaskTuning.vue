<script setup lang="ts">
import { shallowRef, ref, watch, onUnmounted } from 'vue';
import { api, type Report } from '../../../api/evaluations';
import ReportEvidenceAnalysis from './ReportEvidenceAnalysis.vue';
const props = defineProps<{ runIds: string[] }>();
const selected = ref(props.runIds[0] ?? ''),
  report = shallowRef<Report | null>(null),
  error = ref(''),
  busy = ref(false);
let ticket = 0;
async function load() {
  const current = ++ticket;
  report.value = null;
  error.value = '';
  busy.value = true;
  try {
    const progress = await api.status(selected.value);
    if (progress.status !== 'completed')
      throw Error('所选运行尚未完成，请完成后刷新查看调优分析。');
    const value = await api.report(selected.value);
    if (current === ticket) report.value = value;
  } catch (e) {
    if (current === ticket) error.value = String(e);
  } finally {
    if (current === ticket) busy.value = false;
  }
}
watch(selected, load, { immediate: true });
onUnmounted(() => ticket++);
</script>
<template>
  <div class="tuning-sides">
    <button
      v-for="(id, index) in runIds"
      :key="id"
      :class="['secondary', { selected: selected === id }]"
      @click="selected = id"
    >
      实验 {{ index === 0 ? 'A · 基线' : 'B · 候选' }}</button
    ><span>分别查看两侧的问题与改进建议</span>
  </div>
  <p v-if="busy" role="status">正在读取真实评测报告…</p>
  <p v-if="error" role="alert">{{ error }} <button class="link" @click="load">重试</button></p>
  <ReportEvidenceAnalysis v-if="report" :report="report" />
</template>
<style scoped>
.tuning-sides {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.tuning-sides span {
  color: #738078;
  font-size: 12px;
}
.tuning-sides .selected {
  background: #e6f5ed;
  border-color: #00a687;
  color: #008368;
}
</style>
