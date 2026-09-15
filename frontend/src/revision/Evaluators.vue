<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {setBuiltinEnabled} from './evaluator-preferences'
import { ElMessage } from 'element-plus'
import { api, request, kindLabel, pretty, type EvaluatorSummary, type EvaluatorDetail, type Definition, type Kind } from './api'
import EvaluatorImport from './EvaluatorImport.vue'
import EvaluatorVersions from "./EvaluatorVersions.vue"
import MockEvaluator from './MockEvaluator.vue'
const props=defineProps<{initialId?:string}>(),emit=defineEmits<{dirtyChange:[dirty:boolean];launch:[id:string]}>()
const mockSelected=ref(false),importOpen=ref(false),enabledFilter=ref('all')
const draftEdit=ref<Definition|null>(null),createDescription=ref(''),createKind=ref<Kind>('rule')
const createChoices=computed(()=>items.value.filter(e=>e.kind===createKind.value&&e.latest_version))
import EvaluatorEditor from './EvaluatorEditor.vue'
import {evaluatorScenarios,evaluatorRecommendationReasons} from './evaluator-guidance'
const edit=ref<Definition|null>(null)
const items=ref<EvaluatorSummary[]>([]), kind=ref<Kind>('rule'), query=ref(''), selected=ref<EvaluatorDetail|null>(null)
const tab=ref('definition'), error=ref(''), busy=ref(false), loading=ref(false)
const description=ref(''), name=ref(''), config=ref('{}')
const form=ref(false), cloneFrom=ref(''),formBaseline=ref('')
function formSnapshot(){return JSON.stringify([name.value,createDescription.value,createKind.value,draftEdit.value])}
const filtered=computed(()=>items.value.filter(e=>e.kind===kind.value && (enabledFilter.value==='all'||e.enabled===(enabledFilter.value==='enabled')) && `${e.name} ${e.description}`.toLowerCase().includes(query.value.toLowerCase())))
const enabledReason=computed(()=>!selected.value?'':!selected.value.latest?'请先发布草稿，再启用评估器。':dirty.value?'请先保存当前修改。':busy.value?'操作处理中，请稍候。':'')
const historical=ref<Definition|null>(null)
const definition=computed(()=>historical.value??selected.value?.draft??selected.value?.latest)
const readOnly=computed(()=>!!historical.value||!selected.value?.draft||selected.value?.evaluator.source==='builtin')
function viewVersion(value:Definition|null){historical.value=value;edit.value=definition.value?JSON.parse(JSON.stringify(definition.value)):null}
const sourceFiles=import.meta.glob('../../../backend/src/agentgate/evaluator/{rule/*.py,judge/*.py,hybrid.py}',{eager:true,query:'?raw',import:'default'})
const source=computed(()=>Object.entries(sourceFiles).find(([,text])=>String(text).includes(`implementation_id = "${definition.value?.implementation_id}"`)))
const ruleHints:Record<string,[string,string]>={
 skill_routing:['Case 中的 skill_route 条件','Trace 路由事件中记录的实际 Skill'],
 required_tool:['Case 中 required 工具调用要求','Trace 实际工具调用记录'],
 forbidden_tool:['Case 中 forbidden 工具调用要求','Trace 实际工具调用记录'],
 tool_arguments:['Case 中 tool_argument 的工具、路径与条件','Trace 对应工具调用的实际参数'],
 final_output:['Case 中 output 的路径与条件','当前轮输出'],
 final_state:['Case 中 state 的路径与条件','当前轮状态'],
 policy_compliance:['Case 中 policy 约束','Trace 中记录的策略执行证据'],
}
let openSequence=0
const dirty=computed(()=>!!selected.value&&!!edit.value&&(JSON.stringify(edit.value)!==JSON.stringify(definition.value)||description.value!==selected.value.evaluator.description))
watch([dirty,form],([changed,creating])=>emit('dirtyChange',changed||creating))
function canLeave(){return !dirty.value||window.confirm('当前评估器有未保存修改，放弃并离开？')}
function chooseItem(item:EvaluatorSummary){if(canLeave())void open(item)}
function chooseKind(k:Kind){if(!canLeave())return;kind.value=k;selected.value=null;mockSelected.value=false;edit.value=null;openSequence++;loading.value=false}
function chooseMock(){if(!canLeave())return;mockSelected.value=true;selected.value=null;edit.value=null;openSequence++;loading.value=false}
function beforeUnload(e:BeforeUnloadEvent){if(dirty.value||form.value){e.preventDefault();e.returnValue=''}}
function closeForm(done?:()=>void){if(busy.value)return;if(formSnapshot()!==formBaseline.value&&!window.confirm('放弃尚未保存的新建评估器？'))return;form.value=false;done?.()}
onUnmounted(()=>{openSequence++;emit('dirtyChange',false);window.removeEventListener('beforeunload',beforeUnload)})
const hint=computed(()=>ruleHints[definition.value?.implementation_id??''])
async function load() { loading.value=true;try {items.value=await api.evaluators();error.value=''}catch(e){error.value=String(e)}finally{loading.value=false} }
async function open(item:EvaluatorSummary) {
 mockSelected.value=false
 const sequence=++openSequence
 selected.value=null;historical.value=null; tab.value='definition';error.value='';loading.value=true
 try {const detail=await api.evaluator(item.id);if(sequence!==openSequence)return;selected.value=detail;edit.value=definition.value?JSON.parse(JSON.stringify(definition.value)):null;config.value=pretty(definition.value?.config??{});description.value=selected.value.evaluator.description;name.value=selected.value.evaluator.name}
 catch(e){if(sequence===openSequence)error.value=String(e)}finally{if(sequence===openSequence)loading.value=false}
}
function draftPayload(d:Definition) {const {kind,dimension,metric,severity,implementation_id,implementation_version,children,combination}=d;return {kind,dimension,metric,severity,implementation_id,implementation_version,children,combination,config:d.config} }
async function action(work:()=>Promise<void>) {if(busy.value)return;busy.value=true;error.value='';try {await work();await load()}catch(e){error.value=String(e)}finally{busy.value=false} }
async function createFrom(reset:unknown=true) {
 if(reset){if(!canLeave())return;name.value='';createDescription.value='';createKind.value=kind.value}error.value=''
 cloneFrom.value=createKind.value==='rule'?(createChoices.value[0]?.id??''):''
 draftEdit.value={kind:createKind.value,dimension:'answer',metric:createKind.value==='hybrid'?'composite_quality':'answer_quality',severity:'standard',implementation_id:createKind.value==='hybrid'?'composite':'answer_quality',implementation_version:'1',config:createKind.value==='llm_judge'?{model:{provider_id:'',model_id:'',credential_ref:'env:AGENTGATE_JUDGE_API_KEY'},instruction:'依据评分标准和实际执行证据评价回答质量，遵守结构化响应协议。',rubric:{scoring_guide:'回答符合事实及执行证据，并覆盖用户请求的主要内容。'},input_selection:'final_output',pass_threshold:0.8}:{pass_threshold:0.8},children:[],combination:createKind.value==='hybrid'?'weighted_score':null}
 if(createKind.value==='rule'&&cloneFrom.value)await loadClone()
 if(reset)formBaseline.value=formSnapshot()
 form.value=true
}
function cloneDefinition(value:Definition){if(!selected.value||!canLeave())return;name.value=selected.value.evaluator.name+' · 副本';createDescription.value=selected.value.evaluator.description;createKind.value=value.kind;cloneFrom.value=selected.value.evaluator.id;draftEdit.value=JSON.parse(JSON.stringify(value));formBaseline.value=formSnapshot();form.value=true}
async function loadClone(){if(!cloneFrom.value)return;try{const base=await api.evaluator(cloneFrom.value);draftEdit.value=JSON.parse(JSON.stringify(base.latest))}catch(e){error.value=String(e)}}
async function create() {await action(async()=>{if(!name.value.trim()||!draftEdit.value)throw Error('请填写名称和执行配置。');const d=draftEdit.value;const created=await request<EvaluatorDetail>('/evaluators','POST',{name:name.value.trim(),description:createDescription.value,draft:draftPayload(d)});form.value=false;kind.value=createKind.value;await open({...created.evaluator,kind:createKind.value});ElMessage.success('草稿已保存，发布后可用于评测')}) }
async function save() {await action(async()=>{if(!selected.value||!definition.value)return;const id=selected.value.evaluator.id;await request(`/evaluators/${id}`,'PATCH',{description:description.value});if(!selected.value.draft)await request(`/evaluators/${id}/drafts`,'POST',{});await request(`/evaluators/${id}/drafts/current`,'PUT',draftPayload(edit.value??definition.value));await open(selected.value.evaluator);ElMessage.success('草稿已保存')})}
async function publish() {if(dirty.value){ElMessage.warning('请先保存草稿，再发布当前配置');return}await action(async()=>{if(!selected.value)return;await request(`/evaluators/${selected.value.evaluator.id}/drafts/publish`,'POST');await open(selected.value.evaluator);ElMessage.success('新版本已发布')})}
async function toggleEnabled() {await action(async()=>{if(!selected.value)return;if(selected.value.evaluator.source==='builtin')setBuiltinEnabled(selected.value.evaluator.id,!selected.value.evaluator.enabled);else await request(`/evaluators/${selected.value.evaluator.id}`,'PATCH',{enabled:!selected.value.evaluator.enabled});await open(selected.value.evaluator);ElMessage.success('启用状态已更新')})}
onMounted(async()=>{window.addEventListener('beforeunload',beforeUnload);await load();if(props.initialId){try{const detail=await api.evaluator(props.initialId);kind.value=detail.draft?.kind??detail.latest?.kind??items.value.find(e=>e.id===props.initialId)?.kind??'rule';await open(detail.evaluator);const version=new URLSearchParams(location.hash.split('?')[1]??'').get('version');if(version){viewVersion(await request<Definition>('/evaluators/'+encodeURIComponent(props.initialId)+'/versions/'+encodeURIComponent(version)));tab.value='definition'}}catch(e){error.value=String(e)}}})
</script>
<template>
 <div class="page-head"><div><h1 class="page-title">评估器</h1><p class="page-sub">查看实际判定依据，管理可追溯的评估版本</p></div><div class="actions"><button class="secondary" @click="importOpen=true">导入评估器</button><button class="primary" :disabled="busy||kind==='hybrid'" :title="kind==='hybrid'?'当前主仓未注册复合评估执行实现':''" @click="createFrom">新建评估器</button></div></div>
 <div class="tabs"><button v-for="k in (['rule','llm_judge','hybrid'] as const)" :class="['tab',{active:kind===k}]" @click="chooseKind(k)">{{kindLabel(k)}} <span class="tag">{{items.filter(e=>e.kind===k).length}}</span></button></div>
 <div v-if="error" class="notice error" role="alert">{{error}}</div>
 <div class="evaluator-layout" v-loading="loading">
  <aside class="card evaluator-list"><input v-model="query" class="input" placeholder="搜索评估器" aria-label="搜索评估器"/><select class="input" v-model="enabledFilter" aria-label="评估器状态"><option value="all">全部状态</option><option value="enabled">已启用</option><option value="disabled">已禁用</option></select><button v-for="e in filtered" :key="e.id" :class="['evaluator-choice',{selected:selected?.evaluator.id===e.id}]" @click="chooseItem(e)"><b>{{e.name}}</b><span>{{evaluatorScenarios[e.implementation_id]??e.description??'查看配置与判定依据'}}</span><span>v{{e.latest_version??'未发布'}} · {{e.source==='builtin'?'内置':'自定义'}} · {{e.enabled?'启用':'禁用'}}</span></button><button v-if="kind!=='rule'" class="evaluator-choice" :class="{selected:mockSelected}" @click="chooseMock"><b>{{kind==='hybrid'?'综合质量评估':'回答质量评估'}} · Mock</b><span>通过 / 失败 / 异常案例 · 演示配置与输出</span></button><p v-if="!filtered.length&&kind==='rule'" class="empty">暂无匹配的规则评估器</p></aside>
  <section class="card evaluator-panel">
   <MockEvaluator v-if="mockSelected&&kind!=='rule'" :kind="kind"/><template v-else-if="selected&&definition">
    <header class="evaluator-detail-header">
      <div class="evaluator-heading"><h2>{{selected.evaluator.name}}</h2><div class="evaluator-badges"><span class="tag">{{selected.evaluator.source==='builtin'?'内置只读':'用户定义'}}</span><span class="muted">{{kindLabel(definition.kind)}} · {{historical?'v'+definition.version+' · 已发布':selected.draft?'当前草稿':'v'+definition.version+' · 已发布'}}</span><span class="badge" :class="selected.evaluator.enabled?'success':'info'">{{selected.evaluator.enabled?'已启用':'未启用'}}</span></div></div>
      <div class="evaluator-actions"><button class="secondary" :title="enabledReason" :disabled="busy||!selected.latest||dirty" @click="toggleEnabled">{{selected.evaluator.enabled?'禁用':'启用'}}</button><button class="primary" :disabled="busy||!selected.evaluator.enabled||!selected.latest||dirty" @click="emit('launch',selected.evaluator.id)">发起评测</button></div>
      <p class="evaluator-status-note">{{selected.evaluator.source==='builtin'?'内置评估器启停保存在当前浏览器，影响本页面新建任务、A/B 实验及重跑；历史报告和其他客户端不受影响。清除浏览器数据会重置。':!selected.latest?'尚无发布版本：保存并发布草稿后，启用即可发起评测。':!selected.evaluator.enabled?'当前未启用；启用后可用于新任务，历史结果不受影响。':'新任务使用已发布版本；草稿修改不会影响历史结果。'}}</p>
    </header>
   <EvaluatorVersions v-if="selected" :key="selected.evaluator.id+String(selected.draft?.content_sha256)+String(selected.latest?.version)" :item="selected" :active-version="historical?.version" :unsaved="dirty" :disabled="busy" @clone="cloneDefinition" @select="viewVersion" @busy="busy=$event" @refresh="open(selected.evaluator)" @removed="selected=null;load()"/>
    <div class="tabs"><button v-for="t in [['definition','判定依据'],['source','实现源码']]" :class="['tab',{active:tab===t[0]}]" @click="tab=t[0]">{{t[1]}}</button></div>
    <div v-if="tab==='definition'" class="detail-content"><section class="recommendation-reason" aria-label="推荐理由"><h3>推荐理由</h3><p>{{evaluatorRecommendationReasons[definition.implementation_id]??'此自定义实现暂无预设推荐理由，请根据检查目标与样本约束确认是否适用。'}}</p></section>
     <template v-if="definition.kind==='rule'"><div class="grid two-columns"><section class="mini-card"><h3>检查什么</h3><p>{{hint?.[0]??definition.metric}}</p></section><section class="mini-card"><h3>读取内容</h3><p>{{hint?.[1]??'评测运行中的 Trace'}}</p></section></div></template>
     <template v-else-if="definition.kind==='llm_judge'"><h3>评分输入范围</h3><p>{{definition.config.input_selection??'由实现默认值决定'}}</p><h3>评估提示词</h3><pre>{{definition.config.instruction??'使用实现默认指令，详见源码'}}</pre><h3>评分标准</h3><pre>{{pretty(definition.config.rubric??{})}}</pre></template>
     <template v-else><h3>子评估器</h3><table class="data-table"><thead><tr><th>评估器</th><th>版本</th><th>权重</th></tr></thead><tbody><tr v-for="c in definition.children"><td>{{c.evaluator_id}}</td><td>{{c.evaluator_version}}</td><td>{{c.weight??'—'}}</td></tr></tbody></table><p>组合方式：{{definition.combination}}</p></template>
    </div>
    <div v-else-if="tab==='source'" class="detail-content"><p class="muted">{{source?.[0]?.split('/agentgate/')[1]??'未找到对应源码'}}</p><pre v-if="source" class="source-code">{{source[1]}}</pre><p v-else class="empty">当前版本未包含此实现源码，不展示推测内容。</p></div>
    <div v-else class="detail-content"><label class="field">备注说明<textarea class="input" rows="3" v-model="description" :readonly="readOnly"/></label><EvaluatorEditor v-if="edit&&definition.kind!=='rule'" v-model="edit" :items="items" :disabled="readOnly"/><div v-if="!readOnly" class="form-footer"><button class="secondary" :disabled="busy" @click="save">保存草稿</button><span v-if="dirty" class="muted">有未保存的修改，请先保存草稿。</span><button class="primary" :disabled="busy||!selected.draft||dirty" @click="publish">发布新版本</button></div></div>
   </template>
   <div v-else class="empty"><h2>选择一个{{kindLabel(kind)}}</h2><p>{{kind==='hybrid'?'点击“新建评估器”，选择子评估器版本并设置总计 100% 的权重。':'左侧选择后查看判定依据、配置和实现源码。'}}</p></div>
  </section>
 </div>
 <EvaluatorImport v-if="importOpen" @close="importOpen=false" @imported="importOpen=false;load()"/>
 <el-dialog v-model="form" title="新建评估器草稿" width="min(680px,94vw)" :close-on-click-modal="false" :before-close="closeForm"><div v-if="error" class="notice error">{{error}}</div><div class="form-grid"><label class="field full">名称<input class="input" v-model="name"/></label><label class="field full">类型<select class="input" aria-label="评估器类型" v-model="createKind" @change="createFrom(false)"><option value="rule">规则</option><option value="llm_judge">LLM</option><option value="hybrid" disabled>复合（当前执行实现未注册）</option></select></label><label v-if="createChoices.some(e=>e.latest_version)" class="field full">{{createKind==='rule'?'基于已注册实现':'可选：复制已有发布配置'}}<select class="input" v-model="cloneFrom" @change="loadClone"><option v-if="createKind!=='rule'" value="">使用空白配置</option><option v-for="e in createChoices.filter(x=>x.latest_version)" :value="e.id">{{e.name}} · v{{e.latest_version}}</option></select></label><label class="field full">备注说明<textarea class="input" rows="3" v-model="createDescription"/></label></div><EvaluatorEditor v-if="draftEdit&&createKind!=='rule'" v-model="draftEdit" :items="items"/><template #footer><button class="secondary" @click="closeForm()">取消</button><button class="primary" :disabled="busy" @click="create">保存草稿</button></template></el-dialog>
</template>

<style scoped>
.recommendation-reason{margin:18px 0;padding:14px 18px;background:#f3f8f6;border-radius:8px}.recommendation-reason h3{margin:0 0 8px;font-size:16px}.recommendation-reason p{margin:0;line-height:1.7}
.evaluator-detail-header{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px 24px;padding:4px 0 22px;margin-bottom:20px;border-bottom:1px solid #e5eaf0}
.evaluator-heading h2{font-size:24px;line-height:1.4;margin:0 0 12px;overflow-wrap:anywhere}
.evaluator-badges{display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:13px}
.evaluator-badges .tag{border-radius:5px;padding:3px 8px}
.evaluator-actions{display:flex;align-items:flex-start;gap:12px;padding-top:4px}
.evaluator-actions button{white-space:nowrap}
.evaluator-status-note{grid-column:1/-1;margin:0;color:#64748b;font-size:13px;line-height:1.6}
@media(max-width:800px){.evaluator-detail-header{grid-template-columns:1fr}.evaluator-actions{justify-content:flex-start}}
</style>
