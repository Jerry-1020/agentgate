<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {ElMessageBox} from 'element-plus'
import {staticChinese,skillChinese} from './static-chinese'
import ReportEvidenceAnalysis from './ReportEvidenceAnalysis.vue'
import {api,request,pretty,type Report,type EvaluationRun} from './api'
const props=defineProps<{mode:string;initialId?:string;preferredReportId?:string;lockTarget?:boolean;targetName?:string;runs:EvaluationRun[]}>()
const analyzing=ref(false)
const skills=ref<{external_id:string;label:string;version:string|null}[]>([])
const selectedSkill=ref(''),loadingContext=ref(false)
const filteredFindings=computed(()=>(data.value?.findings??[]).filter((f:any)=>!selectedSkill.value||(f.skill_ids??[]).includes(selectedSkill.value)))
const categoryName=(v:string)=>({skill_overlap:'Skill 职责重叠',skill_confusion:'Skill 路由歧义',skill_conflict:'Skill 职责冲突',skill_duplicate:'Skill 职责重复'}[v]??v)
const skillName=(id:string)=>skillChinese(skills.value.find(s=>s.external_id===id)?.label??id)
const reviewLabel=(v:string)=>({confirmed:'确认问题',dismissed:'排除问题',accepted_risk:'接受风险',deferred:'暂缓'}[v]??v)
const severityLabel=(v:string)=>({info:'提示',warning:'警告',high:'高风险',blocking:'阻断'}[v]??v)
const selected=ref(props.initialId??''),versions=ref<{id:string;label:string}[]>([]),data=ref<any>(null),error=ref(''),busy=ref(false),history=ref<any[]>([]),historyId=ref(''),hash=ref(''),reviewer=ref(''),reviews=ref<any[]>([])
const analysisStatus=(value:string)=>({completed:'已完成',partial:'部分完成',failed:'分析失败'}[value]??value)
const evidenceReport=ref<Report|null>(null)
const decisions=ref<Record<string,string>>({}),comments=ref<Record<string,string>>({})
let ticket=0
const options=computed(()=>props.mode==='analysis'?versions.value.filter(v=>!props.lockTarget||v.id===props.initialId).map(v=>({...v,label:({'Risky version':'旧方案','Fixed version':'修复方案'} as Record<string,string>)[v.label]??v.label})):props.runs.filter(r=>r.status==='completed').map(r=>({id:r.id,label:r.manifest.target.display_name+' · '+r.manifest.target.ref.external_version_id+' · '+r.id.slice(0,8)})))
const message=computed(()=>{
 if(/invalid response/i.test(error.value))return '模型返回内容未通过结构化校验，未生成有效结论。可重试；若持续出现，请检查模型兼容性。'
 if(/timed out|超时/i.test(error.value))return '模型分析超时，未取得完整结论。请稍后重试，或检查服务端模型响应。'
 if(/unavailable|503/i.test(error.value))return '模型服务当前不可用。请核对服务端配置、密钥授权、额度和网络后重试。'
 return error.value
})
watch(()=>props.mode,()=>{ticket++;selected.value='';data.value=null;evidenceReport.value=null;error.value='';busy.value=false;history.value=[];hash.value=''})
watch(selected,()=>{ticket++;data.value=null;evidenceReport.value=null;error.value='';busy.value=false;reviews.value=[];history.value=[];hash.value='';historyId.value='';selectedSkill.value='';skills.value=[];decisions.value={};comments.value={};if(props.mode==='optimizer'&&selected.value)void loadEvidence();else if(props.mode==='analysis'&&selected.value)void loadContext()})
async function loadEvidence(){
 const current=++ticket;busy.value=true;error.value=''
 try{const report=await api.report(selected.value);if(current!==ticket)return;if(report.run.status!=='completed')throw Error('任务尚未完成，无法分析。');evidenceReport.value=report}
 catch(e){if(current===ticket)error.value=String(e)}finally{if(current===ticket)busy.value=false}
}
async function loadContext(){
 const current=++ticket,version=selected.value;loadingContext.value=true
 try{
  const graph=await request<any>('/targets/agentgate-demo/agent/loan-agent/versions/'+encodeURIComponent(selected.value)+'/lineage')
  if(current!==ticket)return
  const root=graph.nodes.find((n:any)=>n.id===graph.root_node_id)
  if(!root?.content_sha256)throw Error('未取得版本定义指纹，无法查询报告。')
  hash.value=root.content_sha256
  skills.value=graph.nodes.filter((n:any)=>n.kind==='skill'&&graph.edges.some((e:any)=>e.source_id===root.id&&e.target_id===n.id&&e.relation==='includes_skill'))
  const reports=await request<any[]>('/skill-analysis/reports?'+new URLSearchParams({target_descriptor_sha256:hash.value}))
  if(current!==ticket)return
  history.value=reports
  if(reports.length){historyId.value=reports.find(r=>r.id===props.preferredReportId)?.id??reports[0].id;await openHistory()}
 }catch(e){if(current===ticket)error.value=String(e)}
 finally{if(selected.value===version)loadingContext.value=false}
}
async function loadHistory(){if(hash.value)history.value=await request<any[]>('/skill-analysis/reports?'+new URLSearchParams({target_descriptor_sha256:hash.value}))}
async function analyze(){
 if(props.mode!=='analysis'||!hash.value||busy.value||loadingContext.value)return
 const current=++ticket;busy.value=true;analyzing.value=true;error.value='';data.value=null
 try{
  const result=await request<any>('/skill-analysis/reports','POST',{target_descriptor_sha256:hash.value},180000)
  if(current!==ticket)return
  data.value=result;reviews.value=[];decisions.value={};comments.value={}
  if(props.mode==='analysis'){hash.value=result.target_descriptor_sha256;historyId.value=result.id;await loadHistory()}
 }catch(e){if(current===ticket)error.value=String(e)}finally{if(current===ticket){busy.value=false;analyzing.value=false}}
}
async function openHistory(){
 const current=++ticket;if(!historyId.value)return
 busy.value=true;error.value=''
 try{const detail=await request<any>('/skill-analysis/reports/'+encodeURIComponent(historyId.value));if(current===ticket){data.value=detail.report;reviews.value=detail.reviews;decisions.value={};comments.value={}}}
 catch(e){if(current===ticket)error.value=String(e)}finally{if(current===ticket)busy.value=false}
}
async function review(id:string){
 if(!reviewer.value.trim()||!decisions.value[id]){error.value='请填写复核人并选择复核结论。';return}
 const reportId=data.value.id,current=++ticket
 busy.value=true;error.value=''
 try{
  const {value}=await ElMessageBox.prompt('填写判断依据；只保存复核记录，不修改报告或智能体。','复核说明',{inputType:'textarea',inputValidator:v=>!!v?.trim()||'请填写复核说明',confirmButtonText:'保存复核',cancelButtonText:'取消'})
  const saved=await request<any>('/skill-analysis/reports/'+encodeURIComponent(reportId)+'/findings/'+encodeURIComponent(id)+'/review','PUT',{decision:decisions.value[id],reviewer_id:reviewer.value.trim(),comment:value.trim()})
  if(current===ticket)reviews.value=[saved,...reviews.value.filter(r=>r.finding_id!==id)]
 }catch(e){if(current===ticket&&e!=='cancel'&&e!=='close')error.value=String(e)}finally{if(current===ticket)busy.value=false}
}
onMounted(async()=>{if(props.mode==='optimizer'){if(selected.value)await loadEvidence();return}try{if(!props.lockTarget)versions.value=await api.versions();if(selected.value)await loadContext()}catch(e){error.value=String(e)}})
onUnmounted(()=>ticket++)
</script>
<template><div class="page-head"><div><div v-if="mode==='optimizer'" class="analysis-return"><a v-if="initialId" class="link" :href="'#tasks/'+encodeURIComponent(initialId)">← 返回来源评测任务</a><a v-else-if="selected" class="link" :href="'#tasks/'+encodeURIComponent(selected)">← 查看所选评测任务</a><a class="link" href="#tasks">返回任务列表</a></div><h1 class="page-title">{{mode==='analysis'?'Skill 静态分析':'调优中心'}}</h1><p class="page-sub">{{mode==='analysis'?'按版本查看 Skill 关系、历史分析与复核结果。':'从失败证据定位问题，查看改进建议，再进入回归验证。'}}</p></div></div><section class="card"><h3 v-if="mode==='analysis'">{{lockTarget?'本次任务评测对象':'第一步：选择要检查的智能体版本'}}</h3><div :class="{'selection-row':mode==='analysis'}"><div v-if="lockTarget" class="field task-target" aria-label="本次任务评测对象"><strong>{{targetName}}</strong><span>智能体版本：{{initialId}}</span><small class="muted">来自本次评测任务的运行配置，不可更换。</small></div><label v-else class="field">{{mode==='analysis'?'智能体版本':'已完成任务'}}<select class="input" v-model="selected" :disabled="busy" aria-label="分析对象"><option value="">请选择</option><option v-for="o in options" :value="o.id">{{o.label}}</option></select></label><button v-if="mode==='analysis'" class="primary" :disabled="!hash||busy||loadingContext" @click="analyze()">{{busy?(analyzing?'分析中…':'读取中…'):(data?'重新分析':'运行分析')}}</button></div><p class="muted">{{mode==='optimizer'?'选择任务后自动展示分析结果。':'模型比较 Skill 职责关系，不运行评测用例。'}}</p><button v-if="mode==='optimizer'&&error" class="secondary" :disabled="busy" @click="loadEvidence()">重新加载</button><p v-if="busy" class="muted" role="status">{{mode==='optimizer'&&!evidenceReport?'正在读取评测报告…':(analyzing?'正在调用服务端模型，复杂任务可能需要 1–3 分钟，请勿重复提交。':'正在读取已保存的报告…')}}</p><p v-if="error" role="alert">{{message}}</p><label v-if="history.length" class="field">历史报告<select class="input" v-model="historyId" :disabled="busy" @change="openHistory"><option v-for="r in history" :value="r.id">{{new Date(r.created_at).toLocaleString()}} · {{analysisStatus(r.status)}}</option></select></label>
 <template v-if="mode==='analysis'&&selected"><p v-if="loadingContext" role="status">正在读取版本与历史报告…</p><div v-if="skills.length" class="skill-context"><h3>{{lockTarget?'本次版本包含的 Skill':'第二步：确认要检查的 Skill'}}</h3><table class="data-table"><thead><tr><th>Skill</th><th>版本</th></tr></thead><tbody><tr v-for="skill in skills" :key="skill.external_id"><td>{{skillChinese(skill.label)}}</td><td>{{skill.version??'未提供版本'}}</td></tr></tbody></table></div><p v-if="!loadingContext&&!history.length&&!error" class="muted">此版本暂无历史报告，可发起分析。</p></template>
 </section>
<ReportEvidenceAnalysis v-if="mode==='optimizer'&&evidenceReport" :report="evidenceReport"/>
<section v-if="data&&mode==='analysis'" class="card section-gap">
 <div class="static-report-body">
 <div class="report-toolbar"><h2>第三步：查看问题与修改建议</h2><label class="field reviewer">复核人<input class="input" v-model="reviewer" placeholder="姓名或工号" :disabled="busy"/></label></div>
 <div class="report-toolbar"><label class="field skill-filter">涉及 Skill<select class="input" v-model="selectedSkill" aria-label="筛选问题 Skill"><option value="">全部 Skill</option><option v-for="skill in skills" :value="skill.external_id">{{skillChinese(skill.label)}}</option></select></label><span class="muted" role="status">{{analysisStatus(data.status)}} · {{data.findings.length}} 项发现</span></div>
 <details v-if="data.errors?.length" class="analysis-errors"><summary>查看检查异常（{{data.errors.length}}）</summary><p>部分检查未完成，不代表全部通过。</p><p v-for="(item,index) in data.errors" :key="index">{{skillName(item.left_skill_id)}} ↔ {{skillName(item.right_skill_id)}}：{{item.category==='invalid_output'?'模型输出未通过校验':item.category}}</p></details>
 <article v-for="f in filteredFindings" :key="f.id" class="mini-card section-gap finding-card">
  <div class="report-toolbar"><h3>{{categoryName(f.category)}} <small class="muted">· {{severityLabel(f.severity)}}</small></h3><div class="review-controls"><label>复核状态<select class="input" :value="decisions[f.id]??reviews.find(r=>r.finding_id===f.id)?.decision??''" @change="decisions[f.id]=($event.target as HTMLSelectElement).value" :disabled="busy"><option value="">未复核</option><option value="confirmed">确认问题</option><option value="dismissed">排除问题</option><option value="accepted_risk">接受风险</option><option value="deferred">暂缓</option></select></label><button class="secondary" :disabled="busy||!decisions[f.id]" @click="review(f.id)">保存复核</button></div></div>
  <p>{{staticChinese(f.reason)}}</p><p><b>涉及 Skill：</b>{{f.skill_ids?.length?f.skill_ids.map(skillName).join('、'):'智能体整体'}}</p>
  <h4>修改建议</h4><ul v-if="f.suggestions?.length"><li v-for="suggestion in f.suggestions">{{staticChinese(suggestion)}}</li></ul><p v-else class="muted">服务端未提供修改建议。</p>
  <details><summary>问题依据</summary><div v-for="(e,index) in f.evidence" :key="index"><p><b>来源：</b>{{e.source==='llm_skill_description_comparison'?'模型对比技能职责描述':e.source}}</p><p><b>模型：</b>{{e.model_id}}</p><p v-if="e.ambiguous_examples?.length"><b>易混淆请求示例：</b></p><ul><li v-for="example in e.ambiguous_examples">{{staticChinese(example)}}</li></ul></div></details>
  <p v-if="reviews.find(r=>r.finding_id===f.id)" class="muted">已保存复核：{{reviewLabel(reviews.find(r=>r.finding_id===f.id)?.decision)}} · {{reviews.find(r=>r.finding_id===f.id)?.reviewer_id}}：{{reviews.find(r=>r.finding_id===f.id)?.comment}}</p>
 </article>
 <p v-if="!filteredFindings.length" class="muted">当前筛选下没有发现项，不代表已通过全部检查。</p>
 </div>
 <details><summary>原始报告</summary><pre>{{pretty(data)}}</pre></details>
</section></template>

<style scoped>.task-target{display:grid;gap:8px;padding:14px;background:#f5f9f8;border-radius:8px;overflow-wrap:anywhere}.selection-row{display:flex;gap:24px;align-items:flex-end}.selection-row>.field{flex:1;margin-bottom:0}.selection-row>button{flex-shrink:0}.report-toolbar{display:flex;justify-content:space-between;gap:24px;align-items:center;flex-wrap:wrap}.reviewer,.skill-filter{width:240px}.review-controls{display:flex;gap:12px;align-items:flex-end}.review-controls label{width:160px}.analysis-errors{margin:12px 0}.finding-card pre{max-height:280px;overflow:auto;white-space:pre-wrap}.finding-card p,.finding-card li{line-height:1.7}@media(max-width:700px){.selection-row{flex-direction:column;align-items:stretch}.review-controls{flex-wrap:wrap}.reviewer,.skill-filter{width:100%}}.skill-context{margin-top:20px}.skill-list{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.skill-list>span{border:1px solid #dce8e3;border-radius:6px;padding:10px}.verification-entry{border-top:1px solid #e5e7eb;margin-top:20px}.static-report-body .field{margin:16px 0}.static-report-body textarea{margin:12px 0}.analysis-return{display:flex;gap:24px;margin-bottom:16px;flex-wrap:wrap}</style>
