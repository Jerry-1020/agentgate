<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import Analysis from './UpstreamAnalysis.vue'
import {request,type TargetDescriptor} from './api'
import {readTaskLinks,saveTaskLink} from './task-links'
const props=defineProps<{runIds:string[]}>()
const selected=ref(''),version=ref(''),agentName=ref(''),error=ref(''),loading=ref(false)
const descriptor=ref<TargetDescriptor|null>(null)
const active=computed(()=>props.runIds.includes(selected.value)?selected.value:props.runIds[0])
const preferred=computed(()=>readTaskLinks().find(t=>t.runIds.includes(active.value))?.staticReports.find(r=>r.descriptorHash===descriptor.value?.content_sha256)?.reportId)
let ticket=0
async function linkReport(reportId:string){
 const link=readTaskLinks().find(t=>t.runIds.includes(active.value))??{id:active.value,kind:'single' as const,runIds:[active.value],staticReports:[]}
 try{await saveTaskLink({...link,staticReports:[...link.staticReports.filter(r=>r.descriptorHash!==descriptor.value?.content_sha256),{version:version.value,descriptorHash:descriptor.value?.content_sha256,reportId}]})}
 catch(e){error.value='分析报告已保存，但任务关联失败；报告 ID：'+reportId+'。'+String(e)}
}
async function load(){
 const current=++ticket;version.value='';descriptor.value=null;error.value='';loading.value=true
 try{const target=await request<TargetDescriptor>('/runs/'+encodeURIComponent(active.value)+'/target-descriptor');if(current===ticket){descriptor.value=target;version.value=target.ref.external_version_id;agentName.value=target.display_name}}
 catch(e){if(current===ticket)error.value=String(e)}finally{if(current===ticket)loading.value=false}
}
watch(active,load,{immediate:true})
</script>
<template>
<section aria-label="任务 Skill 静态分析">
<div v-if="runIds.length>1" class="tabs" aria-label="静态分析实验对象"><button v-for="(id,index) in runIds" :key="id" :class="['tab',{active:active===id}]" @click="selected=id">{{index===0?'实验 A · 基线':'实验 B · 候选'}}</button></div>
<p class="muted">分析当前任务版本的 Skill 定义，不重复运行测试用例。未关联任务报告时，展示该版本的历史分析。</p>
<p v-if="loading">正在读取任务版本…</p><p v-if="error" role="alert">{{error}} <button class="link" @click="load">重试</button></p>
<Analysis v-if="version&&descriptor" :key="active+descriptor.content_sha256" :target-descriptor="descriptor" mode="analysis" :initial-id="version" :preferred-report-id="preferred" :runs="[]" :target-name="agentName" lock-target @report-created="linkReport"/>
</section>
</template>
