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
const library=ref('builtin'),typeFilter=ref(''),dimensionFilter=ref('')
const dimensionLabel=(v:string)=>({routing:'技能路由',tool_use:'工具调用',state:'业务状态',answer:'回答质量',safety:'安全合规'} as Record<string,string>)[v]??v
const dimensions=computed(()=>[...new Set(items.value.filter(e=>(e.source==='builtin')===(library.value==='builtin')).map(e=>e.dimension))])
function resetFilters(){query.value='';typeFilter.value='';dimensionFilter.value='';enabledFilter.value='all'}
function closeDetail(done?:()=>void){if(busy.value)return;if(canLeave()){selected.value=null;edit.value=null;openSequence++;loading.value=false;done?.()}}
function selectLibrary(v:string){if(!canLeave())return;closeDetail();library.value=v;resetFilters()}
const filtered=computed(()=>items.value.filter(e=>(e.source==='builtin')===(library.value==='builtin') && (!typeFilter.value||e.kind===typeFilter.value) && (!dimensionFilter.value||e.dimension===dimensionFilter.value) && (enabledFilter.value==='all'||e.enabled===(enabledFilter.value==='enabled')) && `${e.name} ${e.description} ${e.metric}`.toLowerCase().includes(query.value.toLowerCase())))
const enabledReason=computed(()=>!selected.value?'':!selected.value.latest?'请先发布草稿，再启用评估器。':dirty.value?'请先保存当前修改。':busy.value?'操作处理中，请稍候。':'')
const historical=ref<Definition|null>(null)
const definition=computed(()=>historical.value??(selected.value?.evaluator.kind==='rule'?selected.value?.latest:selected.value?.draft??selected.value?.latest))
const readOnly=computed(()=>definition.value?.kind==='rule'||!!historical.value||!selected.value?.draft||selected.value?.evaluator.source==='builtin')
function viewVersion(value:Definition|null){historical.value=value;edit.value=definition.value?JSON.parse(JSON.stringify(definition.value)):null}
const sourceFiles=import.meta.glob('../../../src/agentgate/evaluator/{rule/*.py,judge/*.py,hybrid.py}',{eager:true,query:'?raw',import:'default'})
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
 try {const detail=await api.evaluator(item.id);if(sequence!==openSequence)return;selected.value=detail;tab.value=detail.draft&&detail.draft.kind!=='rule'&&detail.evaluator.source!=='builtin'?'design':'overview';edit.value=definition.value?JSON.parse(JSON.stringify(definition.value)):null;config.value=pretty(definition.value?.config??{});description.value=selected.value.evaluator.description;name.value=selected.value.evaluator.name}
 catch(e){if(sequence===openSequence)error.value=String(e)}finally{if(sequence===openSequence)loading.value=false}
}
function draftPayload(d:Definition) {const {kind,dimension,metric,severity,implementation_id,implementation_version,children,combination}=d;return {kind,dimension,metric,severity,implementation_id,implementation_version,children,combination,config:d.config} }
async function action(work:()=>Promise<void>) {if(busy.value)return;busy.value=true;error.value='';try {await work();await load()}catch(e){error.value=String(e)}finally{busy.value=false} }
async function createFrom(reset:unknown=true) {
 if(reset){if(!canLeave())return;name.value='';createDescription.value='';createKind.value=typeFilter.value==='hybrid'?'hybrid':'llm_judge'}
 if(createKind.value==='rule'){error.value='规则评估器不支持新建草稿';return}error.value=''
 cloneFrom.value=''
 draftEdit.value={kind:createKind.value,dimension:'answer',metric:createKind.value==='hybrid'?'composite_quality':'answer_quality',severity:'standard',implementation_id:createKind.value==='hybrid'?'composite':'answer_quality',implementation_version:'1',config:createKind.value==='llm_judge'?{model:{provider_id:'',model_id:'',credential_ref:'env:AGENTGATE_JUDGE_API_KEY'},instruction:'依据评分标准和实际执行证据评价回答质量，遵守结构化响应协议。',rubric:{scoring_guide:'回答符合事实及执行证据，并覆盖用户请求的主要内容。'},input_selection:'final_output',pass_threshold:0.8}:{pass_threshold:0.8},children:[],combination:createKind.value==='hybrid'?'weighted_score':null}
 if(reset)formBaseline.value=formSnapshot()
 form.value=true
}
function cloneDefinition(value:Definition){if(value.kind==='rule')return;if(!selected.value||!canLeave())return;name.value=selected.value.evaluator.name+' · 副本';createDescription.value=selected.value.evaluator.description;createKind.value=value.kind;cloneFrom.value=selected.value.evaluator.id;draftEdit.value=JSON.parse(JSON.stringify(value));formBaseline.value=formSnapshot();form.value=true}
async function loadClone(){if(!cloneFrom.value)return;try{const base=await api.evaluator(cloneFrom.value);draftEdit.value=JSON.parse(JSON.stringify(base.latest))}catch(e){error.value=String(e)}}
async function create() {await action(async()=>{if(!name.value.trim()||!draftEdit.value)throw Error('请填写名称和执行配置。');const d=draftEdit.value;const created=await request<EvaluatorDetail>('/evaluators','POST',{name:name.value.trim(),description:createDescription.value,draft:draftPayload(d)});form.value=false;kind.value=createKind.value;await open({...created.evaluator,kind:createKind.value});ElMessage.success('草稿已保存，发布后可用于评测')}) }
async function save() {await action(async()=>{if(!selected.value||!definition.value)return;const id=selected.value.evaluator.id;await request(`/evaluators/${id}`,'PATCH',{description:description.value});if(!selected.value.draft)await request(`/evaluators/${id}/drafts`,'POST',{});await request(`/evaluators/${id}/drafts/current`,'PUT',draftPayload(edit.value??definition.value));await open(selected.value.evaluator);ElMessage.success('草稿已保存')})}
async function publish() {if(dirty.value){ElMessage.warning('请先保存草稿，再发布当前配置');return}await action(async()=>{if(!selected.value)return;await request(`/evaluators/${selected.value.evaluator.id}/drafts/publish`,'POST');await open(selected.value.evaluator);ElMessage.success('新版本已发布')})}
async function toggleEnabled() {await action(async()=>{if(!selected.value)return;if(selected.value.evaluator.source==='builtin')setBuiltinEnabled(selected.value.evaluator.id,!selected.value.evaluator.enabled);else await request(`/evaluators/${selected.value.evaluator.id}`,'PATCH',{enabled:!selected.value.evaluator.enabled});await open(selected.value.evaluator);ElMessage.success('启用状态已更新')})}
onMounted(async()=>{window.addEventListener('beforeunload',beforeUnload);await load();if(props.initialId){try{const detail=await api.evaluator(props.initialId);kind.value=detail.draft?.kind??detail.latest?.kind??items.value.find(e=>e.id===props.initialId)?.kind??'rule';await open(detail.evaluator);const version=new URLSearchParams(location.hash.split('?')[1]??'').get('version');if(version){viewVersion(await request<Definition>('/evaluators/'+encodeURIComponent(props.initialId)+'/versions/'+encodeURIComponent(version)));tab.value='definition'}}catch(e){error.value=String(e)}}})
</script>
<template>
 <div class="page-head"><div><span class="catalog-eyebrow">评估器模板库</span><h1 class="page-title">评估器</h1><p class="page-sub">按类型与评估场景筛选，查看设计内容及执行入口。</p></div><div class="actions"><button class="secondary" :disabled="busy" @click="load">刷新</button><button class="secondary" @click="importOpen=true">导入评估器</button><button v-if="library==='user'&&(typeFilter==='llm_judge'||typeFilter==='hybrid')" class="primary" :disabled="busy" @click="createFrom">新建{{typeFilter==='hybrid'?'复合':' LLM '}}评估器</button></div></div>
 <div class="tabs catalog-tabs"><button v-for="entry in [['user','自建评估器'],['builtin','预置评估器']]" :key="entry[0]" :class="['tab',{active:library===entry[0]}]" @click="selectLibrary(entry[0])">{{entry[1]}}</button></div>
 <div v-if="error" class="notice error" role="alert">{{error}}</div>
 <div class="catalog-layout" v-loading="loading">
 <aside class="catalog-filters" aria-label="评估器筛选"><div class="filter-heading"><b>评估器筛选</b><button class="link" @click="resetFilters">清空</button></div>
 <h3>类型</h3><div class="filter-chips"><button v-for="k in (['rule','llm_judge','hybrid'] as const)" :class="{active:typeFilter===k}" :aria-pressed="typeFilter===k" @click="typeFilter=typeFilter===k?'':k;kind=k">{{kindLabel(k)}}</button></div>
 <h3>场景</h3><div class="filter-chips"><button v-for="d in dimensions" :key="d" :class="{active:dimensionFilter===d}" :aria-pressed="dimensionFilter===d" @click="dimensionFilter=dimensionFilter===d?'':d">{{dimensionLabel(d)}}</button></div>
 <h3>状态</h3><select class="input" v-model="enabledFilter" aria-label="评估器状态"><option value="all">全部状态</option><option value="enabled">已启用</option><option value="disabled">已禁用</option></select>
 </aside>
 <main class="catalog-main"><input v-model="query" class="input catalog-search" placeholder="搜索评估器名称、说明或指标" aria-label="搜索评估器"/>
 <div class="evaluator-cards"><button v-for="e in filtered" :key="e.id" class="evaluator-catalog-card" @click="chooseItem(e)">
 <div class="catalog-card-heading"><h2>{{e.name}}</h2><span class="tag">{{kindLabel(e.kind)}}</span></div>
 <p>{{evaluatorScenarios[e.implementation_id]??e.description??'查看配置与判定依据'}}</p><span class="card-open">点击查看详情 →</span>
 <div class="catalog-tags"><span>{{e.source==='builtin'?'预置':'自建'}}</span><span>{{dimensionLabel(e.dimension)}}</span><span>{{e.latest_version?'v'+e.latest_version:'未发布草稿'}}</span></div>
 <div class="catalog-metric"><small>评估指标</small><strong>{{e.metric}}</strong></div>
 <div class="catalog-card-bottom"><span class="badge" :class="e.enabled&&e.latest_version?'success':'info'">{{!e.latest_version?'待发布':e.enabled?'已启用':'未启用'}}</span><span v-if="e.has_draft&&e.kind!=='rule'">有草稿</span></div>
 </button></div><p v-if="!filtered.length" class="card empty">暂无匹配的评估器</p></main></div>
 <el-dialog :model-value="!!selected" title="评估器详情" width="min(1060px,94vw)" :close-on-click-modal="false" :before-close="closeDetail" class="evaluator-detail-dialog">
  <section class="card evaluator-panel">
   <MockEvaluator v-if="mockSelected&&kind!=='rule'" :kind="kind"/><template v-else-if="selected&&definition">
    <header class="evaluator-detail-header">
      <div class="evaluator-heading"><h2>{{selected.evaluator.name}}</h2><div class="evaluator-badges"><span class="tag">{{selected.evaluator.source==='builtin'?'内置只读':'用户定义'}}</span><span class="muted">{{kindLabel(definition.kind)}} · {{historical?'v'+definition.version+' · 已发布':selected.draft?'当前草稿':'v'+definition.version+' · 已发布'}}</span><span class="badge" :class="selected.evaluator.enabled?'success':'info'">{{selected.evaluator.enabled?'已启用':'未启用'}}</span></div></div>
      <div class="evaluator-actions"><button class="secondary" :title="enabledReason" :disabled="busy||!selected.latest||dirty" @click="toggleEnabled">{{selected.evaluator.enabled?'禁用':'启用'}}</button><button class="primary" :disabled="busy||!selected.evaluator.enabled||!selected.latest||dirty" @click="emit('launch',selected.evaluator.id)">发起评测</button></div>
      <p class="evaluator-status-note">{{selected.evaluator.source==='builtin'?'内置评估器启停保存在当前浏览器，影响本页面新建任务、A/B 实验及重跑；历史报告和其他客户端不受影响。清除浏览器数据会重置。':!selected.latest?'尚无发布版本：保存并发布草稿后，启用即可发起评测。':!selected.evaluator.enabled?'当前未启用；启用后可用于新任务，历史结果不受影响。':'新任务使用已发布版本；草稿修改不会影响历史结果。'}}</p>
    </header>
   <EvaluatorVersions v-if="selected&&definition.kind!=='rule'" :key="selected.evaluator.id+String(selected.draft?.content_sha256)+String(selected.latest?.version)" :item="selected" :allow-create="true" :active-version="historical?.version" :unsaved="dirty" :disabled="busy" @clone="cloneDefinition" @select="viewVersion" @busy="busy=$event" @refresh="open(selected.evaluator)" @removed="selected=null;load()"/>
    <div class="evaluator-display-tags" aria-label="评估器属性"><span>{{selected.evaluator.source==='builtin'?'预置':'自建'}}</span><span>{{definition.kind==='rule'?'代码':definition.kind==='llm_judge'?'llm':'复合'}}</span><span>{{!readOnly?'可编辑':'仅看结果'}}</span></div>
    <div v-if="readOnly" class="evaluator-overview">
<section><h3>描述</h3><p>{{selected.evaluator.description||evaluatorScenarios[definition.implementation_id]||'暂无描述'}}</p></section>
<section><h3>应用场景</h3><p>{{dimensionLabel(definition.dimension)}} · {{evaluatorScenarios[definition.implementation_id]||'以当前评估器配置为准'}}</p></section>
<section><h3>前置条件</h3><p>{{definition.kind==='rule'?(hint?.[0]||'样本包含此规则对应的期望条件')+'；运行结果提供对应执行证据。':definition.kind==='llm_judge'?'配置有效的模型引用、评分提示词及评分标准，并提供所选范围的执行内容。':'子评估器版本必须存在，且服务端已注册对应组合实现。'}}</p></section>
<section><h3>输出</h3><p>评估指标：{{definition.metric}} · 判定状态、可用评分与证据；具体结构以实现为准。</p></section>
<section><h3>结果呈现位置</h3><p>评测任务 → 查看详情 → 评测结果 → 样本评估明细</p></section>
</div>
    <div v-else class="detail-content"><label class="field">备注说明<textarea class="input" rows="3" v-model="description" :readonly="readOnly"/></label><EvaluatorEditor v-if="edit" v-model="edit" :items="items" :disabled="readOnly"/><div v-if="!readOnly" class="form-footer"><button class="secondary" :disabled="busy" @click="save">保存草稿</button><span v-if="dirty" class="muted">有未保存的修改，请先保存草稿。</span><button class="primary" :disabled="busy||!selected.draft||dirty" @click="publish">发布新版本</button></div></div>
   </template>
   <div v-else class="empty"><h2>选择一个{{kindLabel(kind)}}</h2><p>{{kind==='hybrid'?'点击“新建评估器”，选择子评估器版本并设置总计 100% 的权重。':'左侧选择后查看判定依据、配置和实现源码。'}}</p></div>
  </section>
 <template #footer><button class="secondary" @click="closeDetail()">关闭</button></template></el-dialog>
 <EvaluatorImport v-if="importOpen" @close="importOpen=false" @imported="importOpen=false;load()"/>
 <el-dialog v-model="form" title="新建评估器草稿" width="min(680px,94vw)" :close-on-click-modal="false" :before-close="closeForm"><div v-if="error" class="notice error">{{error}}</div><div class="form-grid"><label class="field full">名称<input class="input" v-model="name"/></label><label class="field full">类型<select class="input" aria-label="评估器类型" v-model="createKind" @change="createFrom(false)"><option value="llm_judge">LLM</option><option value="hybrid">复合</option></select></label><label v-if="createChoices.some(e=>e.latest_version)" class="field full">{{createKind==='rule'?'基于已注册实现':'可选：复制已有发布配置'}}<select class="input" v-model="cloneFrom" @change="loadClone"><option v-if="createKind!=='rule'" value="">使用空白配置</option><option v-for="e in createChoices.filter(x=>x.latest_version)" :value="e.id">{{e.name}} · v{{e.latest_version}}</option></select></label><label class="field full">备注说明<textarea class="input" rows="3" v-model="createDescription"/></label></div><EvaluatorEditor v-if="draftEdit" v-model="draftEdit" :items="items"/><template #footer><button class="secondary" @click="closeForm()">取消</button><button class="primary" :disabled="busy" @click="create">保存草稿</button></template></el-dialog>
</template>

<style scoped>
.evaluator-display-tags{display:flex;gap:10px;margin:18px 0}.evaluator-display-tags span{color:#008b73;background:#edf8f4;border:1px solid #b9dfd1;border-radius:6px;padding:8px 14px;font-size:14px}
.evaluator-panel{border:0;box-shadow:none;padding:0}.evaluator-overview{display:grid;gap:18px;padding-top:20px}.evaluator-overview h3{font-size:14px;color:#008b73;margin:0 0 9px}.evaluator-overview p{background:#f6f8f7;border:1px solid #e4e9e6;border-radius:10px;padding:16px;margin:0;line-height:1.8;color:#59675f}

.catalog-eyebrow{font-size:12px;color:#7b8983}.catalog-tabs{margin-bottom:0}.catalog-layout{display:grid;grid-template-columns:235px minmax(0,1fr);background:white;border:1px solid #e2e7e5;border-radius:0 0 12px 12px;min-height:600px}.catalog-filters{padding:24px 20px;border-right:1px solid #e2e7e5}.filter-heading{display:flex;justify-content:space-between;align-items:center}.catalog-filters h3{font-size:13px;color:#778079;margin:26px 0 12px}.filter-chips{display:flex;flex-wrap:wrap;gap:8px}.filter-chips button{background:white;border:1px solid #dce3df;border-radius:8px;padding:9px 12px;cursor:pointer;color:#58635d}.filter-chips button.active{background:#e9f7f2;border-color:#0aaa89;color:#007d65}.catalog-main{padding:24px;min-width:0}.catalog-search{width:100%;margin-bottom:20px}.evaluator-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.evaluator-catalog-card{text-align:left;display:flex;flex-direction:column;gap:14px;background:white;border:1px solid #dde5e1;border-radius:12px;padding:22px;cursor:pointer;color:#25362e;min-width:0;transition:box-shadow .15s,border-color .15s}.evaluator-catalog-card:hover{border-color:#5fb49c;box-shadow:0 5px 20px #174c2d0a}.evaluator-catalog-card:focus-visible{outline:2px solid #08a786;outline-offset:2px}.catalog-card-heading{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.catalog-card-heading h2{font-size:18px;line-height:1.4;margin:0;overflow-wrap:anywhere}.catalog-card-heading .tag{font-size:11px;white-space:nowrap}.evaluator-catalog-card p{font-size:13px;line-height:1.7;color:#66716c;margin:0}.card-open{font-size:12px;color:#87928b}.catalog-tags{display:flex;flex-wrap:wrap;gap:7px}.catalog-tags span{font-size:11px;background:#eff7f3;color:#40836a;border-radius:4px;padding:5px 7px}.catalog-metric{margin-top:auto;background:#f6f8f7;border:1px solid #e9edeb;border-radius:8px;padding:12px;display:grid;gap:6px;overflow-wrap:anywhere}.catalog-metric small{color:#819087}.catalog-metric strong{font-size:13px;font-weight:500}.catalog-card-bottom{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#849188}.catalog-back{margin:20px 0}.catalog-filters .muted{font-size:12px;line-height:1.7}@media(max-width:1100px){.catalog-layout{grid-template-columns:200px minmax(0,1fr)}.evaluator-cards{grid-template-columns:1fr}}@media(max-width:700px){.catalog-layout{grid-template-columns:1fr}.catalog-filters{border-right:0;border-bottom:1px solid #e2e7e5}.catalog-main{padding:16px}}

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
