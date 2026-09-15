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
  if(!['rule','llm_judge','hybrid'].includes(d.kind)||!d.implementation_id||!d.implementation_version||!d.dimension||!d.metric||!d.severity||!d.config)throw Error('缺少评估器定义字段；请使用管理员提供的配置 JSON。')
  const {kind,dimension,metric,severity,implementation_id,implementation_version,config,children=[],combination=null}=d
  payload.value={kind,dimension,metric,severity,implementation_id,implementation_version,config,children,combination}
  name.value=data.name??'导入的评估器'
 }catch(e){error.value=String(e)}
}
async function submit(){
 if(busy.value||!payload.value||!name.value.trim())return
 busy.value=true;error.value=''
 try{await request('/evaluators','POST',{name:name.value.trim(),description:'由配置文件导入；请核对执行配置后发布。',draft:payload.value});emit('imported')}
 catch(e){error.value=String(e)}finally{busy.value=false}
}
</script>
<template><el-dialog :model-value="true" title="导入评估器配置" width="min(680px,94vw)" :close-on-click-modal="false" :before-close="()=>{if(!busy)emit('close')}"><p>仅导入配置为新草稿，不执行代码、不自动发布。实现必须已在服务端注册；复合评估器引用的子版本必须已存在。</p><input type="file" accept=".json" aria-label="评估器配置文件" :disabled="busy" @change="read"/><label class="field">名称<input class="input" aria-label="导入评估器名称" v-model="name" :disabled="busy"/></label><p v-if="payload">类型：{{payload.kind}} · 实现：{{payload.implementation_id}} @ {{payload.implementation_version}}</p><small>模型凭据应使用引用，不要将真实 API Key 写入配置文件。</small><p v-if="error" role="alert">{{error}}</p><template #footer><button class="secondary" :disabled="busy" @click="emit('close')">取消</button><button class="primary" :disabled="busy||!payload||!name.trim()" @click="submit">导入为草稿</button></template></el-dialog></template>
