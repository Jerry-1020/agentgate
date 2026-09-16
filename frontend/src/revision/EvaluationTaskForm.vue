<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import EvaluatorSelectionGuide from './EvaluatorSelectionGuide.vue'
import {api,request,type DatasetSummary,type EvaluatorSummary} from './api'
import {recommendEvaluators} from './evaluator-guidance'
import {saveTaskLink,type TaskLink} from './task-links'
const props=defineProps<{source?:{id:string;version:number;caseIds?:string[];caseName?:string;targetVersion?:string;evaluatorId?:string}}>()
const emit=defineEmits<{close:[];created:[link:TaskLink]}>()
const taskKind=ref<'single'|'ab'>('single'),candidateVersion=ref(''),includeStatic=ref(false)
const mockBranch=ref('main'),modelBaseUrl=ref('https://model.example.com/compatible-mode/v1'),modelApiKey=ref('DEMO-ONLY-NOT-A-REAL-API-KEY'),modelName=ref('deepseek-v3.2')
const staticModelSource=ref('platform')
watch(includeStatic,enabled=>{if(!enabled)staticModelSource.value='platform'})
const modelOptions=['deepseek-v3.2','qwen-plus','qwen-max']
const create = ref(true), submitting = ref(false), formLoading=ref(false), datasetLoading=ref(false)
let formSequence=0
watch(create,open=>{if(!open){formSequence++;modelApiKey.value=''}})
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
const runSource=ref<{id:string;version:number;caseIds?:string[];caseName?:string;evaluatorId?:string}|null>(null)
async function openCreate(source?:{id:string;version:number;caseIds?:string[];caseName?:string;targetVersion?:string;evaluatorId?:string}) {
 const ticket=++formSequence;formLoading.value=true
 runSource.value=source??null
 scope.value=source?.caseIds?'selected':'all';selectedCaseIds.value=source?.caseIds??[]
 repetitions.value=1;concurrency.value=2;timeout.value=300;retries.value=0;launchMode.value='now';scheduledAt.value=''
 formError.value=''; selectedDataset.value=''; create.value=true
 try { const [d,e,v]=await Promise.all([api.datasets(),api.evaluators(),api.versions()]); if(ticket!==formSequence)return;descriptors.value=[];datasets.value=d.filter(x=>x.version!==null&&!x.archived); evaluators.value=e.filter(x=>x.enabled&&x.latest_version); versions.value=v; selectedDataset.value=source?.id||datasets.value[0]?.id||''; selectedVersion.value=source?.targetVersion&&v.some(x=>x.id===source.targetVersion)?source.targetVersion:(v[0]?.id??''); selectedEvaluators.value=source?.evaluatorId?[source.evaluatorId]:[]; candidateVersion.value=v.find(x=>x.id!==selectedVersion.value)?.id??'' }
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
 if(taskKind.value==='ab'&&(!candidateVersion.value||candidateVersion.value===selectedVersion.value)){formError.value='A/B 实验需要选择两个不同版本。';return}
 for(const [label,value,min,max] of [
  ['稳定性测试重复次数',repetitions.value,1,20],
  ['并发样本数',concurrency.value,1,32],
  ['执行超时（秒）',timeout.value,1,3600],
  ['失败重试次数',retries.value,0,5],
 ] as [string,number,number,number][]){
  if(!Number.isInteger(value)||value<min||value>max){formError.value=`${label}必须为 ${min}—${max} 的整数`;return}
 }
 if(repetitions.value>1){formError.value='稳定性多次执行尚未接入后端，请暂设为 1 次；不会按单次替代执行。';return}
 if(launchMode.value==='scheduled'&&(repetitions.value!==1||!scheduledAt.value||!Number.isFinite(new Date(scheduledAt.value).getTime())||new Date(scheduledAt.value).getTime()<=Date.now())){formError.value='预约时间必须晚于当前时间，且只支持单次普通评测。';return}
 const dataset=datasets.value.find(d=>d.id===selectedDataset.value)
 if(!dataset || selectedDatasetVersion.value===null || !selectedVersion.value || !selectedEvaluators.value.length) { formError.value='请选择已发布评测集、智能体版本和至少一个评估器。';return }
 submitting.value=true;formError.value=''
 try {
 await ElMessageBox.confirm(includeStatic.value&&staticModelSource.value==='custom'?'Git 分支与模型配置仅用于前端展示，尚未接入执行。继续后将使用已选智能体版本及服务端实际模型配置运行；此处填写的 API Key 不会发送或保存。':'Git 分支为 Mock 展示，不会用于执行。评测使用所选智能体和评估器的已有配置；如启用 Skill 静态分析，将使用平台模型配置。','确认实际执行配置',{confirmButtonText:'按实际配置执行',cancelButtonText:'返回修改'})
 const exact=await request<{cases:any[]}>(`/datasets/${dataset.id}/versions/${selectedDatasetVersion.value}`)
 const caseIds=scope.value==='selected'?selectedCaseIds.value:undefined
 if(!exact.cases.length||caseIds?.length===0)throw Error('请选择至少一条用例。')
 if(caseIds){exact.cases=exact.cases.filter(c=>caseIds.includes(c.id));if(exact.cases.length!==caseIds.length)throw Error('所选用例不在当前发布版本中。')}
 const chosen=evaluators.value.filter(e=>selectedEvaluators.value.includes(e.id))
 if(chosen.every(e=>e.kind==='rule')&&!recommendEvaluators(chosen,exact.cases).length)throw Error('所选评估器与样本期望没有适用检查。请补充期望或调整评估器。')
 const uncovered=exact.cases.filter(c=>chosen.every(e=>e.kind==='rule')&&!recommendEvaluators(chosen,[c]).length)
 if(uncovered.length)await ElMessageBox.confirm(`${uncovered.length} 条用例没有匹配检查，将标为不适用。是否继续？`,'检查覆盖范围',{confirmButtonText:'继续评测',cancelButtonText:'返回修改'})
 const link:TaskLink={id:'',kind:taskKind.value,runIds:[],staticReports:[],mockSelection:{branch:mockBranch.value,credentialScope:'frontend-only',credentialLabel:includeStatic.value?(staticModelSource.value==='custom'?modelName.value:'平台配置'):'未启用静态分析'}}
 if(taskKind.value==='ab'){
  const pair=await request<{baseline:{run_id:string};candidate:{run_id:string}}>('/run-comparisons','POST',{
   baseline_version:selectedVersion.value,candidate_version:candidateVersion.value,dataset_id:dataset.id,dataset_version:selectedDatasetVersion.value,
   evaluators:chosen.map(e=>({id:e.id,version:e.latest_version}))
  })
  link.id=pair.baseline.run_id;link.runIds=[pair.baseline.run_id,pair.candidate.run_id]
 }else{
  const run=await request<{run_id:string}>('/evaluations','POST',{version:selectedVersion.value,dataset_id:dataset.id,dataset_version:selectedDatasetVersion.value,evaluator_ids:selectedEvaluators.value,max_parallel_cases:concurrency.value,timeout_seconds:timeout.value,max_retries:retries.value,...(caseIds?{case_ids:caseIds}:{}),...(launchMode.value==='scheduled'?{scheduled_for:new Date(scheduledAt.value).toISOString()}:{})})
  link.id=run.run_id;link.runIds=[run.run_id]
 }
 try{saveTaskLink(link)}catch{ElMessage.warning('任务已创建，但浏览器未能保存关联信息，请保留运行 ID：'+link.runIds.join('、'))}
 if(includeStatic.value){
  for(const version of taskKind.value==='ab'?[selectedVersion.value,candidateVersion.value]:[selectedVersion.value]){
   try{
    const report=await request<{id:string}>('/evaluations/skill-analysis','POST',{version},240000)
    link.staticReports.push({version,reportId:report.id})
   }catch(e){link.staticReports.push({version,error:String(e)})}
   try{saveTaskLink(link)}catch{/* Run submission remains successful even if browser storage is unavailable. */}
  }
 }
 emit('created',link)
 ElMessage.success(link.staticReports.some(x=>x.error)?'运行已提交，静态分析未完成，请查看任务详情':'评测任务已提交')
 }

 catch(e) { if(e!=='cancel'&&e!=='close')formError.value=String(e) } finally { submitting.value=false }
}

watch(taskKind,kind=>{if(kind==='ab'){scope.value='all';launchMode.value='now';concurrency.value=1;timeout.value=300;retries.value=0}})
onMounted(()=>void openCreate(props.source))
</script>
<template>
  <el-dialog  :model-value="true" @close="emit('close')" :show-close="!submitting" :close-on-press-escape="!submitting" title="新建评测任务" width="min(1080px, 96vw)" class="task-create-dialog" top="3vh" :close-on-click-modal="false">

   <p v-if="formLoading||datasetLoading" role="status">正在加载任务配置…</p>
   <div v-if="formError" class="notice error" role="alert">{{formError}}</div>
   
   <div class="form-section-heading full"><span>01</span><div><h3>任务类型</h3></div></div>
   <div class="task-kind-choice" aria-label="任务类型"><button type="button" :class="{selected:taskKind==='single'}" :disabled="submitting" @click="taskKind='single'"><b>单任务</b></button><button type="button" :class="{selected:taskKind==='ab'}" :disabled="submitting" @click="taskKind='ab'"><b>A/B 实验</b></button></div>
   <fieldset :disabled="submitting" class="form-grid task-create-grid">
    <div class="form-section-heading full"><span>02</span><div><h3>评测对象</h3></div></div>
    <div class="target-choice full" :class="{'is-ab':taskKind==='ab'}"><label class="field">智能体<select class="input" aria-label="智能体"><option value="loan-agent">贷款审批演示智能体（内置 Demo）</option></select></label>
    <label class="field">关联 Git 分支<select class="input" aria-label="关联 Git 分支" v-model="mockBranch"><option value="main">main（Mock）</option><option value="develop">develop（Mock）</option><option value="feature/prompt-tuning">feature/prompt-tuning（Mock）</option></select></label>
    <label class="field">{{taskKind==='ab'?'实验 A · 基线版本':'智能体版本'}}<select aria-label="智能体版本" class="input" v-model="selectedVersion"><option v-for="v in versions" :key="v.id" :value="v.id">{{v.id==='loan-agent-v1-risky'?'旧方案 v1（风险版本）':v.id==='loan-agent-v2-fixed'?'修正方案 v2':v.label}} · {{v.id}}</option></select></label>
    <label v-if="taskKind==='ab'" class="field">实验 B · 候选版本<select class="input" v-model="candidateVersion" aria-label="实验 B · 候选版本"><option v-for="v in versions" :key="v.id" :value="v.id" :disabled="v.id===selectedVersion">{{v.id==='loan-agent-v1-risky'?'旧方案 v1（风险版本）':v.id==='loan-agent-v2-fixed'?'修正方案 v2':v.label}} · {{v.id}}</option></select></label>
    <p v-if="taskKind==='ab'" class="target-note">A 为基线，B 为候选；两侧共用评测集和评估器，仅比较版本变化。</p>
    </div>
    <div class="form-section-heading full"><span>03</span><div><h3>评测数据</h3></div></div>
    <label class="field">评测集<select class="input" v-model="selectedDataset"  aria-label="任务评测集"><option v-for="d in datasets" :value="d.id">{{d.name}}</option></select></label>
    <label class="field">评测集版本<select class="input" v-model="selectedDatasetVersion"  aria-label="任务评测集版本"><option v-for="v in datasetVersions" :value="v.version">v{{v.version}} · {{v.cases.length}} 条样本</option></select></label>
    <label class="field full">运行范围<select :disabled="taskKind==='ab'" class="input" aria-label="运行范围" v-model="scope"><option value="all">全部用例（{{availableCases.length}} 条）</option><option value="selected">指定用例</option></select><el-select v-if="scope==='selected'" v-model="selectedCaseIds" multiple filterable placeholder="选择要运行的用例" aria-label="指定用例"><el-option v-for="c in availableCases" :key="c.id" :label="c.name" :value="c.id"/></el-select><small v-if="taskKind==='ab'">当前 A/B 接口运行发布版本的全部用例；指定用例需后端扩展。</small><small v-if="scope==='selected'&&!selectedCaseIds.length">请从当前发布版本重新选择用例。</small></label>
    <div class="form-section-heading full"><span>04</span><div><h3>评估方式</h3></div></div>
    <EvaluatorSelectionGuide class="full" :initial-evaluator-id="runSource?.evaluatorId" :evaluators="evaluators" :cases="executionCases" :target-versions="taskKind==='ab'?[selectedVersion,candidateVersion]:[selectedVersion]" v-model="selectedEvaluators"/>
    <label class="static-option full"><input type="checkbox" v-model="includeStatic"/><span><b>Skill 静态分析</b><small>调用服务端模型检查职责冲突与路由歧义；结果单独展示，不替代用例评测。</small></span></label>
    <section v-if="includeStatic" class="static-model-settings full" aria-label="Skill 静态分析模型配置">
     <label class="field">静态分析模型来源<select class="input" aria-label="静态分析模型来源" v-model="staticModelSource"><option value="platform">使用平台模型配置（默认）</option><option value="custom">自定义模型 · Mock</option></select></label>
     <p class="muted">仅用于 Skill 静态分析；智能体和 LLM 评估器沿用各自版本的模型配置。</p>
     <p v-if="staticModelSource==='platform'" class="platform-model-note">由服务端提供模型与分析提示词，无需重复填写。</p>
     <template v-else>
    <div class="model-config-fields full">
     <label class="field">Base URL<input class="input" aria-label="Base URL" v-model="modelBaseUrl" type="url" placeholder="https://服务地址/compatible-mode/v1" autocomplete="off"/></label>
     <label class="field">API Key<input class="input" aria-label="API Key" v-model="modelApiKey" type="password" placeholder="请输入 API Key" autocomplete="off" spellcheck="false"/></label>
     <label class="field">模型名称<select class="input" aria-label="模型名称" v-model="modelName"><option v-for="model in modelOptions" :key="model" :value="model">{{model}}</option></select></label>
    </div>
    <p class="mock-notice full">Mock 示例配置：地址、API Key 和模型名称均为演示数据，可编辑或切换；示例 Key 无效。Base URL、API Key 不会发送或保存，关闭窗口后清空 API Key。实际调用仍使用服务端配置。</p>
     </template>
    </section>
    <div class="form-section-heading full"><span>05</span><div><h3>执行设置</h3></div></div>
    <div class="execution-settings full" aria-label="执行参数">
    <label class="field">执行时间<select aria-label="执行时间" class="input" v-model="launchMode" :disabled="taskKind==='ab'"><option value="now">立即执行</option><option value="scheduled">预约执行</option></select><small v-if="repetitions>1">稳定性测试暂不支持预约。</small></label>
    <label v-if="launchMode==='scheduled'" class="field">预约时间<input aria-label="预约时间" class="input" type="datetime-local" v-model="scheduledAt"/><small>本机时区 {{Intl.DateTimeFormat().resolvedOptions().timeZone}}；到期由调度服务进入队列。</small></label>
    <label class="field">并发样本数<input class="input"  :disabled="taskKind==='ab'" v-model.number="concurrency" title="1–32 个，最大 32 个" aria-label="并发样本数" type="number" min="1" max="32" step="1"/></label>
    <label class="field">执行超时（秒）<input class="input"  :disabled="taskKind==='ab'" v-model.number="timeout" title="1–3600 秒，最大 3600 秒" aria-label="执行超时（秒）" type="number" min="1" max="3600" step="1"/></label>
    <label class="field">稳定性测试<input class="input" type="number" v-model.number="repetitions" min="1" max="20" step="1" title="1–20 次，最大 20 次；当前后端仅支持 1 次" aria-label="稳定性测试"/></label>
    <label class="field">失败重试次数<input class="input"  :disabled="taskKind==='ab'" v-model.number="retries" title="0–5 次，最大 5 次" aria-label="失败重试次数" type="number" min="0" max="5" step="1"/></label>

    </div>
    <p v-if="repetitions>1" class="execution-limit full">当前后端仅支持 1 次；多次执行暂不能提交。</p>

    <p v-if="taskKind==='ab'" class="muted full">当前 A/B 接口固定为立即执行、并发 1、超时 300 秒、失败重试 0 次，两侧保持一致。</p>

   </fieldset>
   <p v-if="submitting" role="status">{{includeStatic?'任务提交与静态分析处理中，请勿重复提交；模型分析可能需要数分钟。':'正在提交任务…'}}</p>
   <p class="task-summary">本次：{{taskKind==='ab'?'A/B 实验 · 两个版本':'单任务'}} · {{versions.find(v=>v.id===selectedVersion)?.label??'待选目标'}} · v{{selectedDatasetVersion??'—'}} · {{executionCases.length}} 条用例 × {{repetitions}} 次 · {{selectedEvaluators.length}} 个评估器</p>
   <template #footer><button class="secondary"  :disabled="submitting" @click="emit('close')">取消</button><button class="primary" :disabled="submitting||formLoading||datasetLoading" @click="submit">{{submitting?'正在处理…':taskKind==='ab'?'创建 A/B 实验':'开始评测'}}</button></template>
  </el-dialog>
</template>
<style scoped>
.execution-settings{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;align-items:start}.execution-settings .field{min-width:0;margin:0;font-size:13px;gap:8px}.execution-settings .input{width:100%;min-width:0;padding:10px 12px;font-size:14px}.execution-settings small{font-size:11px}@media(max-width:1000px){.execution-settings{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:650px){.execution-settings{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:420px){.execution-settings{grid-template-columns:1fr}}
.execution-limit{color:#986616}
.static-model-settings{padding:20px;border:1px solid #d5e8df;border-radius:10px;background:#fbfdfc}.static-model-settings>.field{max-width:440px}.static-model-settings .muted,.platform-model-note{font-size:13px;line-height:1.7}.platform-model-note{color:#43715e;margin-bottom:0}
.model-config-fields{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:20px;min-width:0}.model-config-fields .field{min-width:0}@media(max-width:800px){.model-config-fields{grid-template-columns:1fr}}
.mock-notice{margin:0;padding:12px;background:#fff9eb;border:1px solid #eadbb9;border-radius:6px;color:#896e35;font-size:12px;line-height:1.6}.task-kind-choice{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}.task-kind-choice button{text-align:left;padding:16px 20px;border:1px solid #dce4e1;background:white;border-radius:8px;cursor:pointer}.task-kind-choice button.selected{border-color:#00a88b;background:#edf9f5;color:#007f6b}.task-kind-choice small{display:block;margin-top:6px;color:#64748b}.target-choice{display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:16px}.target-choice.is-ab{grid-template-columns:repeat(2,minmax(0,1fr))}.target-choice .field{min-width:0}.target-choice .input{width:100%;min-width:0}.target-note{grid-column:1/-1;margin:0;color:#64748b;font-size:12px;padding:10px 12px;background:#f6f8f9;border-radius:6px}.static-option{display:flex;align-items:flex-start;gap:10px;background:#f3f9f6;padding:16px;border-radius:8px}.static-option small{display:block;color:#64748b;margin-top:6px}fieldset{border:0;margin:0;padding:0;min-width:0}@media(max-width:700px){.target-choice,.target-choice.is-ab{grid-template-columns:1fr}}
</style>
