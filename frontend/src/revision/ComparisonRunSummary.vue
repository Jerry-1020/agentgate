<script setup lang="ts">
import {computed,ref} from 'vue'
import {score,statusLabel,type Report} from './api'
import {frozenEvaluators} from './comparison-compatibility'
import RunConfiguration from './RunConfiguration.vue'
const props=defineProps<{report:Report}>()
const run=computed(()=>props.report.run),evaluators=computed(()=>frozenEvaluators(run.value))
const scope=computed(()=>{
 const manifest=run.value.manifest as typeof run.value.manifest&{selected_case_ids?:string[]|null}
 const count=manifest.selected_case_ids?.length??manifest.dataset.cases.length
 return (manifest.selected_case_ids==null?'全部用例':'指定用例')+' · '+count+' 条'
})
const expanded=ref(false)
</script>
<template>
 <article class="history-result" data-testid="history-result">
  <div class="verdict-line"><div><span class="muted">综合得分</span><strong>{{score(report.metrics.find(m=>m.level==='overall')?.score)}}</strong></div><span :class="['badge',report.release_gate.outcome==='pass'?'success':report.release_gate.outcome==='fail'?'error':'warn']">{{statusLabel(report.release_gate.outcome)}}</span></div>
  <dl>
   <dt>智能体</dt><dd>{{run.manifest.target.display_name}} · {{run.manifest.target.ref.external_version_id}}</dd>
   <dt>评测集</dt><dd>{{run.manifest.dataset.dataset_name}} · v{{run.manifest.dataset.version}}</dd>
   <dt>执行用例</dt><dd>{{scope}}</dd>
  </dl>
  <details class="evaluator-summary"><summary>本次实际使用的评估器 · {{evaluators.length}} 个</summary><ul><li v-for="e in evaluators" :key="e.id">{{e.label}}</li></ul></details>
  <div class="run-identity"><span>完成于 {{new Date(run.completed_at??run.created_at).toLocaleString()}}</span><span>任务 ID：{{run.id}}</span></div>
  <a class="link" :href="'#results/'+run.id">查看原报告 →</a>
  <details class="frozen-details" @toggle="expanded=($event.target as HTMLDetailsElement).open"><summary>任务详情与执行参数（只读）</summary><RunConfiguration v-if="expanded" :manifest="run.manifest"/></details>
 </article>
</template>
<style scoped>
.history-result{margin-top:14px;padding:16px;background:#f9fbfb;border:1px solid #e5eaea;border-radius:7px;min-width:0}
.verdict-line{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.verdict-line strong{font-size:28px;line-height:1.2;color:#172b2f;margin-left:12px;font-weight:650}.verdict-line .badge{font-size:13px}
dl{display:grid;grid-template-columns:70px minmax(0,1fr);gap:8px;margin:0;font-size:13px;line-height:1.5}dt{color:#687382}dd{margin:0;overflow-wrap:anywhere}
.evaluator-summary{margin:12px 0;font-size:13px}.evaluator-summary ul{display:flex;flex-wrap:wrap;gap:6px 20px;padding-left:18px;margin:10px 0}.run-identity{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#6b7280;margin:12px 0;overflow-wrap:anywhere}
.link,.frozen-details{font-size:13px}.frozen-details{margin-top:14px}.frozen-details :deep(.data-table){font-size:12px}.frozen-details :deep(th){min-width:0;white-space:normal}.frozen-details :deep(td){word-break:break-word}
</style>
