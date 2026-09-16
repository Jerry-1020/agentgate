<script setup lang="ts">
import TaskStaticAnalysis from './TaskStaticAnalysis.vue'
import TaskTuning from './TaskTuning.vue'
import EvaluationTaskForm from './EvaluationTaskForm.vue'
import {readTaskLinks,type TaskLink} from './task-links'
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
]
const datasetDirty=ref(false),evaluatorDirty=ref(false),settingsDirty=ref(false)
const rerunId=ref('')
const route = ref(location.hash.slice(1) || 'overview')
const page = computed(() => ['results','experiments','optimizer'].includes(route.value.split('/')[0])?'tasks':route.value.split('/')[0])
const taskDetailTab=ref('results')
watch(route,value=>taskDetailTab.value=value.startsWith('optimizer/')||new URLSearchParams(value.split('?')[1]??'').get('tab')==='analysis'?'analysis':'results',{immediate:true})
function pairRows(id:string){return (linkFor(id)?.runIds??[id]).map((runId,index)=>{const run=runs.value.find(r=>r.id===runId);return {id:runId,side:index===0?'A':'B',name:run?.manifest.target.display_name??'运行记录待加载',version:run?.manifest.target.ref.external_version_id??'—'}})}
const taskType=ref(''),datasetFilter=ref(''),evaluatorFilter=ref(''),timeOrder=ref('newest')
const taskLinks=ref(readTaskLinks()),detailDialog=ref('')
function syncTaskLinks(){taskLinks.value=readTaskLinks();void loadPage()}
const currentLink=computed(()=>taskLinks.value.find(t=>t.runIds.includes(runId.value)))
const pairLink=computed(()=>currentLink.value?.kind==='ab'?currentLink.value:null)
function linkFor(id:string){return taskLinks.value.find(t=>t.runIds.includes(id))}
function groupStatus(run:EvaluationRun,records=runs.value){
 const link=linkFor(run.id);if(link?.kind!=='ab')return run.status
 const states=link.runIds.map(id=>records.find(r=>r.id===id)?.status)
 if(states.includes('failed'))return 'failed'
 if(states.includes('cancelled'))return 'cancelled'
 if(states.every(s=>s==='completed'))return 'completed'
 return states.includes('running')||states.includes('completed')?'running':'pending'
}
const datasetOptions=computed(()=>[...new Map(runs.value.map(r=>[r.manifest.dataset.dataset_id,r.manifest.dataset.dataset_name])).entries()])
const evaluatorOptions=computed(()=>[...new Set(runs.value.flatMap(r=>r.manifest.primary_evaluator_ids))])
const runId = computed(() => route.value.split('/')[1]?.split('?')[0] || '')
function go(value:string) { location.hash = value }
function updateRoute() {
 const next=location.hash.slice(1)||'overview'
 if((datasetDirty.value||evaluatorDirty.value||settingsDirty.value)&&next!==route.value&&!window.confirm('当前页面有未保存的修改，确定离开并放弃修改？')) {history.replaceState(null,'','#'+route.value);return}
 datasetDirty.value=false;evaluatorDirty.value=false;settingsDirty.value=false;route.value=next
}
const runs = ref<EvaluationRun[]>([]), overview = ref<Overview|null>(null)
const error = ref(''), online = ref<boolean|null>(null), loading = ref(false)
const query = ref(''), status = ref(''),listLoading=ref(false)
const reportSummaries=ref<Record<string,Report>>({}),reportErrors=ref<Record<string,boolean>>({})
watch(page,(next,previous)=>{if(next!==previous&&['tasks','results'].includes(next)){void loadPage()}})
const visibleRuns=ref<EvaluationRun[]>([]),totalRuns=ref(0),pageNumber=ref(1),pageSize=ref(20)
let pageRequest=0
async function loadPage(){
 const ticket=++pageRequest;listLoading.value=true
 try{const records=await request<EvaluationRun[]>('/runs?limit=200');let filtered=records;filtered=filtered.filter(r=>{
 const link=linkFor(r.id)
 if(link?.kind==='ab'&&link.runIds[0]!==r.id)return false
 return (link?.runIds??[r.id]).some(id=>{const item=records.find(x=>x.id===id);return JSON.stringify([id,item?.manifest.target.display_name,item?.manifest.target.ref.external_version_id,item?.manifest.dataset.dataset_name]).toLowerCase().includes(query.value.toLowerCase())})&&(!taskType.value||(link?.kind??'single')===taskType.value)&&(!status.value||groupStatus(r,records)===status.value)&&(!datasetFilter.value||r.manifest.dataset.dataset_id===datasetFilter.value)&&(!evaluatorFilter.value||r.manifest.primary_evaluator_ids.includes(evaluatorFilter.value))
 });if(timeOrder.value==='oldest')filtered.reverse();const result={items:filtered.slice((pageNumber.value-1)*pageSize.value,pageNumber.value*pageSize.value),total:filtered.length};if(ticket===pageRequest){visibleRuns.value=result.items;totalRuns.value=result.total;if(page.value==='tasks')void loadSummaries(records.filter(r=>result.items.some(item=>item.id===r.id||linkFor(item.id)?.runIds.includes(r.id))),ticket)}}
 catch(e){if(ticket===pageRequest)error.value=String(e)}finally{if(ticket===pageRequest)listLoading.value=false}
}
async function loadSummaries(rows:EvaluationRun[],ticket:number){
 for(let start=0;start<rows.length;start+=4){
  if(ticket!==pageRequest)return
  await Promise.all(rows.slice(start,start+4).filter(r=>r.status==='completed'&&!reportSummaries.value[r.id]).map(async r=>{try{const report=await api.report(r.id);if(ticket===pageRequest){reportSummaries.value[r.id]=report;reportErrors.value[r.id]=false}}catch{if(ticket===pageRequest)reportErrors.value[r.id]=true}}))
 }
}
function resultSummary(id:string){const report=reportSummaries.value[id];return report?.metrics.find(m=>m.level==='overall')}
watch([query,status,pageSize,taskType,datasetFilter,evaluatorFilter,timeOrder],()=>{pageNumber.value=1;void loadPage()})
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
onMounted(() => { window.addEventListener('hashchange',updateRoute);window.addEventListener('task-links-updated',syncTaskLinks); void poll() })
onUnmounted(() => { disposed=true; clearTimeout(timer); window.removeEventListener('hashchange',updateRoute);window.removeEventListener('task-links-updated',syncTaskLinks) })
const create=ref(false)
const formSource=ref<{id:string;version:number;caseIds?:string[];caseName?:string;targetVersion?:string;evaluatorId?:string}>()
function openCreate(source?:typeof formSource.value){formSource.value=source;create.value=true}
async function taskCreated(link:TaskLink){create.value=false;taskLinks.value=readTaskLinks();go('tasks/'+link.id);await refresh()}
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
     <template v-if="runId">
      <section v-if="pairLink" class="card task-linked-summary">
       <a href="#tasks" class="link">← 返回评测任务</a><h3>A/B 实验</h3>
       <template v-if="pairLink"><p>两侧使用相同评测集与评估器版本。</p><div class="actions"><button v-for="(id,index) in pairLink.runIds" :key="id" @click="detailDialog=id" class="link">实验 {{index===0?'A':'B'}} · {{statusLabel(runs.find(r=>r.id===id)?.status??'pending')}}</button></div></template>
      </section>
      <div v-if="pairLink" class="tabs" aria-label="实验详情内容"><button :class="['tab',{active:taskDetailTab==='results'}]" @click="taskDetailTab='results'">实验对比</button><button :class="['tab',{active:taskDetailTab==='analysis'}]" @click="taskDetailTab='analysis'">调优分析</button><button :class="['tab',{active:taskDetailTab==='static'}]" @click="taskDetailTab='static'">Skill 静态分析</button></div>
      <TaskStaticAnalysis v-if="pairLink&&taskDetailTab==='static'" :run-ids="pairLink.runIds"/>
      <TaskTuning v-if="pairLink&&taskDetailTab==='analysis'" :key="pairLink.id" :run-ids="pairLink.runIds"/>
      <Comparisons v-if="pairLink&&taskDetailTab==='results'" :key="pairLink.id" :initial-pair="{a:pairLink.runIds[0],b:pairLink.runIds[1]}" embedded/>
      <RunDetail v-if="!pairLink" :key="route" :id="runId" :return-page="page" @navigate="go" /></template>
     <template v-else><div class="page-head"><div><h1 class="page-title">{{page==='tasks'?'评测任务':'结果中心'}}</h1><p class="page-sub">{{page==='tasks'?'统一查看执行进度、评估结论与样本报告':'查看结论与问题样本，进入分析或回归验证'}}</p></div><div v-if="page==='tasks'" class="actions"><button class="primary" @click="openCreate()">发起评测</button></div></div>
      <section class="card" :class="{'task-list-card':page==='tasks'}"><div v-if="page==='tasks'" class="tabs task-status-tabs" aria-label="任务类型筛选"><button v-for="s in ['','single','ab']" :key="s" :class="['tab',{active:taskType===s}]" :aria-pressed="taskType===s" @click="taskType=s">{{s==='single'?'单任务':s==='ab'?'A/B 实验':'全部'}}</button></div><div class="toolbar task-filterbar"><input class="search" v-model="query" placeholder="搜索智能体或任务 ID" aria-label="搜索任务"/><span v-if="page==='tasks'" class="muted">{{listLoading?'加载中…':''}}共 {{totalRuns}} 条匹配记录</span><select v-else class="input" v-model="status" aria-label="执行状态"><option value="">全部执行状态</option><option v-for="s in ['scheduled','pending','running','completed','failed','cancelled']" :value="s">{{statusLabel(s)}}</option></select></div><div class="table-wrap"><table class="data-table"><thead><tr><th>任务 / 智能体</th><th><select v-model="datasetFilter" aria-label="筛选评测集"><option value="">全部评测集</option><option v-for="[id,name] in datasetOptions" :value="id">{{name}}</option></select></th><th><select v-model="evaluatorFilter" aria-label="筛选评估器"><option value="">全部评估器</option><option v-for="id in evaluatorOptions" :value="id">{{id}}</option></select></th><th><select v-model="status" aria-label="执行状态筛选"><option value="">全部执行状态</option><option v-for="s in ['scheduled','pending','running','completed','failed','cancelled']" :value="s">{{statusLabel(s)}}</option></select></th><th>评估结论 / 得分</th><th><select v-model="timeOrder" aria-label="创建时间排序"><option value="newest">创建时间 · 最新优先</option><option value="oldest">创建时间 · 最早优先</option></select></th><th>操作</th></tr></thead><tbody><tr v-for="r in visibleRuns" :key="r.id"><td class="task-identity"><template v-if="linkFor(r.id)?.kind==='ab'"><button class="link task-title" @click="go('tasks/'+r.id)">A/B 实验 · 双版本对比</button><div class="ab-identities"><div v-for="side in pairRows(r.id)" :key="side.id" class="ab-identity"><span class="ab-side">{{side.side}}</span><div><b>{{side.name}}</b><span>{{side.version}}</span><small :title="side.id">运行 ID：{{side.id.slice(0,8)}}…</small></div></div></div></template><template v-else><button class="link task-title" @click="go('tasks/'+r.id)">{{r.manifest.target.display_name}}</button><div class="muted task-meta">{{r.manifest.target.ref.external_version_id}}</div><div class="muted task-id" :title="r.id">{{r.id}}</div></template></td><td>{{r.manifest.dataset.dataset_name}} · v{{r.manifest.dataset.version}}</td><td v-if="page==='tasks'"><span class="tag">{{r.manifest.primary_evaluator_ids.length}} 个</span><small class="task-meta muted">固定运行配置</small></td><td><span class="badge" :class="groupStatus(r)==='failed'?'error':groupStatus(r)==='completed'?'success':'info'">{{statusLabel(groupStatus(r))}}</span></td><td><template v-if="linkFor(r.id)?.kind==='ab'"><p v-for="(id,index) in linkFor(r.id)!.runIds" :key="id">{{index===0?'A':'B'}}：{{reportSummaries[id]?statusLabel(reportSummaries[id].release_gate.outcome):statusLabel(runs.find(x=>x.id===id)?.status??'pending')}}</p></template><template v-else-if="reportSummaries[r.id]"><b>{{reportSummaries[r.id].release_gate.reason_code==='no_applicable_results'?'无有效评判依据':statusLabel(reportSummaries[r.id].release_gate.outcome)}}</b><p>{{resultSummary(r.id)?.score==null?'—':(resultSummary(r.id)!.score!*100).toFixed(1)}} / 100</p></template><span v-else>{{r.status==='completed'?(reportErrors[r.id]?'报告读取失败，请查看详情':'读取报告中…'):'—'}}</span></td><td>{{new Date(r.created_at).toLocaleString()}}<small v-if="r.scheduled_for" class="muted">预约 {{new Date(r.scheduled_for).toLocaleString()}}</small></td><td class="task-row-actions"><button class="link" @click="go(page+'/'+r.id)">查看{{page==='results'?'报告':'详情'}}</button><button v-if="page==='tasks'&&linkFor(r.id)?.kind!=='ab'" class="link" :disabled="!!actionRun" @click="runAction(r.id, ['scheduled','pending','running'].includes(r.status)?'cancel':'rerun')">{{actionRun===r.id?'处理中…':(['scheduled','pending','running'].includes(r.status)?'取消':'重跑')}}</button></td></tr></tbody></table></div><p v-if="!visibleRuns.length" class="empty">暂无符合条件的任务</p><p class="muted">最近最多 200 条中匹配 {{totalRuns}} 条 · 第 {{pageNumber}} / {{Math.max(1,Math.ceil(totalRuns/pageSize))}} 页</p><div class="toolbar"><button class="secondary" :disabled="pageNumber<=1" @click="pageNumber--">上一页</button><select class="input" v-model.number="pageSize" aria-label="每页条数"><option :value="20">20 条/页</option><option :value="50">50 条/页</option><option :value="100">100 条/页</option></select><button class="secondary" :disabled="pageNumber*pageSize>=totalRuns" @click="pageNumber++">下一页</button></div></section>
     </template>
    </template>
    <section v-else-if="page==='stability'" class="card">主仓暂无稳定性重复运行接口，请先使用普通评测。</section>
    <Comparisons v-else-if="page==='experiments'" />
    <Analysis v-else-if="page==='optimizer'||page==='analysis'" :key="route" :mode="page" :initial-id="runId" :runs="runs" />
    <div v-else class="card empty">页面不存在。<a href="#overview">返回总览</a></div>
   </main>
  </div>
  <RerunDialog v-if="rerunId" :id="rerunId" @close="rerunId=''" @created="id=>{rerunId='';go('tasks/'+id)}" />
  <el-dialog :model-value="!!detailDialog" @close="detailDialog=''" title="实验运行详情" width="min(1200px,96vw)" destroy-on-close><RunDetail v-if="detailDialog" :id="detailDialog" return-page="tasks" @navigate="value=>{detailDialog='';go(value)}"/></el-dialog>
  <EvaluationTaskForm v-if="create" :source="formSource" @close="create=false" @created="taskCreated"/>
 </div>
</template>

<style>
.task-identity{min-width:250px}.ab-identities{display:grid;gap:10px;margin-top:10px}.ab-identity{display:flex;gap:8px;align-items:flex-start}.ab-side{display:inline-grid;place-items:center;background:#e7f4ee;color:#00826a;border-radius:4px;width:21px;height:21px;font-size:11px;font-weight:700}.ab-identity div{display:grid;gap:3px;font-size:11px;color:#718278;overflow-wrap:anywhere}.ab-identity b{color:#384e42;font-size:12px}.ab-identity small{font-size:10px;color:#8a9791}.task-create-dialog .el-dialog__header{padding:20px 28px;border-bottom:1px solid #e5eaf0;margin:0}
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
.task-list-card th select{max-width:175px;background:transparent;border:0;color:inherit;font:inherit;padding:4px;cursor:pointer}.task-linked-summary{margin-bottom:20px}.task-linked-summary .actions{display:flex;gap:20px;margin-bottom:16px}.task-linked-summary button{margin-left:16px}.task-list-card th{background:#f6f8fa;white-space:nowrap}
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
