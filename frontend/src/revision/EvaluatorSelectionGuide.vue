<script setup lang="ts">
import {computed,ref,watch,onUnmounted} from 'vue'
import {request,kindLabel,type EvaluatorSummary,type TargetDescriptor} from './api'
import {evaluatorScenarios,evaluatorRecommendationReasons,recommendEvaluators,recommendationReason} from './evaluator-guidance'
const props=defineProps<{evaluators:EvaluatorSummary[];cases:any[];modelValue:string[];targetVersions?:string[];initialEvaluatorId?:string;targetDescriptors?:TargetDescriptor[]}>()
const emit=defineEmits<{'update:modelValue':[ids:string[]]}>()
const category=ref(props.initialEvaluatorId?'all':'recommended'),activeId=ref(props.initialEvaluatorId??''),confirmed=ref(false)
const recommended=computed(()=>recommendEvaluators(props.evaluators,props.cases))
const names:Record<string,string>={skill_routing:'技能路由',required_tool:'必需工具',forbidden_tool:'禁用工具',tool_arguments:'工具参数',final_state:'最终状态',final_output:'最终输出',policy_compliance:'策略合规',answer_quality:'回答质量'}
function displayName(e:EvaluatorSummary){return e.source==='builtin'?(names[e.implementation_id]??e.name):e.name}
function group(e:EvaluatorSummary){if(e.kind!=='rule')return 'semantic';if(e.implementation_id==='skill_routing')return 'routing';if(['required_tool','forbidden_tool','tool_arguments'].includes(e.implementation_id))return 'tools';return 'business'}
const categories=computed(()=>[
 {id:'recommended',name:'推荐',count:recommended.value.length},
 ...[{id:'routing',name:'技能路由'},{id:'tools',name:'工具调用'},{id:'business',name:'业务结果'},{id:'semantic',name:'模型评判'}].map(c=>({...c,count:props.evaluators.filter(e=>group(e)===c.id).length})),
 {id:'all',name:'全部',count:props.evaluators.length},
].filter(c=>c.count||['recommended','all'].includes(c.id)))
const items=computed(()=>props.evaluators.filter(e=>category.value==='all'||(category.value==='recommended'?recommended.value.includes(e.id):group(e)===category.value)))
const active=computed(()=>items.value.find(e=>e.id===activeId.value)??items.value[0])
const selected=computed(()=>props.evaluators.filter(e=>props.modelValue.includes(e.id)))
watch(()=>props.modelValue,()=>confirmed.value=false)
watch(()=>props.cases,()=>confirmed.value=false)
function toggle(id:string,checked:boolean){emit('update:modelValue',checked?[...new Set([...props.modelValue,id])]:props.modelValue.filter(x=>x!==id))}

const targetSkills=ref<Record<string,string[]>>({}),contextError=ref(''),contextLoading=ref(false)
let contextTicket=0
watch(()=>[props.targetVersions,props.targetDescriptors] as const,async ([versions,descriptors])=>{
 const ticket=++contextTicket;targetSkills.value={};contextError.value='';contextLoading.value=true
 try{
  if(descriptors){targetSkills.value=Object.fromEntries(descriptors.map(d=>[d.display_name+' · '+d.ref.external_version_id,d.skills.map(s=>s.external_skill_id)]));return}
  const entries=await Promise.all((versions??[]).filter(Boolean).map(async version=>{
   const graph=await request<any>('/targets/agentgate-demo/agent/loan-agent/versions/'+encodeURIComponent(version)+'/lineage')
   const skillIds=graph.nodes.filter((n:any)=>n.kind==='skill'&&graph.edges.some((edge:any)=>edge.source_id===graph.root_node_id&&edge.target_id===n.id&&edge.relation==='includes_skill')).map((n:any)=>n.external_id)
   return [version,skillIds] as const
  }))
  if(ticket===contextTicket)targetSkills.value=Object.fromEntries(entries)
 }catch{if(ticket===contextTicket)contextError.value='未能读取智能体定义；以下仅依据样本期望。'}
 finally{if(ticket===contextTicket)contextLoading.value=false}
},{immediate:true})
onUnmounted(()=>contextTicket++)
const internalContext=computed(()=>{
 const checks=props.cases.flatMap(c=>c.turns??[]).flatMap(t=>t.expectations??[])
 const unique=(values:unknown[])=>[...new Set(values.filter((v):v is string=>typeof v==='string'&&!!v))]
 const routes=unique(checks.filter(e=>e.kind==='skill_route').flatMap(e=>Array.isArray(e.condition?.expected)?e.condition.expected:[e.condition?.expected]))
 const tools=unique(checks.filter(e=>['tool_call','tool_argument'].includes(e.kind)).map(e=>e.tool))
 const paths=unique(checks.filter(e=>['state','output','tool_argument'].includes(e.kind)).map(e=>e.path))
 const type=active.value?.implementation_id
 const prompt=type==='skill_routing'?'核对路由提示词中的触发条件与 Skill 职责边界。':type==='forbidden_tool'?'核对提示词中的禁止动作与调用前权限约束。':type==='required_tool'?'核对提示词是否明确要求执行必需动作。':'核对提示词中的输出规范、业务状态与执行顺序约束。'
 return {routes,tools,paths,prompt}
})

function apply(){emit('update:modelValue',[...recommended.value]);category.value='recommended';activeId.value=recommended.value[0]??''}
</script>
<template>
 <section class="evaluator-guide" aria-label="评估器选择">
  <header class="guide-header">
   <div><span class="eyebrow">基于样本期望</span><h4>为本次评测选择检查项</h4><p>{{cases.length}} 条用例 · 推荐 {{recommended.length}} 个评估器</p></div>
   <div class="bulk-actions"><button type="button" class="link" :disabled="!evaluators.length" @click="emit('update:modelValue',evaluators.map(e=>e.id))">全选</button><button type="button" class="link" :disabled="!modelValue.length" @click="emit('update:modelValue',[])">全部取消</button><button class="secondary" type="button" :disabled="!recommended.length" title="用推荐项替换当前选择" @click="apply">采用推荐并查看理由</button></div>
  </header>
  <div class="dimension-nav" aria-label="检查维度">
   <button v-for="c in categories" :key="c.id" type="button" :class="{active:category===c.id}" :aria-pressed="category===c.id" @click="category=c.id">{{c.name}} <span>{{c.count}}</span></button>
  </div>
  <div class="guide-workbench">
   <div class="evaluator-options" aria-label="可选评估器">
    <div class="list-caption"><span>选择检查项</span><span>点击名称查看推荐依据 →</span></div>
    <div v-for="e in items" :key="e.id" class="evaluator-row" :class="{focused:active?.id===e.id,chosen:modelValue.includes(e.id)}">
     <input type="checkbox" :aria-label="'选择'+displayName(e)" :checked="modelValue.includes(e.id)" @change="toggle(e.id,($event.target as HTMLInputElement).checked)"/>
     <button type="button" :aria-pressed="active?.id===e.id" @click="activeId=e.id">
      <span class="row-heading"><b>{{displayName(e)}}</b><small v-if="recommended.includes(e.id)" class="recommended-tag">推荐</small></span>
      <span class="row-meta">{{kindLabel(e.kind)}} · v{{e.latest_version}}</span>
     </button><span class="row-arrow" aria-hidden="true">›</span>
    </div>
    <div v-if="!items.length" class="guide-empty"><b>当前没有匹配项</b><p>可切换其他检查维度，或查看全部评估器。</p><button class="link" type="button" @click="category='all'">查看全部评估器</button></div>
    <div class="confirm-evaluators"><button class="secondary" type="button" :disabled="!modelValue.length||confirmed" @click="confirmed=true">{{confirmed?'已确认评估器':'确认评估器'}}</button></div>
   </div>
   <aside class="recommendation-panel" aria-label="评估器推荐依据">
    <template v-if="active">
     <div class="reason-block">
      <h5>{{recommended.includes(active.id)?'推荐理由：':'适用条件'}}</h5>
      <p v-if="recommended.includes(active.id)" class="match-count">{{recommendationReason(active,cases)}}</p>
      <p>{{evaluatorRecommendationReasons[active.implementation_id]??active.description}}</p>
      <p v-if="!recommended.includes(active.id)&&active.kind==='rule'" class="unmatched">当前用例没有匹配期望，请确认适用性后选择。</p>
     </div>
     <section class="internal-context" aria-label="智能体内部推荐依据">
      <h5>与智能体内部的关联</h5><p v-if="contextLoading">正在读取所选智能体定义…</p><p v-if="contextError">{{contextError}}</p>
      <dl><dt>Skill 路由</dt><dd>样本期望：{{internalContext.routes.join('、')||'未声明'}}<span v-for="(skills,version) in targetSkills" :key="version">{{version}}：{{internalContext.routes.length?internalContext.routes.map(id=>id+(skills.includes(id)?'（定义中已包含）':'（定义中未找到）')).join('、'):skills.join('、')}}</span></dd>
      <dt>Tool 调用</dt><dd>{{internalContext.tools.join('、')||'所选样本未声明工具约束'}}<span>对应样本中的必需／禁止调用及参数检查；实际是否调用由 Trace 验证。</span></dd>
      <dt>字段约束</dt><dd>{{internalContext.paths.join('、')||'所选样本未声明字段约束'}}</dd>
      <dt>提示词</dt><dd>{{internalContext.prompt}}<span>{{targetDescriptors?.some(d=>d.prompt)?'所选目标提供了版本提示词；这里列出核对方向，不代表已执行模型检查。':'接口未提供提示词正文，这是核对方向，不代表已检查正文。'}}</span></dd></dl>
     </section>
     <div class="resource-note"><span aria-hidden="true">{{active.kind==='rule'?'✓':'◇'}}</span>{{active.kind==='rule'?'规则检查 · 无需模型凭据':'模型评判 · 需要有效模型凭据'}}</div>
     <button class="detail-action" type="button" :class="{added:modelValue.includes(active.id)}" @click="toggle(active.id,!modelValue.includes(active.id))">{{modelValue.includes(active.id)?'已加入 · 点击移除':'＋ 加入本次评测'}}</button>
    </template>
    <p v-else class="muted">选中一个检查项，查看它的用途和适用条件。</p>
   </aside>
  </div>
 </section>
</template>
<style scoped>
.confirm-evaluators{padding-top:16px;margin-top:12px;border-top:1px solid #e5ece8}.confirm-evaluators button{font-size:13px;padding:10px 18px}
.bulk-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:flex-end}.bulk-actions .link{font-size:12px}.internal-context{margin-top:16px;border-top:1px solid #e0e9e3;padding-top:12px}.internal-context h5{font-size:12px;margin:0 0 10px}.internal-context dl{display:grid;grid-template-columns:68px minmax(0,1fr);gap:10px;font-size:11px;line-height:1.7;margin:0}.internal-context dt{color:#718177}.internal-context dd{margin:0;overflow-wrap:anywhere;color:#365442}.internal-context dd span{display:block;color:#839087;margin-top:3px}.evaluator-guide{border:1px solid #dce5e2;border-radius:12px;overflow:hidden;background:#fff;min-width:0}
.guide-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 22px;background:linear-gradient(115deg,#f0f9f5,#fafcfb)}
.eyebrow{font-size:11px;color:#648477;letter-spacing:.6px}.guide-header h4,.detail-heading h4{font-size:16px;margin:5px 0 7px;color:#203a32}.guide-header p{font-size:12px;color:#6b7c76;margin:0}.guide-header button{font-size:12px;white-space:nowrap;background:#fff}
.dimension-nav{display:flex;gap:6px;padding:12px 18px;border-bottom:1px solid #e7ece9;flex-wrap:wrap}.dimension-nav button{display:flex;gap:7px;align-items:center;padding:7px 10px;border:0;border-radius:6px;background:transparent;color:#64716b;font-size:12px;cursor:pointer}.dimension-nav button.active{background:#e6f5ee;color:#087e60;font-weight:600}.dimension-nav span{font-size:11px;color:#86958e}.dimension-nav .active span{color:#0d8669}
.guide-workbench{display:grid;grid-template-columns:minmax(0,1fr) minmax(240px,.9fr)}.evaluator-options{padding:14px 14px 18px;min-width:0}.list-caption{display:flex;justify-content:space-between;gap:10px;color:#87958d;font-size:11px;padding:0 5px 10px}.evaluator-row{display:flex;align-items:center;gap:10px;border:1px solid transparent;border-bottom-color:#edf1ef;padding:10px 12px;min-width:0;border-radius:7px;margin-bottom:3px}.evaluator-row.focused{background:#f1f9f5;border-color:#bedfce}.evaluator-row input{width:15px;height:15px;accent-color:#00a487;flex:none}.evaluator-row button{flex:1;min-width:0;text-align:left;border:0;background:transparent;padding:0;cursor:pointer;color:#33463e}.row-heading{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.row-heading b{font-size:13px;overflow-wrap:anywhere}.row-meta{display:block;font-size:11px;color:#8a9690;margin-top:4px}.recommended-tag{font-size:10px;font-weight:400;color:#198769;background:#e2f2e9;padding:2px 6px;border-radius:4px}.row-arrow{color:#9bb2a5;font-size:20px}
.recommendation-panel{min-width:0;border-left:1px solid #e6ece8;background:#fafcfb;padding:20px;align-self:stretch}.detail-heading{margin-bottom:18px}.explanation h5,.reason-block h5{font-size:12px;margin:0 0 7px;color:#476355}.explanation p,.reason-block p{font-size:12px;line-height:1.75;margin:0;color:#637269;overflow-wrap:anywhere}.reason-block{margin-top:18px;background:#eef6f0;padding:14px;border-radius:8px;border-left:3px solid #83bba0}.reason-block .match-count{font-weight:600;color:#387555;margin-bottom:8px}.reason-block .unmatched{margin-top:8px;color:#9b793e}.resource-note{font-size:11px;color:#7d8d84;margin:18px 0 14px;display:flex;gap:7px}.detail-action{width:100%;padding:9px 12px;border:1px solid #b6d6c4;color:#087754;background:#fff;border-radius:6px;font-size:12px;cursor:pointer}.detail-action.added{background:#e8f4ed}
.selection-footer{border-top:1px solid #e2eae5;padding:16px 20px}.selection-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.selection-heading b{font-size:13px;color:#365343}.selection-heading>span{font-size:11px;color:#83928a}.selected-tags{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0}.selected-tags button{background:#f1f6f3;color:#41664f;border:1px solid #dfe9e2;border-radius:5px;font-size:11px;padding:5px 8px;cursor:pointer}.selected-tags span{margin-left:5px;color:#8fa394}.selection-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px}.selection-actions>span,.empty-selection{font-size:12px;color:#7f9086}.selection-actions button{font-size:12px;padding:8px 14px}.guide-empty{padding:20px;font-size:12px;line-height:1.6;color:#718479}
@media(max-width:700px){.guide-workbench{grid-template-columns:1fr}.recommendation-panel{border-left:0;border-top:1px solid #e6ece8}.guide-header,.selection-heading{align-items:flex-start;flex-direction:column}.selection-actions{flex-wrap:wrap}.list-caption span:last-child{display:none}}
</style>
