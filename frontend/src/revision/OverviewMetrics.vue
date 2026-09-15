<script setup lang="ts">
import {ref,watch,onUnmounted} from 'vue'
import {api,score} from './api'
const days=ref(7),data=ref<any>(null),error=ref(''),loading=ref(false)
let sequence=0
async function load(){
 const ticket=++sequence;loading.value=true;error.value='';data.value=null
 const start=new Date();start.setHours(0,0,0,0);start.setDate(start.getDate()-(days.value-1))
 try{
 const [overview,runs]=await Promise.all([api.overview(),api.runs()])
 const period=runs.filter(r=>new Date(r.created_at)>=start),completed=period.filter(r=>r.status==='completed')
 const reports=[];let incomplete=false
 for(let i=0;i<completed.length;i+=6){if(ticket!==sequence)return;const batch=await Promise.allSettled(completed.slice(i,i+6).map(r=>api.report(r.id)));for(const item of batch){if(item.status==='fulfilled')reports.push(item.value);else incomplete=true}}
 if(ticket!==sequence)return
 const scores=reports.map(r=>r.metrics.find(m=>m.level==='overall')?.score).filter((n):n is number=>typeof n==='number')
 data.value={total_runs:period.length,average_score:incomplete?null:scores.length?scores.reduce((a,b)=>a+b,0)/scores.length:null,scored_runs:incomplete?null:scores.length,completed_samples:completed.reduce((n,r)=>n+(r.manifest.selected_case_ids??r.manifest.dataset.cases.map(c=>c.id)).length,0),dataset_samples:overview.case_count,dataset_count:overview.dataset_count}
 if(incomplete)error.value='部分报告读取失败，平均综合分暂不展示。'
 }catch(e){if(ticket===sequence)error.value=String(e)}finally{if(ticket===sequence)loading.value=false}
}
watch(days,load,{immediate:true})
onUnmounted(()=>sequence++)
</script>
<template>
 <section aria-label="总览统计">
  <div class="toolbar"><div class="tabs"><button v-for="d in [1,7,30]" :key="d" :class="['tab',{active:days===d}]" :aria-pressed="days===d" @click="days=d">{{d===1?'今日':'近'+d+'天'}}</button></div><button class="link" :disabled="loading" @click="load">刷新统计</button></div>
  <p class="muted">时间统计基于最近最多 200 条任务；未覆盖更早记录。</p>
  <p v-if="error" role="alert">{{error}}</p>
  <div class="overview-metrics">
   <article class="card"><div class="metric-label">评测任务总数</div><div class="metric-value">{{data?.total_runs??'—'}}</div><small>所选区间内创建的任务</small></article>
   <article class="card"><div class="metric-label">平均综合分</div><div class="metric-value">{{score(data?.average_score)}}<small> / 100</small></div><small>{{data?.scored_runs??'—'}} 个已完成且有有效评分的任务</small></article>
   <article class="card"><div class="metric-label">评测完成样本数</div><div class="metric-value">{{data?.completed_samples??'—'}}</div><small>已完成任务的执行用例数，重跑单独计数</small></article>
   <article class="card"><div class="metric-label">数据集样本</div><div class="metric-value">{{data?.dataset_samples??'—'}}</div><small>当前 {{data?.dataset_count??'—'}} 个未归档集的最新发布样本，不随时间筛选</small></article>
   <article class="card"><div class="metric-label">Token 消耗</div><div class="metric-value">—</div><small>当前未提供完整用量统计</small></article>
  </div>
 </section>
</template>
<style scoped>
.overview-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:16px;margin-bottom:24px}
small{color:#64748b;font-size:12px}.metric-value{margin:12px 0}
@media(max-width:1300px){.overview-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:700px){.overview-metrics{grid-template-columns:1fr}}
</style>
