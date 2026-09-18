<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {api,request,type DatasetSummary} from './api'
const props=defineProps<{skillIds:string[];title:string;targetVersion:string}>()
const emit=defineEmits<{close:[];run:[source:{id:string;version:number;caseIds:string[];targetVersion:string}]}>()
const datasets=ref<DatasetSummary[]>([]),dataset=ref(''),versions=ref<any[]>([]),version=ref<number|null>(null),selected=ref<string[]>([]),onlyRelated=ref(true),error=ref(''),busy=ref(false)
let ticket=0
const cases=computed(()=>versions.value.find(v=>v.version===version.value)?.cases??[])
function skills(c:any):string[]{return [...new Set<string>(c.turns.flatMap((t:any)=>t.expectations.filter((e:any)=>e.kind==='skill_route'&&e.condition?.kind==='equals'&&typeof e.condition?.expected==='string').map((e:any)=>e.condition.expected)))]}
const rows=computed(()=>cases.value.filter((c:any)=>!onlyRelated.value||!props.skillIds.length||skills(c).some(id=>props.skillIds.includes(id))))
watch(version,()=>selected.value=[])
watch(onlyRelated,()=>selected.value=[])
watch(dataset,async id=>{const current=++ticket;versions.value=[];version.value=null;error.value='';busy.value=true;try{const d=await request<{versions:any[]}>('/datasets/'+encodeURIComponent(id));if(ticket===current){versions.value=d.versions.filter(v=>v.status==='published');version.value=versions.value[0]?.version??null}}catch(e){if(ticket===current)error.value=String(e)}finally{if(ticket===current)busy.value=false}})
onMounted(async()=>{try{datasets.value=(await api.datasets()).filter(d=>d.version!==null&&!d.archived)}catch(e){error.value=String(e)}})
onUnmounted(()=>ticket++)
function submit(){if(!busy.value&&version.value!==null&&selected.value.length)emit('run',{id:dataset.value,version:version.value,caseIds:[...selected.value],targetVersion:props.targetVersion})}
</script>
<template>
 <el-dialog :model-value="true" title="选择验证用例" width="min(860px,94vw)" @close="emit('close')">
  <p><b>{{title}}</b></p><p class="muted">从发布版选择用例，下一步确认智能体和评估器。Skill 命中只是检索线索，不代表已覆盖风险；本次不保存发现项与用例的长期关联。</p>
  <p v-if="error" role="alert">{{error}}</p>
  <div class="form-grid"><label class="field">评测集<select class="input" aria-label="验证评测集" v-model="dataset"><option value="">请选择</option><option v-for="d in datasets" :value="d.id">{{d.name}}</option></select></label><label class="field">发布版本<select class="input" aria-label="验证发布版本" v-model="version" :disabled="busy"><option v-for="v in versions" :value="v.version">v{{v.version}} · {{v.cases.length}} 条</option></select></label></div>
  <label v-if="skillIds.length"><input type="checkbox" v-model="onlyRelated"/> 仅显示显式期望包含 {{skillIds.join('、')}} 的用例</label>
  <div class="table-wrap"><table class="data-table"><thead><tr><th>选择</th><th>用例</th><th>显式期望 Skill</th></tr></thead><tbody><tr v-for="c in rows" :key="c.id"><td><input type="checkbox" v-model="selected" :value="c.id" :aria-label="c.name"/></td><td>{{c.name}}<details><summary>查看输入与期望</summary><pre>{{JSON.stringify(c.turns,null,2)}}</pre></details></td><td>{{skills(c).join('、')||'未配置路由期望'}}</td></tr></tbody></table></div>
  <p v-if="version!==null&&!rows.length" class="empty">没有匹配用例，可取消筛选，或到评测集中补充草稿并发布。</p>
  <template #footer><button class="secondary" @click="emit('close')">返回</button><button class="primary" :disabled="busy||!selected.length" @click="submit">配置验证任务 · {{selected.length}} 条</button></template>
 </el-dialog>
</template>
<style scoped>pre{max-height:260px;overflow:auto}.table-wrap{max-height:45vh;overflow:auto;margin-top:16px}</style>
