<script setup lang="ts">
import AgentGraph from './AgentGraph.vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, request, statusLabel, kindLabel, type EvaluationRun, type Overview, type DatasetSummary, type EvaluatorSummary, type Report } from './api'
import OverviewMetrics from './OverviewMetrics.vue'
import DatasetMerge from './DatasetMerge.vue'
import RerunDialog from './RerunDialog.vue'
import DatasetWorkspace from '../upstream/pages/DatasetWorkspace.vue'
import Evaluators from './Evaluators.vue'
import ModelSettings from './ModelSettings.vue'
import RunDetail from './RunDetail.vue'
import Comparisons from './Comparisons.vue'
import Analysis from './UpstreamAnalysis.vue'
import Stability from './Stability.vue'
import {evaluatorScenarios,recommendEvaluators,recommendationReason} from './evaluator-guidance'
const navigation = [
 { title: '系统', items: [['settings','配置']] },
 { title: '评测与资产', items: [['overview','评测总览'], ['datasets','评测集'], ['evaluators','评估器'], ['tasks','评测任务']] },
 { title: '分析与改进', items: [['experiments','A/B 实验'], ['optimizer','调优中心'], ['analysis','Skill 静态分析']] },
]
const datasetDirty=ref(false),evaluatorDirty=ref(false),settingsDirty=ref(false)
const rerunId=ref('')
const route = ref(location.hash.slice(1) || 'overview')
const page = computed(() => route.value.split('/')[0]==='results'?'tasks':route.value.split('/')[0])
const runId = computed(() => route.value.split('/')[1]?.split('?')[0] || '')
function go(value:string) { location.hash = value }
function updateRoute() {
 const next=location.hash.slice(1)||'overview'
 if((datasetDirty.value||evaluatorDirty.value||settingsDirty.value)&&next!==route.value&&!window.confirm('当前页面有未保存的修改，确定离开并放弃修改？')) {history.replaceState(null,'','#'+route.value);return}
 datasetDirty.value=false;evaluatorDirty.value=false;settingsDirty.value=false;route.value=next
}
const runs = ref<EvaluationRun[]>([]), overview = ref<Overview|null>(null)
const error = ref(''), online = ref<boolean|null>(null), loading = ref(false)
const query = ref(''), status = ref(''),outcomeFilter=ref(''),listLoading=ref(false)
const reportSummaries=ref<Record<string,Report>>({}),reportErrors=ref<Record<string,boolean>>({})
watch(page,(next,previous)=>{if(next!==previous&&['tasks','results'].includes(next)){void loadPage()}})
const visibleRuns=ref<EvaluationRun[]>([]),totalRuns=ref(0),pageNumber=ref(1),pageSize=ref(20)
let pageRequest=0
async function loadPage(){
 const ticket=++pageRequest;listLoading.value=true
 try{const records=await request<EvaluationRun[]>('/runs?limit=200'+(status.value?'&status='+encodeURIComponent(status.value):''));let filtered=records.filter(r=>JSON.stringify([r.id,r.manifest.target.display_name,r.manifest.dataset.dataset_name]).toLowerCase().includes(query.value.toLowerCase()));if(outcomeFilter.value){await loadSummaries(filtered,ticket);if(ticket!==pageRequest)return;filtered=filtered.filter(r=>reportSummaries.value[r.id]?.release_gate.outcome===outcomeFilter.value)}const result={items:filtered.slice((pageNumber.value-1)*pageSize.value,pageNumber.value*pageSize.value),total:filtered.length};if(ticket===pageRequest){visibleRuns.value=result.items;totalRuns.value=result.total;if(page.value==='tasks')void loadSummaries(result.items,ticket)}}
 catch(e){if(ticket===pageRequest)error.value=String(e)}finally{if(ticket===pageRequest)listLoading.value=false}
}
async function loadSummaries(rows:EvaluationRun[],ticket:number){
 for(let start=0;start<rows.length;start+=4){
  if(ticket!==pageRequest)return
  await Promise.all(rows.slice(start,start+4).filter(r=>r.status==='completed'&&!reportSummaries.value[r.id]).map(async r=>{try{const report=await api.report(r.id);if(ticket===pageRequest){reportSummaries.value[r.id]=report;reportErrors.value[r.id]=false}}catch{if(ticket===pageRequest)reportErrors.value[r.id]=true}}))
 }
}
function resultSummary(id:string){const report=reportSummaries.value[id];return report?.metrics.find(m=>m.level==='overall')}
watch([query,status,pageSize,outcomeFilter],()=>{pageNumber.value=1;void loadPage()})
watch(pageNumber,()=>void loadPage())
const actionRun = ref('')
async function runAction(id:string, action:'cancel'|'rerun') {
 if(action==='rerun'){rerunId.value=id;return}
 if(actionRun.value) return
 actionRun.value=id
 try {
  await ElMessageBox.confirm('取消当前任务？已产生的记录将保留。','取消任务',{confirmButtonText:'确认',cancelButtonText:'返回'})
  await request(`/runs/${encodeURIComponent(id)}/cancel`,'POST')
  await refresh()
  ElMessage.success('取消请求已提交')
 } catch(e) { if(e!=='cancel'&&e!=='close') ElMessage.error(String(e)) }
 finally { actionRun.value='' }
}
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
async function refresh() {
 if(loading.value) return
 loading.value=true
 try { const [o,r] = await Promise.all([api.overview(),api.runs()]); overview.value=o; runs.value=r; online.value=true; error.value='';await loadPage() }
 catch(e) { online.value=false; error.value=e instanceof Error?e.message:String(e) }
 finally { loading.value=false }
}
async function poll() { await refresh(); if(!disposed) timer=setTimeout(poll,5000) }
onMounted(() => { window.addEventListener('hashchange',updateRoute); void poll() })
onUnmounted(() => { disposed=true; clearTimeout(timer); window.removeEventListener('hashchange',updateRoute) })
const create = ref(false), submitting = ref(false), formLoading=ref(false), datasetLoading=ref(false)
let formSequence=0
watch(create,open=>{if(!open)formSequence++})
const datasets = ref<DatasetSummary[]>([]), evaluators = ref<EvaluatorSummary[]>([]), versions=ref<{id:string;label:string}[]>([])
const selectedDataset = ref(''), selectedVersion = ref(''), selectedEvaluators = ref<string[]>([])
const repetitions=ref(1),launchMode=ref('now'),scheduledAt=ref('')
const descriptors=ref<any[]>([])
const targetDescriptor=computed(()=>descriptors.value.find(d=>d.ref.external_version_id===selectedVersion.value))
const scope=ref('all'),selectedCaseIds=ref<string[]>([])
const availableCases=computed(()=>datasetVersions.value.find(v=>v.version===selectedDatasetVersion.value)?.cases??[])
const executionCases=computed(()=>scope.value==='selected'?availableCases.value.filter(c=>selectedCaseIds.value.includes(c.id)):availableCases.value)
watch(repetitions,v=>{if(v>1){launchMode.value='now';scheduledAt.value=''}})
const datasetVersions=ref<{version:number;cases:any[]}[]>([]),selectedDatasetVersion=ref<number|null>(null)
const concurrency = ref(2), timeout = ref(300), retries = ref(0), formError = ref('')
const runSource=ref<{id:string;version:number;caseIds?:string[];caseName?:string}|null>(null)
async function openCreate(source?:{id:string;version:number;caseIds?:string[];caseName?:string;targetVersion?:string;evaluatorId?:string}) {
 const ticket=++formSequence;formLoading.value=true
 runSource.value=source??null
 scope.value=source?.caseIds?'selected':'all';selectedCaseIds.value=source?.caseIds??[]
 repetitions.value=1;concurrency.value=2;timeout.value=300;retries.value=0;launchMode.value='now';scheduledAt.value=''
 formError.value=''; selectedDataset.value=''; create.value=true
 try { const [d,e,v]=await Promise.all([api.datasets(),api.evaluators(),api.versions()]); if(ticket!==formSequence)return;descriptors.value=[];datasets.value=d.filter(x=>x.version!==null&&!x.archived); evaluators.value=e.filter(x=>x.enabled&&x.latest_version); versions.value=v; selectedDataset.value=source?.id||datasets.value[0]?.id||''; selectedVersion.value=source?.targetVersion&&v.some(x=>x.id===source.targetVersion)?source.targetVersion:(v[0]?.id??''); selectedEvaluators.value=source?.evaluatorId?[source.evaluatorId]:evaluators.value.filter(x=>x.kind==='rule').map(x=>x.id) }
 catch(e) { if(ticket===formSequence)formError.value=String(e) }
 finally {if(ticket===formSequence)formLoading.value=false}
}
const recommended=ref<string[]>([]),recommendationError=ref('')
let recommendationSequence=0
watch(selectedDataset,async id=>{
 const ticket=++recommendationSequence;recommended.value=[];recommendationError.value='';datasetVersions.value=[];selectedDatasetVersion.value=null
 datasetLoading.value=Boolean(id)
 if(!id)return
 try{const d=await request<{versions:{version:number|null;cases:{turns:{expectations:{kind:string;mode?:string}[]}[]}[]}[]}>(`/datasets/${encodeURIComponent(id)}`);if(ticket!==recommendationSequence)return;datasetVersions.value=d.versions.filter(v=>v.version!==null) as {version:number;cases:any[]}[];selectedDatasetVersion.value=runSource.value?.id===id?runSource.value.version:datasets.value.find(d=>d.id===id)?.version??null}catch{if(ticket===recommendationSequence)recommendationError.value='未能读取样本期望，请按使用场景手动选择。'}finally{if(ticket===recommendationSequence)datasetLoading.value=false}
},{flush:'sync'})
watch(availableCases,cases=>{selectedCaseIds.value=selectedCaseIds.value.filter(id=>cases.some(c=>c.id===id))})
watch([executionCases,evaluators],()=>{recommended.value=recommendEvaluators(evaluators.value,executionCases.value)})
async function submit() {
 if(submitting.value||formLoading.value||datasetLoading.value) return
 for(const [label,value,min,max] of [
  ['稳定性测试重复次数',repetitions.value,1,20],
  ['并发样本数',concurrency.value,1,32],
  ['执行超时（秒）',timeout.value,1,3600],
  ['失败重试次数',retries.value,0,5],
 ] as [string,number,number,number][]){
  if(!Number.isInteger(value)||value<min||value>max){formError.value=`${label}必须为 ${min}—${max} 的整数`;return}
 }
 if(launchMode.value==='scheduled'&&(repetitions.value!==1||!scheduledAt.value||!Number.isFinite(new Date(scheduledAt.value).getTime())||new Date(scheduledAt.value).getTime()<=Date.now())){formError.value='预约时间必须晚于当前时间，且只支持单次普通评测。';return}
 const dataset=datasets.value.find(d=>d.id===selectedDataset.value)
 if(!dataset || selectedDatasetVersion.value===null || !selectedVersion.value || !selectedEvaluators.value.length) { formError.value='请选择已发布评测集、智能体版本和至少一个评估器。';return }
 submitting.value=true;formError.value=''
 try {
 const exact=await request<{cases:any[]}>(`/datasets/${dataset.id}/versions/${selectedDatasetVersion.value}`)
 const caseIds=scope.value==='selected'?selectedCaseIds.value:undefined
 if(!exact.cases.length||caseIds?.length===0)throw Error('请选择至少一条用例。')
 if(caseIds){exact.cases=exact.cases.filter(c=>caseIds.includes(c.id));if(exact.cases.length!==caseIds.length)throw Error('所选用例不在当前发布版本中。')}
 const chosen=evaluators.value.filter(e=>selectedEvaluators.value.includes(e.id))
 if(chosen.every(e=>e.kind==='rule')&&!recommendEvaluators(chosen,exact.cases).length)throw Error('所选评估器与样本期望没有适用检查。请补充期望或调整评估器。')
 const uncovered=exact.cases.filter(c=>chosen.every(e=>e.kind==='rule')&&!recommendEvaluators(chosen,[c]).length)
 if(uncovered.length)await ElMessageBox.confirm(`${uncovered.length} 条用例没有匹配检查，将标为不适用。是否继续？`,'检查覆盖范围',{confirmButtonText:'继续评测',cancelButtonText:'返回修改'})
 const r=await request<{run_id?:string;id?:string}>('/evaluations','POST',{version:selectedVersion.value,dataset_id:dataset.id,dataset_version:selectedDatasetVersion.value,evaluator_ids:selectedEvaluators.value,max_parallel_cases:concurrency.value,timeout_seconds:timeout.value,max_retries:retries.value,...(caseIds?{case_ids:caseIds}:{}),...(repetitions.value>1?{repetitions:repetitions.value}:{}),...(launchMode.value==='scheduled'?{scheduled_for:new Date(scheduledAt.value).toISOString()}:{})});create.value=false;go('tasks/'+r.run_id);await refresh();ElMessage.success('评测任务已提交') }
 catch(e) { if(e!=='cancel'&&e!=='close')formError.value=String(e) } finally { submitting.value=false }
}
</script>
<template>
 <div class="app revision-app">
  <header class="topbar"><div class="brand">智能体评测中心 <small>评测工作台</small></div><span class="muted">当前目标：内置 Demo · 非本地 DeepAgent</span><span class="badge" :class="online?'success':'warn'">{{online===null?'正在连接服务…':online?'UX 后端已连接':'服务未连接'}}</span></header>
  <div class="shell"><aside class="sidebar"><template v-for="group in navigation" :key="group.title"><div class="nav-group">{{group.title}}</div><a v-for="item in group.items" :key="item[0]" :href="'#'+item[0]" class="nav-item" :class="{active:page===item[0]||(page==='stability'&&item[0]==='tasks')}">{{item[1]}}</a></template><div class="sidebar-foot">主仓联调副本 · 2026.09.14<br>Demo 目标 · 真实评测执行</div></aside>
   <main class="content">
    <div v-if="error" class="notice error" role="alert">服务连接失败：{{error}} <button class="link" @click="refresh">重试</button>。不使用模拟数据替代。</div>
    <template v-if="page==='overview'">
     <div class="page-head"><div><h1 class="page-title">评测总览</h1><p class="page-sub">运行状态、评测资产与最近结果</p></div><span class="muted">{{loading?'正在刷新':'最近任务每 5 秒刷新'}}</span></div>
     <OverviewMetrics />
     <div class="card"><div class="toolbar"><h2 class="section-title">最近评测任务</h2><a href="#tasks" class="link">查看全部 →</a></div><table class="data-table"><thead><tr><th>智能体 / 版本</th><th>评测集</th><th>执行状态</th><th>操作</th></tr></thead><tbody><tr v-for="r in runs.slice(0,6)" :key="r.id"><td>{{r.manifest.target.display_name}}<div class="muted">{{r.manifest.target.ref.external_version_id}}</div></td><td>{{r.manifest.dataset.dataset_name}}</td><td>{{statusLabel(r.status)}}</td><td><button class="link" @click="go('tasks/'+r.id)">查看</button></td></tr></tbody></table><p v-if="!runs.length" class="empty">尚无评测任务，请从“评测任务”发起。</p></div>
    </template>
    <ModelSettings v-else-if="page==='settings'" @dirty-change="settingsDirty=$event" />
    <DatasetWorkspace v-else-if="page==='datasets'" :key="route" :initial-id="runId" @dirty-change="datasetDirty=$event" @run-version="openCreate($event)" />
    <section v-else-if="page==='dataset-merge'" class="card">多 Skill 合并需求已挂起，当前不提供创建入口。<a href="#datasets">返回评测集</a></section>
    <Evaluators v-else-if="page==='evaluators'" :key="route" :initial-id="runId" @dirty-change="evaluatorDirty=$event" @launch="openCreate({id:'',version:0,evaluatorId:$event})" />
    <template v-else-if="page==='tasks'||page==='results'">
     <RunDetail v-if="runId" :key="route" :id="runId" :return-page="page" @navigate="go" />
     <template v-else><div class="page-head"><div><h1 class="page-title">{{page==='tasks'?'评测任务':'结果中心'}}</h1><p class="page-sub">{{page==='tasks'?'统一查看执行进度、评估结论与样本报告':'查看结论与问题样本，进入分析或回归验证'}}</p></div><div v-if="page==='tasks'" class="actions"><button class="primary" @click="openCreate()">发起评测</button></div></div>
      <section class="card" :class="{'task-list-card':page==='tasks'}"><div v-if="page==='tasks'" class="tabs task-status-tabs" aria-label="任务状态筛选"><button v-for="s in ['','scheduled','pending','running','completed','failed','cancelled']" :key="s" :class="['tab',{active:status===s}]" :aria-pressed="status===s" @click="status=s">{{s?statusLabel(s):'全部'}}</button></div><div class="toolbar task-filterbar"><input class="search" v-model="query" placeholder="搜索智能体或任务 ID" aria-label="搜索任务"/><select v-if="page==='tasks'" class="input outcome-filter" aria-label="评估结论筛选" v-model="outcomeFilter"><option value="">全部评估结论</option><option value="pass">通过</option><option value="fail">未通过</option><option value="review">待复核</option></select><span v-if="page==='tasks'" class="muted">{{listLoading?'加载中…':''}}共 {{totalRuns}} 条匹配记录</span><select v-else class="input" v-model="status" aria-label="执行状态"><option value="">全部执行状态</option><option v-for="s in ['scheduled','pending','running','completed','failed','cancelled']" :value="s">{{statusLabel(s)}}</option></select></div><div class="table-wrap"><table class="data-table"><thead><tr><th>任务 / 智能体</th><th>评测集版本</th><th v-if="page==='tasks'">评估器</th><th>执行状态</th><th>评估结论 / 得分</th><th>创建 / 预约时间</th><th>操作</th></tr></thead><tbody><tr v-for="r in visibleRuns" :key="r.id"><td><button v-if="page==='tasks'" class="link task-title" @click="go('tasks/'+r.id)">{{r.manifest.target.display_name}}</button><span v-else>{{r.manifest.target.display_name}}</span><div v-if="page==='tasks'" class="muted task-meta">{{r.manifest.target.ref.external_version_id}}</div><div class="muted task-id" :title="r.id">{{r.id}}</div></td><td>{{r.manifest.dataset.dataset_name}} · v{{r.manifest.dataset.version}}</td><td v-if="page==='tasks'"><span class="tag">{{r.manifest.primary_evaluator_ids.length}} 个</span><small class="task-meta muted">固定运行配置</small></td><td><span class="badge" :class="r.status==='failed'?'error':r.status==='completed'?'success':'info'">{{statusLabel(r.status)}}</span></td><td><template v-if="reportSummaries[r.id]"><b>{{reportSummaries[r.id].release_gate.reason_code==='no_applicable_results'?'无有效评判依据':statusLabel(reportSummaries[r.id].release_gate.outcome)}}</b><p>{{resultSummary(r.id)?.score==null?'—':(resultSummary(r.id)!.score!*100).toFixed(1)}} / 100</p></template><span v-else>{{r.status==='completed'?(reportErrors[r.id]?'报告读取失败，请查看详情':'读取报告中…'):'—'}}</span></td><td>{{new Date(r.created_at).toLocaleString()}}<small v-if="r.scheduled_for" class="muted">预约 {{new Date(r.scheduled_for).toLocaleString()}}</small></td><td class="task-row-actions"><button class="link" @click="go(page+'/'+r.id)">查看{{page==='results'?'报告':'详情'}}</button><button v-if="page==='tasks'" class="link" :disabled="!!actionRun" @click="runAction(r.id, ['scheduled','pending','running'].includes(r.status)?'cancel':'rerun')">{{actionRun===r.id?'处理中…':(['scheduled','pending','running'].includes(r.status)?'取消':'重跑')}}</button></td></tr></tbody></table></div><p v-if="!visibleRuns.length" class="empty">暂无符合条件的任务</p><p class="muted">最近最多 200 条中匹配 {{totalRuns}} 条 · 第 {{pageNumber}} / {{Math.max(1,Math.ceil(totalRuns/pageSize))}} 页</p><div class="toolbar"><button class="secondary" :disabled="pageNumber<=1" @click="pageNumber--">上一页</button><select class="input" v-model.number="pageSize" aria-label="每页条数"><option :value="20">20 条/页</option><option :value="50">50 条/页</option><option :value="100">100 条/页</option></select><button class="secondary" :disabled="pageNumber*pageSize>=totalRuns" @click="pageNumber++">下一页</button></div></section>
     </template>
    </template>
    <section v-else-if="page==='stability'" class="card">主仓暂无稳定性重复运行接口，请先使用普通评测。</section>
    <Comparisons v-else-if="page==='experiments'" />
    <Analysis v-else-if="page==='optimizer'||page==='analysis'" :key="route" :mode="page" :initial-id="runId" :runs="runs" />
    <div v-else class="card empty">页面不存在。<a href="#overview">返回总览</a></div>
   </main>
  </div>
  <RerunDialog v-if="rerunId" :id="rerunId" @close="rerunId=''" @created="id=>{rerunId='';go('tasks/'+id)}" />
  <el-dialog v-model="create" title="新建评测任务" width="min(1080px, 96vw)" class="task-create-dialog" top="3vh" :close-on-click-modal="false">

   <p v-if="formLoading||datasetLoading" role="status">正在加载任务配置…</p>
   <div v-if="formError" class="notice error" role="alert">{{formError}}</div>
   
   <p class="task-intro">选择评测对象、样本及评估器，再设置执行参数。提交后将在评测任务中查看进度和结果。</p>
   <div class="form-grid task-create-grid">
    <div class="form-section-heading full"><span>01</span><div><h3>评测对象</h3><p>明确本次运行使用的智能体与固定版本</p></div></div>
    <label class="field">智能体<select class="input" aria-label="智能体"><option value="loan-agent">贷款审批演示智能体（内置 Demo）</option></select><small>当前仅接入这一智能体，非本地 DeepAgent。</small></label>
    <label class="field">智能体版本<select class="input" v-model="selectedVersion"><option v-for="v in versions" :key="v.id" :value="v.id">{{v.id==='loan-agent-v1-risky'?'旧方案 v1（风险版本）':v.id==='loan-agent-v2-fixed'?'修正方案 v2':v.label}} · {{v.id}}</option></select></label>
    <AgentGraph :version="selectedVersion" />
    <div class="form-section-heading full"><span>02</span><div><h3>评测数据</h3><p>选择已发布版本及本次运行的样本范围</p></div></div>
    <label class="field">评测集<select class="input" v-model="selectedDataset"  aria-label="任务评测集"><option v-for="d in datasets" :value="d.id">{{d.name}}</option></select></label>
    <label class="field">评测集版本<select class="input" v-model="selectedDatasetVersion"  aria-label="任务评测集版本"><option v-for="v in datasetVersions" :value="v.version">v{{v.version}} · {{v.cases.length}} 条样本</option></select></label>
    <label class="field full">运行范围<select class="input" aria-label="运行范围" v-model="scope"><option value="all">全部用例（{{availableCases.length}} 条）</option><option value="selected">指定用例</option></select><el-select v-if="scope==='selected'" v-model="selectedCaseIds" multiple filterable placeholder="选择要运行的用例" aria-label="指定用例"><el-option v-for="c in availableCases" :key="c.id" :label="c.name" :value="c.id"/></el-select><small v-if="scope==='selected'&&!selectedCaseIds.length">请从当前发布版本重新选择用例。</small></label>
    <div class="form-section-heading full"><span>03</span><div><h3>评估方式</h3><p>多个评估器使用同一批执行结果进行判定</p></div></div>
    <div class="field full"><label>评估器 · 已选 {{selectedEvaluators.length}} 个</label><div class="actions" style="display:flex;flex-wrap:wrap"><button class="secondary" style="width:auto" type="button" :disabled="!recommended.length" @click="selectedEvaluators=[...recommended]">推荐评估器</button><button class="secondary" style="width:auto" @click="selectedEvaluators=evaluators.map(e=>e.id)">全选可用项</button><button class="secondary" style="width:auto" @click="selectedEvaluators=[]">清空选择</button></div><small>按样本期望匹配；点击后替换当前勾选。数量按评估器记录计算。</small><small v-if="recommendationError">{{recommendationError}}</small><div class="check-list"><label v-for="e in evaluators" :key="e.id"><input type="checkbox" :value="e.id" v-model="selectedEvaluators"/>{{e.name}} <span class="muted">{{kindLabel(e.kind)}} · v{{e.latest_version}}<small style="display:block">{{evaluatorScenarios[e.implementation_id]??e.description}}</small><small v-if="recommended.includes(e.id)" class="block">推荐理由：{{recommendationReason(e,executionCases)}}</small></span></label></div></div>
    <div class="form-section-heading full"><span>04</span><div><h3>执行设置</h3><p>执行时间、并发及异常处理</p></div></div>
    <label class="field">执行时间<select aria-label="执行时间" class="input" v-model="launchMode" :disabled="repetitions>1"><option value="now">立即执行</option><option value="scheduled">预约执行</option></select><small v-if="repetitions>1">稳定性测试暂不支持预约。</small></label>
    <label v-if="launchMode==='scheduled'" class="field">预约时间<input aria-label="预约时间" class="input" type="datetime-local" v-model="scheduledAt"/><small>本机时区 {{Intl.DateTimeFormat().resolvedOptions().timeZone}}；到期由调度服务进入队列。</small></label>
    <label class="field">并发样本数<input class="input" v-model.number="concurrency" type="number" min="1" max="32"/><small>同时执行的用例上限，不增加样本数量。例如 3 条用例、并发 2，最多同时执行 2 条。</small></label>
    <label class="field">执行超时（秒）<input class="input" v-model.number="timeout" type="number" min="1" max="3600"/><small>单次目标执行的等待时限，不是整个评测集的总时长；超时处理取决于目标适配器。</small></label>
    <label class="field">稳定性测试 · 执行次数<input class="input" type="number" :value="1" disabled aria-label="稳定性测试执行次数"/><small>同一配置独立重复运行，用于观察结果波动，不等同于失败重试。旧版扩展支持 2–20 次；当前主仓未接入该接口，暂固定为 1 次。</small></label>
    <label class="field">失败重试次数<input class="input" v-model.number="retries" type="number" min="0" max="5"/><small>仅对后端认可的可重试执行错误额外尝试。0 表示不重试；2 表示最多首次执行加 2 次重试。评分不通过不会触发重试。</small></label>
   </div>
   <p class="task-summary">本次：{{versions.find(v=>v.id===selectedVersion)?.label??'待选目标'}} · v{{selectedDatasetVersion??'—'}} · {{executionCases.length}} 条用例 × {{repetitions}} 次 · {{selectedEvaluators.length}} 个评估器</p>
   <template #footer><button class="secondary" @click="create=false">取消</button><button class="primary" :disabled="submitting||formLoading||datasetLoading||!online" @click="submit">{{submitting?'正在提交…':'开始评测'}}</button></template>
  </el-dialog>
 </div>
</template>

<style>
.task-create-dialog .el-dialog__header{padding:20px 28px;border-bottom:1px solid #e5eaf0;margin:0}
.task-create-dialog .el-dialog__body{padding:20px 32px;max-height:76vh;overflow:auto}
.task-create-dialog .el-dialog__footer{border-top:1px solid #e5eaf0;padding:16px 28px}
.task-create-dialog .el-dialog__footer button+button{margin-left:12px}
.task-intro{color:#64748b;margin:0 0 24px;font-size:14px}
.task-create-grid{gap:22px 28px}
.task-create-grid .full{grid-column:1 / -1}
.form-section-heading{display:flex;gap:12px;align-items:center;padding-top:24px;border-top:1px solid #e8edf1;margin-top:4px}
.form-section-heading:first-child{border-top:0;padding-top:0}
.form-section-heading>span{background:#e3f5f0;color:#00826e;border-radius:8px;padding:10px;font-weight:700}
.form-section-heading h3{font-size:17px;margin:0 0 4px}
.form-section-heading p{color:#64748b;font-size:13px;margin:0}
.task-create-dialog .check-list{gap:12px;margin-top:16px}
.task-create-dialog .check-list>label{padding:14px;align-items:flex-start;background:#fafcfb;border:1px solid #e2e9e6;border-radius:8px;font-size:14px}
.task-create-dialog .task-summary{padding:16px;background:#f4f8f7;border-radius:8px;font-size:14px;margin:24px 0 0}
.task-list-card .task-status-tabs{margin:-4px 0 20px;overflow-x:auto;white-space:nowrap}
.task-filterbar{justify-content:flex-start;gap:20px;margin-bottom:20px}
.task-filterbar .outcome-filter{width:170px;flex:none}
.task-filterbar .search{max-width:420px;flex:1}
.task-list-card table{min-width:1120px}
.task-list-card .badge,.task-list-card .tag{white-space:nowrap}
.task-list-card td:nth-child(3){min-width:82px}
.task-list-card td:nth-child(4){min-width:88px}
.task-list-card td:nth-child(5){min-width:110px}
.task-list-card th{background:#f6f8fa;white-space:nowrap}
.task-list-card td{padding-top:20px;padding-bottom:20px;vertical-align:middle}
.task-title{font-weight:600;text-align:left}
.task-meta{display:block;font-size:12px;margin-top:7px}
.task-id{font-size:12px;max-width:245px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:5px}
.task-row-actions{white-space:nowrap}
.task-row-actions button+button{margin-left:16px}
.task-list-card>.toolbar:last-child{justify-content:flex-end;gap:12px}
.task-list-card>.toolbar:last-child select{width:130px}
@media(max-width:700px){.task-create-dialog .el-dialog__body{padding:16px}.task-create-grid{grid-template-columns:1fr}.task-filterbar{flex-wrap:wrap}}
</style>
