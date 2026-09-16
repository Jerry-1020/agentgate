<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import Analysis from './UpstreamAnalysis.vue'
import {request} from './api'
import {readTaskLinks} from './task-links'
const props=defineProps<{runIds:string[]}>()
const selected=ref(''),version=ref(''),agentName=ref(''),error=ref(''),loading=ref(false)
const active=computed(()=>props.runIds.includes(selected.value)?selected.value:props.runIds[0])
const preferred=computed(()=>readTaskLinks().find(t=>t.runIds.includes(active.value))?.staticReports.find(r=>r.version===version.value)?.reportId)
let ticket=0
async function load(){
 const current=++ticket;version.value='';error.value='';loading.value=true
 try{const manifest=await request<any>('/runs/'+encodeURIComponent(active.value)+'/manifest');if(current===ticket){version.value=manifest.target.ref.external_version_id;agentName.value=manifest.target.display_name}}
 catch(e){if(current===ticket)error.value=String(e)}finally{if(current===ticket)loading.value=false}
}
watch(active,load,{immediate:true})
</script>
<template>
<section aria-label="任务 Skill 静态分析">
<div v-if="runIds.length>1" class="tabs" aria-label="静态分析实验对象"><button v-for="(id,index) in runIds" :key="id" :class="['tab',{active:active===id}]" @click="selected=id">{{index===0?'实验 A · 基线':'实验 B · 候选'}}</button></div>
<p class="muted">分析当前任务版本的 Skill 定义，不重复运行测试用例。未关联任务报告时，展示该版本的历史分析。</p>
<p v-if="loading">正在读取任务版本…</p><p v-if="error" role="alert">{{error}} <button class="link" @click="load">重试</button></p>
<Analysis v-if="version" :key="active+version" mode="analysis" :initial-id="version" :preferred-report-id="preferred" :runs="[]" :target-name="agentName" lock-target/>
</section>
</template>
