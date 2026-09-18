<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {api,request,pretty} from './api'
import {previewSources,type MergeSource,mergeService} from './merge-preview'
const emit=defineEmits<{close:[]}>()
const mode=ref('demo'),step=ref(1),busy=ref(false),error=ref(''),name=ref('多 Skill 综合回归集')
const catalog=ref<any[]>([]),chosen=ref<string[]>([]),histories=ref<Record<string,any[]>>({}),versions=ref<Record<string,number>>({})
const sources=ref<MergeSource[]>([]),confirmations=ref<Record<string,boolean>>({}),collapse=ref(false)
const excluded=ref<string[]>([])
const allRows=computed(()=>previewSources(sources.value).rows)
const result=computed(()=>previewSources(sources.value.map(s=>({...s,cases:s.cases.filter(c=>!excluded.value.includes(JSON.stringify([s.dataset_id,s.version,c.id])))}))))
const retained=computed(()=>result.value.rows.filter(r=>!collapse.value||!result.value.duplicates.some(g=>g.slice(1).some(x=>x.key===r.key))))
function provenance(row:any){return (collapse.value?result.value.duplicates.find(g=>g.some(x=>x.key===row.key)):null)??[row]}
watch([excluded,collapse],()=>confirmations.value={}, {deep:true})
const outputCount=computed(()=>result.value.rows.length-(collapse.value?result.value.duplicates.reduce((n,g)=>n+g.length-1,0):0))
const pending=computed(()=>result.value.differences.filter(g=>!confirmations.value[g[0]!.key]).length)
function reset(){step.value=1;sources.value=[];excluded.value=[];confirmations.value={};collapse.value=false;error.value=''}
onMounted(async()=>{try{catalog.value=(await api.datasets()).filter(d=>d.version!==null&&!d.archived)}catch(e){error.value=String(e)}})
async function select(id:string){
 if(!chosen.value.includes(id)||histories.value[id])return
 try{const d=await request<any>('/datasets/'+encodeURIComponent(id));histories.value[id]=d.versions.filter((v:any)=>v.status==='published');versions.value[id]=histories.value[id]![0]?.version}catch(e){error.value=String(e)}
}
function demoSources():MergeSource[]{
 const sample=(id:string,skill:string,output:string)=>({id,name:'业务场景 '+id,initial_state:{},turns:[{id:'turn-'+id,input:{query:'处理申请'},expectations:[{id:'route-'+id,kind:'skill_route',condition:{kind:'equals',expected:skill}},{id:'out-'+id,kind:'output',path:null,condition:{kind:'equals',expected:output}}]}]})
 const original=sample('approval-a','loan_approval','人工复核')
 return [{dataset_id:'demo-a',name:'演示 · 审批回归',version:1,content_sha256:'演示',cases:[original]},
 {dataset_id:'demo-b',name:'演示 · 综合业务',version:2,content_sha256:'演示',cases:[{...original,id:'approval-copy'},sample('credit-a','credit_inquiry','返回征信结果')]}]
}
async function inspect(){
 if(busy.value)return;busy.value=true;error.value=''
 try{
  if(mode.value==='demo')sources.value=demoSources()
  else{
   if(chosen.value.length<2)throw Error('请选择至少两个不同的评测集及发布版本')
   sources.value=await Promise.all(chosen.value.map(async id=>{
    if(!versions.value[id])throw Error('请选择来源发布版本')
    const v=await request<any>('/datasets/'+encodeURIComponent(id)+'/versions/'+versions.value[id])
    return {dataset_id:id,name:catalog.value.find(d=>d.id===id)?.name,version:v.version,content_sha256:v.content_sha256,cases:v.cases}
   }))
   if(sources.value.reduce((n,s)=>n+s.cases.length,0)>500){sources.value=[];throw Error('本地预览最多 500 条用例，请缩小来源范围。此限制不是后端能力声明。')}
  }
  confirmations.value={};excluded.value=[];step.value=2
 }catch(e){error.value=String(e)}finally{busy.value=false}
}
function downloadPlan(){
 const plan={kind:'local_merge_plan',server_validated:false,name:name.value,sources:sources.value.map(({cases,...s})=>({...s,case_ids:cases.filter(c=>!excluded.value.includes(JSON.stringify([s.dataset_id,s.version,c.id]))).map(c=>c.id)})),output_sources:retained.value.map(r=>provenance(r).map(x=>({dataset_id:x.source.dataset_id,version:x.source.version,case_id:x.item.id}))),duplicate_policy:collapse.value?'suggest_collapse_exact':'keep_all',differences:result.value.differences.map(g=>({sources:g.map(r=>({dataset_id:r.source.dataset_id,version:r.source.version,case_id:r.item.id})),decision:confirmations.value[g[0]!.key]?'keep_separate':'unresolved'}))}
 const url=URL.createObjectURL(new Blob([pretty(plan)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='merge-plan-2026-09-14.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
</script>
<template>
 <section class="card merge-workspace">
  <div class="toolbar"><h1>合并现有评测集</h1><button class="secondary" @click="emit('close')">返回评测集</button></div>
  <p class="muted" role="status">{{mode==='demo'?'交互演示 · 不创建真实资产':'本地预览 · 源数据只读，未经服务端验证'}}</p>
  <nav class="tabs" aria-label="合并步骤"><span v-for="(label,i) in ['选择来源','检查合并','确认差异','生成草稿']" :class="['tab',{active:step===i+1}]">{{i+1}}. {{label}}</span></nav>
  <p v-if="error" class="notice error" role="alert">{{error}}</p>
  <template v-if="step===1">
   <label class="field">预览数据<select class="input" aria-label="合并预览数据" v-model="mode" @change="reset"><option value="demo">内置演示样例</option><option value="local">读取已发布版本进行本地预览</option></select></label>
   <p v-if="mode==='demo'">演示包含完全一致候选与同输入不同期望；合并只整理用例，不合并 Skill 代码或串接独立对话。</p>
   <table v-else class="data-table"><thead><tr><th>选择来源</th><th>发布版本</th></tr></thead><tbody><tr v-for="d in catalog" :key="d.id"><td><label><input type="checkbox" :value="d.id" v-model="chosen" @change="select(d.id)"/> {{d.name}}</label><small>{{d.id}}</small></td><td><select v-if="chosen.includes(d.id)" class="input" :aria-label="d.name+'来源版本'" v-model="versions[d.id]"><option v-for="v in histories[d.id]" :value="v.version">v{{v.version}} · {{v.cases.length}} 条</option></select></td></tr></tbody></table>
   <div class="form-footer"><button class="primary" :disabled="busy" @click="inspect">{{busy?'读取中…':'检查合并'}}</button></div>
  </template>
  <template v-else>
   <div class="grid two-columns"><article class="mini-card" v-for="s in sources"><b>{{s.name}} · v{{s.version}}</b><p>{{s.cases.length}} 条来源用例</p></article></div>
   <p>已选 {{result.rows.length}} / {{allRows.length}} 条 · 完全一致候选 {{result.duplicates.length}} 组 · 待确认差异 {{pending}} 组 · 预计保留 {{outputCount}} 条</p>
   <template v-if="step===2">
    <label v-if="result.duplicates.length"><input type="checkbox" v-model="collapse"/> 预览中折叠完全一致项，保留全部来源</label>
    <table class="data-table"><thead><tr><th>纳入计划</th><th>用例</th><th>来源版本</th><th>Skill 线索（非兼容性证明）</th></tr></thead><tbody><tr v-for="r in allRows" :key="r.key"><td><input type="checkbox" :aria-label="'纳入 '+r.source.name+' '+r.item.name" :checked="!excluded.includes(r.key)" @change="excluded=($event.target as HTMLInputElement).checked?excluded.filter(key=>key!==r.key):[...excluded,r.key]"/></td><td>{{r.item.name}}</td><td>{{r.source.name}} · v{{r.source.version}}</td><td>{{r.skills.join('、')||'待确认'}}</td></tr></tbody></table>
   </template>
   <template v-if="step===3">
    <p v-if="!result.differences.length">没有检测到同输入不同内容的差异，不代表业务等价已被验证。</p>
    <article v-for="g in result.differences" :key="g[0]!.key" class="mini-card section-gap"><h3>相同输入，不同场景或期望</h3><div class="grid two-columns"><div v-for="r in g"><b>{{r.source.name}} · {{r.item.name}}</b><pre>{{pretty(r.item)}}</pre></div></div><label><input type="checkbox" v-model="confirmations[g[0]!.key]"/> 已核对：保留为不同场景，不拼接期望或轮次</label></article>
   </template>
   <template v-if="step===4"><h3>预计保留用例与来源 · {{retained.length}} 条</h3><table class="data-table"><thead><tr><th>用例</th><th>来源版本 / 原用例</th><th>Skill 线索</th></tr></thead><tbody><tr v-for="r in retained" :key="r.key"><td>{{r.item.name}}</td><td><p v-for="p in provenance(r)">{{p.source.name}} · v{{p.source.version}} · {{p.item.id}}</p></td><td>{{r.skills.join('、')||'待确认'}}</td></tr></tbody></table><label class="field">计划名称<input class="input" v-model="name"/></label><p>{{mergeService.reason}}</p><button class="secondary" :disabled="!name.trim()" @click="downloadPlan">导出计划清单（不含用例正文）</button><button class="primary" disabled>生成草稿 · 待后端接入</button></template>
   <div class="form-footer"><button class="secondary" @click="step--">上一步</button><button v-if="step<4" class="primary" :disabled="result.rows.length===0||(step===3&&pending>0)" @click="step++">下一步</button></div>
  </template>
 </section>
</template>
<style scoped>small{display:block;color:#64748b}pre{max-height:320px;overflow:auto;white-space:pre-wrap}.merge-workspace input[type=checkbox]{accent-color:#07ac8e}</style>
