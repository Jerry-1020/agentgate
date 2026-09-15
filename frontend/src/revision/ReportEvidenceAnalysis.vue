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
const expanded=ref<string|null>(null)
watch(()=>props.report.run.id,()=>expanded.value=null)
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
</script>
<template>
 <section class="card section-gap rule-analysis" aria-label="基于真实报告的规则分析">
  <h2>分析结果</h2>
  <p v-if="!failed.length">{{errors||reviews?'暂无未通过结果，请先处理异常或待复核项。':'本次没有未通过结果。'}}</p>
  <article v-for="group in groups" :key="group.key" class="improvement-card">
   <h3>{{group.metric==='forbidden_tool_compliance'?'调用了禁用工具':group.name}}<small>（{{group.items[0].evaluator_id}} · v{{group.version}}）</small></h3>
   <button class="secondary" :aria-expanded="expanded===group.key" @click="expanded=expanded===group.key?null:group.key">{{expanded===group.key?'收起关联原因与建议':'查看关联原因与建议'}}</button>
   <div class="failure-line"><p>{{reason(group.items[0].reason)}}</p><span class="muted">涉及 {{new Set(group.items.map(r=>r.case_id)).size}} 条样本 · {{group.items.length}} 条未通过结果</span></div>
   <div class="sample-links"><button v-for="id in [...new Set(group.items.map(r=>r.case_id))]" :key="id" class="link sample-button" @click="reportCase=id">{{caseName(id)}} → 查看报告</button></div>
   <section v-if="expanded===group.key" class="recommendation" aria-label="基于失败证据的改进建议">
    <p><b>优先级：</b>{{group.items.some(r=>r.severity==='blocking')?'高（依据阻断检查）':'待确认'}} · <b>修改对象：</b>待根据 Trace 定位。</p>
    <div class="advice-line"><h3>改进建议</h3><p><strong>{{action(group.metric)[0]}}</strong>：{{action(group.metric)[1]}}</p></div>
    <div class="advice-line"><h4>如何验证</h4><p>{{action(group.metric)[2]}}</p></div>
   </section>
   <details>
    <summary>查看期望与实际执行证据</summary>
    <p v-if="group.metric==='forbidden_tool_compliance'" class="muted">期望为禁止调用约束；实际是 Trace 中的工具调用名称列表，并非智能体最终回答。</p>
    <div v-for="(result,index) in group.items" :key="index" class="annotated-evidence">
    <div class="checks-column"><h4>{{caseName(result.case_id)}}</h4>
     <div class="table-wrap" v-if="result.checks.some(c=>c.outcome==='fail')"><table class="data-table"><thead><tr><th>检查项</th><th>期望</th><th>实际</th></tr></thead><tbody><tr v-for="check in result.checks.filter(c=>c.outcome==='fail')" :key="check.id"><td>{{check.name}}<small>{{check.reason}}</small></td><td><pre>{{pretty(check.expected)??'未提供'}}</pre></td><td><pre>{{check.actual_missing?'未记录实际值':pretty(check.actual)??'未提供'}}</pre></td></tr></tbody></table></div>
     <p v-else>原报告未提供检查项明细，请查看原始报告。</p>
    </div><AnalysisAnnotation :key="report.run.id+':'+result.case_id" :run-id="report.run.id" :case-id="result.case_id" :case-name="caseName(result.case_id)" :dataset-name="report.run.manifest.dataset.dataset_name" :model-value="annotations[result.case_id]??''" @update:model-value="annotations[result.case_id]=$event"/>
    </div>
   </details>
  </article>
 </section>
 <el-dialog :model-value="!!reportCase" @close="reportCase=''" title="样本评测报告" width="min(1200px,94vw)" top="4vh" destroy-on-close>
  <div class="report-dialog-body"><CaseReport v-if="sample" :key="reportCase" :sample="sample" :results="report.results.filter(r=>r.case_id===reportCase)" :primary-ids="report.run.manifest.primary_evaluator_ids" :trace="trace" :trace-error="traceError" :trace-loading="traceLoading" complete hide-analyze/></div>
 </el-dialog>
</template>
<style scoped>
.annotated-evidence{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:24px;margin-top:20px}.checks-column{min-width:0}.checks-column h4{margin-top:0}@media(max-width:1000px){.annotated-evidence{grid-template-columns:1fr}}

.failure-line{display:flex;align-items:baseline;gap:24px;flex-wrap:wrap}.sample-links{margin:12px 0 20px}.sample-button{padding:8px 12px;border:1px solid #dce7e4;border-radius:6px;background:white}.advice-line{display:grid;grid-template-columns:100px minmax(0,1fr);align-items:baseline;gap:16px}.advice-line h3,.advice-line h4,.advice-line p{margin:10px 0}.report-dialog-body{max-height:78vh;overflow-y:auto}@media(max-width:600px){.advice-line{grid-template-columns:1fr;gap:0}}

.sample-links{display:flex;flex-wrap:wrap;gap:16px}.recommendation{margin-top:20px}

.improvement-card{border:1px solid #e3e8ee;border-radius:10px;padding:24px;margin-top:20px}.improvement-meta,.improvement-steps{display:grid;grid-template-columns:1fr 1fr;gap:24px}.improvement-steps{background:#f5f9f8;padding:16px;border-radius:8px}.improvement-card p,.improvement-card li{line-height:1.8}.improvement-card h4{margin:12px 0}.improvement-card li{margin-bottom:8px}.evidence-group{scroll-margin-top:24px}@media(max-width:700px){.improvement-meta,.improvement-steps{grid-template-columns:1fr;gap:8px}}

.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}.summary-grid>div{background:#f5f9f8;border:1px solid #e3eae8;border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:8px}.summary-grid strong{font-size:26px}.summary-grid span{font-size:13px;color:#64748b}
.evidence-group{border-top:1px solid #e5e7eb;padding:20px 0}.evidence-group h3{margin-top:0}.recommendation{background:#f3f8f6;padding:14px;line-height:1.7}details{margin:16px 0;padding:14px;border:1px solid #e4e9e7;border-radius:8px}summary{cursor:pointer;color:#00846f}small{display:block;color:#64748b;font-size:12px;margin-top:6px}h3 small{display:inline}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:200px;font-size:12px;margin:0}td{vertical-align:top;width:33%}
@media(max-width:700px){.summary-grid{grid-template-columns:repeat(2,1fr)}}
</style>
