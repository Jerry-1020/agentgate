<script setup lang="ts">
import {ref} from 'vue'
import {request} from './api'
const emit=defineEmits<{close:[];imported:[]}>()
const name=ref(''),payload=ref<any>(null),error=ref(''),busy=ref(false)
async function read(event:Event){
 payload.value=null;error.value=''
 const file=(event.target as HTMLInputElement).files?.[0];if(!file)return
 if(file.size>1024*1024){error.value='文件不能超过 1 MB';return}
 try{
  const data=JSON.parse(await file.text()),d=data.draft??data
  if(!['rule','llm_judge','hybrid'].includes(d.kind))throw Error('不支持的评估器类型。')
  if(!['rule','llm_judge','hybrid'].includes(d.kind)||!d.implementation_id||!d.implementation_version||!d.dimension||!d.metric||!d.severity||!d.config)throw Error('缺少评估器定义字段；请使用管理员提供的配置 JSON。')
  const {kind,dimension,metric,severity,implementation_id,implementation_version,config,children=[],combination=null}=d
  payload.value={kind,dimension,metric,severity,implementation_id,implementation_version,config,children,combination}
  name.value=data.name??'导入的评估器'
 }catch(e){error.value=String(e)}
}
async function submit(){
 if(busy.value||!payload.value||!name.value.trim())return
 busy.value=true;error.value=''
 try{
  const rule=payload.value.kind==='rule'
  if(rule){
   if(Object.keys(payload.value.config).length)throw Error('规则配置必须为空；规则算法由服务端已注册代码提供。')
   const registered=await request<any[]>('/evaluators?include_disabled=true')
   if(!registered.some(e=>e.kind==='rule'&&e.latest_version&&e.implementation_id===payload.value.implementation_id&&e.implementation_version===payload.value.implementation_version))throw Error('规则实现尚未注册，无法导入。')
  }
  const created=await request<any>('/evaluators','POST',{name:name.value.trim(),description:rule?'由已注册规则配置导入。':'由配置文件导入；请核对执行配置后发布。',draft:payload.value})
  if(rule){
   const path='/evaluators/'+encodeURIComponent(created.evaluator.id)
   try{await request(path+'/drafts/publish','POST')}
   catch(publicationError){
    try{
     const current=await request<any>(path)
     if(current.latest){emit('imported');return}
     await request(path,'DELETE')
    }catch{throw Error('发布结果或临时记录清理未能确认，请刷新列表核查：'+created.evaluator.id)}
    throw publicationError
   }
  }
  emit('imported')
 }
 catch(e){error.value=String(e)}finally{busy.value=false}
}
</script>
<template><el-dialog :model-value="true" title="导入评估器配置" width="min(680px,94vw)" :close-on-click-modal="false" :before-close="()=>{if(!busy)emit('close')}"><p>规则评估器导入后经服务端校验自动发布为只读版本，默认不启用；不提供草稿编辑。LLM 和复合评估器导入为草稿。仅接受配置 JSON，不上传或执行新代码。</p><input type="file" accept=".json" aria-label="评估器配置文件" :disabled="busy" @change="read"/><label class="field">名称<input class="input" aria-label="导入评估器名称" v-model="name" :disabled="busy"/></label><p v-if="payload">类型：{{payload.kind}} · 实现：{{payload.implementation_id}} @ {{payload.implementation_version}}</p><small>模型凭据应使用引用，不要将真实 API Key 写入配置文件。</small><p v-if="error" role="alert">{{error}}</p><template #footer><button class="secondary" :disabled="busy" @click="emit('close')">取消</button><button class="primary" :disabled="busy||!payload||!name.trim()" @click="submit">{{payload?.kind==='rule'?'导入并发布':'导入为草稿'}}</button></template></el-dialog></template>
