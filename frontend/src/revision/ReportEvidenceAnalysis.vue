<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import AnalysisAnnotation from './AnalysisAnnotation.vue'
import CaseReport from './CaseReport.vue'
import {api,pretty,type Report} from './api'
import type {EvaluationResult,Trace} from '../upstream/api/client'
const props=defineProps<{report:Report}>()
const annotations=ref<Record<string,string>>({})
watch(()=>props.report.run.id,()=>{annotations.value={}})
const reportCase=ref('')
const trace=ref<Trace|null>(null),traceLoading=ref(false),traceError=ref('')
const sample=computed(()=>props.report.run.manifest.dataset.cases.find(c=>c.id===reportCase.value))
let traceTicket=0
watch(()=>props.report.run.id,()=>{reportCase.value=''})
watch(reportCase,async id=>{
 const ticket=++traceTicket;trace.value=null;traceError.value='';traceLoading.value=!!id
 if(!id)return
 try{const value=await api.trace(props.report.run.id,id);if(ticket===traceTicket)trace.value=value}
 catch(e){if(ticket===traceTicket)traceError.value=String(e)}
 finally{if(ticket===traceTicket)traceLoading.value=false}
})
const guidance:Record<string,string>={
 forbidden_tool_compliance:'核对禁用工具约束、调用前的权限判断和实际工具调用记录；修改后用同一发布样本复测。',
 skill_routing_accuracy:'核对期望 Skill、实际路由记录及路由触发条件；不能仅凭路由不匹配断言提示词错误。',
 required_tool_coverage:'核对必需工具是否被调用，以及条件分支是否跳过该步骤。',
 tool_argument_accuracy:'逐项对比参数路径的期望值与实际值，核对字段映射、类型和调用前的校验。',
 final_state_accuracy:'对照失败状态字段与业务期望，检查状态更新分支和工具执行结果。',
 final_output_accuracy:'对照失败输出字段，检查输出格式、字段映射和结果生成环节。',
 policy_compliance:'核对样本策略约束及实际执行证据，检查策略条件和执行顺序。'
}
const actions:Record<string,[string,string,string]>={
 forbidden_tool_compliance:['限制禁用工具的调用路径','根据关联 Trace，核对被禁止工具的触发条件，在对应业务分支阻止调用。','重跑关联样本，确认禁用工具不再出现，并检查其他必需动作是否执行。'],
 tool_coverage:['补齐必需工具调用','检查缺失工具的触发条件与执行分支，补齐调用步骤。','确认必需工具均被调用，再核对参数和返回结果。'],
 policy_compliance:['修正业务策略执行','对照策略失败原因核对业务分支，同时检查禁止动作和要求达到的业务状态。','逐项确认策略检查通过，不以单个工具调用成功代替策略通过。'],
 final_state_match:['修正最终业务状态','对照状态检查项的期望与实际值，修正状态更新条件。','确认失败状态字段达到期望，并检查状态更新前置动作。'],
 tool_argument_accuracy:['修正工具参数构造','对照工具参数检查项，修正对应参数字段和取值来源。','确认失败参数符合期望，并检查工具执行结果。'],
 skill_routing_accuracy:['修正 Skill 路由条件','对照期望 Skill 与实际路由，核对触发条件和职责边界。','确认实际 Skill 符合期望，并回归相邻场景。']
}
const action=(metric:string)=>actions[metric]??['核对并修正执行配置',suggestion(metric),'使用同一评测集发布版本和评估器版本重跑关联样本，对比修复前后结果，并检查是否引入新的失败。']
const evaluatorTitle=(id:string,name:string)=>({'final-state':'最终业务状态','forbidden-tool':'调用了禁用工具','policy-compliance':'策略合规','required-tool':'必需工具调用','skill-routing':'技能路由','tool-arguments':'工具参数','final-output':'最终输出'} as Record<string,string>)[id]??name
const groups=computed(()=>{
 const map=new Map<string,{key:string;name:string;version:string;metric:string;items:EvaluationResult[]}>()
 for(const result of props.report.results.filter(r=>r.outcome==='fail')){
  const key=result.evaluator_id+':'+result.evaluator_version
  const group=map.get(key)??{key,name:result.evaluator_name,version:result.evaluator_version??'',metric:result.metric,items:[]}
  group.items.push(result);map.set(key,group)
 }
 return [...map.values()].sort((a,b)=>b.items.length-a.items.length)
})
const failed=computed(()=>props.report.results.filter(r=>r.outcome==='fail'))

const errors=computed(()=>props.report.results.filter(r=>r.outcome==='error').length)
const reviews=computed(()=>props.report.results.filter(r=>r.outcome==='review').length)
const caseName=(id:string)=>props.report.run.manifest.dataset.cases.find(c=>c.id===id)?.name??id
const reason=(text:string)=>[...new Set(text.split(/[；;]/).map(t=>t.trim()).filter(Boolean))].join('；')
const suggestion=(metric:string)=>guidance[metric]??'逐项核对下方期望值、实际值与 Trace；先确认样本约束是否正确，再排查智能体执行过程。'
const groupKey=ref(''),caseKey=ref('')
const activeGroup=computed(()=>groups.value.find(g=>g.key===groupKey.value)??groups.value[0])
const caseIds=computed(()=>[...new Set(activeGroup.value?.items.map(r=>r.case_id)??[])])
const selectedCase=computed({get:()=>caseIds.value.includes(caseKey.value)?caseKey.value:caseIds.value[0]??'',set:(v:string)=>caseKey.value=v})
const caseResults=computed(()=>activeGroup.value?.items.filter(r=>r.case_id===selectedCase.value)??[])
watch(()=>props.report.run.id,()=>{groupKey.value='';caseKey.value=''})
</script>
<template>
<section class="card section-gap rule-analysis" aria-label="基于真实报告的规则分析">
<h2>分析结果</h2>
<p v-if="!failed.length">{{errors||reviews?'暂无未通过结果，请先处理异常或待复核项。':'本次没有未通过结果。'}}</p>
<div v-if="activeGroup" class="tuning-workbench">
<nav class="tuning-evaluators" aria-label="调优评估器"><h3>评估器</h3>
<button v-for="group in groups" :key="group.key" class="evaluator-option" :class="{selected:activeGroup.key===group.key}" :aria-pressed="activeGroup.key===group.key" @click="groupKey=group.key">
<b>{{evaluatorTitle(group.items[0].evaluator_id,group.name)}}</b><small>v{{group.version}} · {{new Set(group.items.map(r=>r.case_id)).size}} 条问题用例</small>
</button></nav>
<section class="tuning-cases" aria-label="测试用例与样本报告"><h3>测试用例与样本报告</h3>
<label class="case-picker">测试用例<select v-model="selectedCase" aria-label="选择分析用例"><option v-for="id in caseIds" :key="id" :value="id">{{caseName(id)}}</option></select></label>
<div class="case-heading"><h4>{{caseName(selectedCase)}}</h4><button class="link" @click="reportCase=selectedCase">查看完整样本评测报告 ↗</button></div>
<p class="muted">当前展示所选评估器的未通过检查项。</p>
<article v-for="(result,index) in caseResults" :key="index" class="case-result">
<p>{{reason(result.reason)}}</p>
<div v-for="check in result.checks.filter(c=>c.outcome==='fail')" :key="check.id" class="check-result">
<b>{{check.name}}</b><small>{{check.reason}}</small>
<div class="expected-actual"><div><h5>期望</h5><pre>{{pretty(check.expected)??'未提供'}}</pre></div><div><h5>实际</h5><pre>{{check.actual_missing?'未记录实际值':pretty(check.actual)??'未提供'}}</pre></div></div>
</div><p v-if="!result.checks.some(c=>c.outcome==='fail')" class="muted">报告未提供检查项明细，可查看完整样本报告。</p>
</article>
<details class="recommendation"><summary>原因与改进建议</summary>
<p><b>优先级：</b>{{activeGroup.items.some(r=>r.severity==='blocking')?'高':'待确认'}} · 修改对象待根据 Trace 定位。</p>
<p><b>{{action(activeGroup.metric)[0]}}</b>：{{action(activeGroup.metric)[1]}}</p><p><b>如何验证：</b>{{action(activeGroup.metric)[2]}}</p>
</details></section>
<aside class="tuning-notes" aria-label="用例人工备注"><p class="note-context">{{caseName(selectedCase)}}</p>
<AnalysisAnnotation :key="report.run.id+':'+selectedCase" :run-id="report.run.id" :case-id="selectedCase" :case-name="caseName(selectedCase)" :dataset-name="report.run.manifest.dataset.dataset_name" :model-value="annotations[selectedCase]??''" @update:model-value="annotations[selectedCase]=$event"/>
</aside></div></section>
<el-dialog :model-value="!!reportCase" @close="reportCase=''" title="样本评测报告" width="min(1200px,94vw)" top="4vh" destroy-on-close>
<div class="report-dialog-body"><CaseReport v-if="sample" :key="reportCase" :sample="sample" :results="report.results.filter(r=>r.case_id===reportCase)" :primary-ids="report.run.manifest.primary_evaluator_ids" :trace="trace" :trace-error="traceError" :trace-loading="traceLoading" complete hide-analyze/></div>
</el-dialog>
</template>
<style scoped>
.tuning-workbench{display:grid;grid-template-columns:minmax(160px,.7fr) minmax(0,2fr) minmax(220px,1fr);border:1px solid #e1e9e6;border-radius:10px;overflow:hidden}
.tuning-evaluators,.tuning-cases,.tuning-notes{min-width:0;padding:20px}.tuning-evaluators{background:#f7faf9}.tuning-cases{border-inline:1px solid #e1e9e6}.tuning-workbench h3{font-size:16px;margin:0 0 20px}
.evaluator-option{display:block;width:100%;text-align:left;border:1px solid transparent;border-radius:8px;background:transparent;padding:14px 10px;margin-bottom:8px;cursor:pointer;overflow-wrap:anywhere}.evaluator-option.selected{background:#e3f4ef;border-color:#9cd6c5;color:#007d68}
small{display:block;color:#718096;font-size:12px;margin-top:6px;line-height:1.6}
.case-picker{display:grid;gap:8px;font-size:13px;color:#64748b}.case-picker select{width:100%;padding:10px;border:1px solid #d3dbd8;border-radius:6px;background:white;color:#172333}
.case-heading{margin-top:20px}.case-heading h4{margin:0 0 10px}.case-heading button{text-align:left;font-size:13px}
.case-result{font-size:13px;line-height:1.7}.check-result{padding:14px 0;border-bottom:1px solid #e7eeeb}.expected-actual{display:grid;grid-template-columns:1fr 1fr;gap:10px}.expected-actual>div{min-width:0}h5{margin:10px 0 6px;color:#64748b}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fa;padding:10px;border-radius:6px;font-size:12px;margin:0;max-height:240px;overflow:auto}
.recommendation{margin-top:20px;padding:12px;background:#f3f8f6;border-radius:6px;font-size:13px;line-height:1.8}summary{cursor:pointer;color:#00846f}
.note-context{font-size:13px;color:#64748b;margin-top:0}.tuning-notes :deep(.annotation-panel){border:0;padding:0}.report-dialog-body{max-height:78vh;overflow:auto}
@media(max-width:950px){.tuning-workbench{grid-template-columns:1fr}.tuning-cases{border-inline:0;border-block:1px solid #e1e9e6}.tuning-evaluators{display:flex;flex-wrap:wrap;gap:8px}.tuning-evaluators h3{width:100%}.evaluator-option{width:auto;margin:0}}
</style>
