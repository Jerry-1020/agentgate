<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref,watch} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import RerunDialog from './RerunDialog.vue'
import RunConfiguration from './RunConfiguration.vue'
import RunLineage from './RunLineage.vue'
import CaseReport from './CaseReport.vue'
import {needsAttention} from './report-presentation'
const rerunPreview=ref(false)
const noEvidence=computed(()=>report.value?.release_gate.reason_code==='no_applicable_results')
import {api,request,statusLabel,score,metricLabel,type Report,type Trace,type RunProgress,type RunSamples} from './api'
const props=withDefaults(defineProps<{id:string;returnPage?:string}>(),{returnPage:'tasks'}),emit=defineEmits<{navigate:[path:string]}>()
const progress=ref<RunProgress|null>(null),report=ref<Report|null>(null),trace=ref<Trace|null>(null),error=ref(''),traceError=ref(''),busy=ref(false),caseId=ref(''),filter=ref(''),traceLoading=ref(false)
let timer:ReturnType<typeof setTimeout>|undefined,disposed=false,traceRequest=0
const evidence=ref<RunSamples|null>(null)
const groups=computed(()=>Array.from(new Set(evidence.value?.results.map(r=>r.case_id)??[])))
const filteredCases=computed(()=>groups.value.filter(id=>!filter.value||evidence.value?.results.some(r=>r.case_id===id&&r.outcome===filter.value)))
const results=computed(()=>evidence.value?.results.filter(r=>r.case_id===caseId.value)??[])
const attentionCount=(id:string)=>evidence.value?.results.filter(r=>r.case_id===id&&needsAttention(r)).length??0
const sample=computed(()=>evidence.value?.run.manifest.dataset.cases.find(c=>c.id===caseId.value))
async function update(){
 try{
  const p=await api.status(props.id)
  const completed=p.status==='completed'?await api.report(props.id):null
  const manifest=completed?.run.manifest??await request<any>(`/runs/${props.id}/manifest`)
  const s={run:completed?.run??({id:props.id,status:p.status,manifest} as any),results:completed?.results??[],complete:!!completed}
  if(disposed)return
  progress.value=p;evidence.value=s
  if(completed)report.value=completed
  if(!caseId.value){const wanted=new URLSearchParams(location.hash.split('?')[1]??'').get('case');caseId.value=wanted&&groups.value.includes(wanted)?wanted:groups.value[0]??''}
  error.value=''
 }catch(e){error.value=String(e)}
 finally{if(!disposed&&(!!error.value||!['completed','failed','cancelled'].includes(progress.value?.status??'')))timer=setTimeout(update,2000)}
}
watch(filteredCases,ids=>{if(!ids.includes(caseId.value)){const wanted=new URLSearchParams(location.hash.split('?')[1]??'').get('case');caseId.value=wanted&&ids.includes(wanted)?wanted:ids[0]??''}})
const badCaseIds=computed(()=>[...new Set(report.value?.results.filter(r=>report.value!.run.manifest.primary_evaluator_ids.includes(r.evaluator_id)&&['fail','error','review'].includes(r.outcome)).map(r=>r.case_id)??[])])
async function writeback(){
 if(!report.value||!sample.value||busy.value)return
 const source=sample.value
 try{
  await ElMessageBox.confirm('将本次运行中的用例快照写回原评测集草稿？如草稿已有同 ID 用例，将覆盖该用例。已发布版本及历史结果不变。','回写失败用例',{type:'warning',confirmButtonText:'确认回写',cancelButtonText:'取消'})
  busy.value=true
  const result=await request<{source_dataset_id:string}>(`/runs/${props.id}/cases/${encodeURIComponent(source.id)}/writeback`,'POST',{case:source})
  emit('navigate','datasets/'+result.source_dataset_id)
 }catch(e){if(e!=='cancel'&&e!=='close')error.value=String(e)}finally{busy.value=false}
}
watch(caseId,async id=>{const ticket=++traceRequest;trace.value=null;traceError.value='';traceLoading.value=!!id;if(!id)return;try{const t=await api.trace(props.id,id);if(ticket===traceRequest)trace.value=t}catch(e){if(ticket===traceRequest)traceError.value=String(e)}finally{if(ticket===traceRequest)traceLoading.value=false}})
async function runAction(action:'cancel'|'rerun'){if(busy.value)return;try{if(action==='cancel')await ElMessageBox.confirm(action==='cancel'?'取消当前评测任务？已产生的运行记录将保留。':'使用原版本快照创建一个新的评测任务？',action==='cancel'?'取消评测':'重新评测',{confirmButtonText:'确认',cancelButtonText:'返回'});busy.value=true;const r=await request<RunProgress>(`/runs/${props.id}/${action}`,'POST');if(action==='rerun'){rerunPreview.value=false;emit('navigate','tasks/'+r.run_id)}else{clearTimeout(timer);await update()}}catch(e){if(e!=='cancel'&&e!=='close')error.value=String(e)}finally{busy.value=false}}
onMounted(async()=>{await update();await nextTick();if(new URLSearchParams(location.hash.split('?')[1]??'').get('action')==='regression')document.getElementById('regression-action')?.scrollIntoView({block:'center'})});onUnmounted(()=>{disposed=true;clearTimeout(timer);traceRequest++})
</script>
<template>
 <div class="page-head"><div><button class="link" @click="emit('navigate',returnPage)">← {{'返回任务列表'}}</button><h1 class="page-title">{{'评测任务详情'}}</h1><p class="page-sub">{{id}}</p></div><div class="actions"><button v-if="progress&&['scheduled','pending','running'].includes(progress.status)" class="secondary" :disabled="busy" @click="runAction('cancel')">取消任务</button><button v-else-if="progress" class="primary" :disabled="busy" @click="rerunPreview=true">使用原配置重跑</button></div></div>
 <div v-if="error" class="notice error" role="alert">{{error}}</div>
 <div v-if="progress" class="grid metric-grid"><div class="card"><div class="metric-label">执行状态</div><h2>{{statusLabel(progress.status)}}</h2><p class="muted">{{progress.completed_cases}} / {{progress.total_cases}} 样本</p></div><div class="card"><div class="metric-label">智能体版本</div><h3>{{progress.target_name}}</h3><p class="muted">{{progress.target_version}}</p></div><div class="card"><div class="metric-label">评测集版本</div><h3>{{progress.dataset_name}}</h3><p class="muted">v{{progress.dataset_version}}</p></div><div class="card"><div class="metric-label">运行耗时</div><h2>{{progress.duration_seconds==null?'—':progress.duration_seconds.toFixed(1)+' 秒'}}</h2><p class="muted">队列位置：{{progress.queue_position??'—'}}</p></div></div>
 <div v-if="progress?.error" class="notice error"><b>执行异常</b><pre>{{progress.error}}</pre></div>
 <div v-if="progress&&!report&&progress.status!=='failed'" class="notice">{{progress.status==='scheduled'?'任务已预约，等待到期调度。':progress.status==='cancelled'?'任务已取消，未生成完整评测报告。':'任务正在处理，页面每 2 秒查询进度。已完成样本逐条显示，下方每 2 秒更新；最终结论在整批结束后生成。'}}</div>
 <RerunDialog v-if="rerunPreview" :id="id" @close="rerunPreview=false" @created="next=>{rerunPreview=false;emit('navigate','tasks/'+next)}" />
 <template v-if="evidence">
  <details class="card section-gap"><summary>本次任务配置与版本来源</summary><RunConfiguration :manifest="evidence.run.manifest"/><RunLineage :run-id="id"/></details>
  <div v-if="noEvidence" class="notice warn" role="status"><b>没有适用的评估检查，发布门禁未通过</b><p>这不代表智能体业务失败。请补充用例期望，或选择能评判这些样本的评估器。</p><a class="link" :href="'#datasets/'+evidence.run.manifest.dataset.dataset_id+'?version='+evidence.run.manifest.dataset.version">查看本次评测集版本并创建修改草稿 →</a></div>
  <div v-if="report" class="card"><div class="toolbar"><h2 class="section-title">评估结论</h2><span class="badge" :class="report.release_gate.outcome==='pass'?'success':'warn'">{{noEvidence?'无有效评判依据':statusLabel(report.release_gate.outcome)}}</span></div><div class="grid metric-grid"><div v-for="m in report.metrics.filter(m=>m.level==='overall'||m.level==='kind')" :key="m.key"><div class="metric-label">{{metricLabel(m.key)}}</div><div class="metric-value">{{score(m.score)}}<small class="muted"> / 100</small></div><span class="muted">通过 {{m.passed}} · 未通过 {{m.failed}} · 异常 {{m.errors}} · 不适用 {{m.not_applicable}}</span></div></div><p class="muted">统计单位为评估结果，非唯一样本数。缺失分数显示“—”。</p></div>
  <div class="report-layout case-report-layout">
   <aside class="card case-navigation">
    <h3>样本（{{groups.length}}）</h3>
    <select class="input" v-model="filter" aria-label="样本结果筛选">
     <option value="">全部样本</option>
     <option v-for="s in ['fail','error','review','pass','not_applicable']" :key="s" :value="s">含{{statusLabel(s)}}评估项</option>
    </select>
    <button v-for="id in filteredCases" :key="id" :class="['evaluator-choice',{selected:caseId===id}]" :aria-pressed="caseId===id" @click="caseId=id">
     <b>{{evidence.run.manifest.dataset.cases.find(c=>c.id===id)?.name??id}}</b>
     <span>{{id}}</span><span v-if="attentionCount(id)" class="case-attention">需处理 {{attentionCount(id)}} 项</span>
    </button>
    <p v-if="!filteredCases.length" class="empty">无匹配样本</p>
   </aside>
   <div v-if="sample"><div v-if="results.some(r=>r.outcome==='fail')" class="toolbar"><button class="secondary" :disabled="busy" @click="writeback">回写失败用例到草稿</button></div><CaseReport v-if="sample" :key="caseId" :sample="sample" :results="results" :primary-ids="evidence.run.manifest.primary_evaluator_ids" :trace="trace" :trace-error="traceError" :trace-loading="traceLoading" :complete="!!report" @analyze="emit('navigate','optimizer/'+id)"/></div>
   <section v-else class="card empty">暂无可展示的样本结果</section>
  </div>
 </template>
</template>
<style scoped>
.report-layout.case-report-layout{grid-template-columns:220px minmax(0,1fr)}
.case-navigation .case-attention{color:#b42318;font-weight:600}
@media(max-width:1280px){.report-layout.case-report-layout{grid-template-columns:180px minmax(0,1fr)}}
@media(max-width:768px){.report-layout.case-report-layout{grid-template-columns:1fr}.case-navigation{max-height:280px}}
</style>
