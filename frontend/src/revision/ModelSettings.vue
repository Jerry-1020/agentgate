<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {request,type EvaluatorSummary,type EvaluatorDetail} from './api'
defineEmits<{dirtyChange:[value:boolean]}>()
const models=ref<{evaluator:string;provider:string;model:string}[]>([]),busy=ref(false),error=ref('')
const connections=ref<{role:string;model:string;base_url:string;configured:boolean}[]>([])
async function load(){
 busy.value=true;error.value=''
 try{
  const entries=await request<EvaluatorSummary[]>('/evaluators?include_disabled=true')
  connections.value=(await request<{connections:typeof connections.value}>('/model-runtime')).connections
  const details=await Promise.all(entries.filter(e=>e.kind==='llm_judge'&&e.latest_version).map(e=>request<EvaluatorDetail>('/evaluators/'+encodeURIComponent(e.id))))
  models.value=details.map(d=>{const m=d.latest?.config.model as {provider_id?:string;model_id?:string}|undefined;return {evaluator:d.evaluator.name,provider:m?.provider_id??'未配置',model:m?.model_id??'未配置'}})
 }catch(e){error.value=String(e)}finally{busy.value=false}
}
onMounted(load)
</script>
<template>
 <main>
  <div class="toolbar"><h1>模型配置</h1><button class="secondary" :disabled="busy" @click="load">刷新</button></div>
  <section class="card">
   <h2>已发布 LLM 评估器的模型引用</h2>
   <p>以下信息直接读取后端。模型凭据由服务端管理，不在浏览器展示。模型引用不等于连接验证成功，实际调用结果请查看评测报告。</p>
   <p v-if="error" role="alert">{{error}}</p><p v-else-if="busy">正在读取…</p>
   <table v-else class="data-table"><thead><tr><th>评估器</th><th>模型服务</th><th>模型名称</th></tr></thead><tbody><tr v-for="m in models" :key="m.evaluator"><td>{{m.evaluator}}</td><td>{{m.provider}}</td><td>{{m.model}}</td></tr></tbody></table>
   <p v-if="!busy&&!error&&!models.length">暂无已发布的 LLM 评估器。</p>
  </section>
  <section class="card section-gap"><h2>服务端实际模型配置</h2><table class="data-table"><thead><tr><th>用途</th><th>模型名称</th><th>接口地址</th><th>配置状态</th></tr></thead><tbody><tr v-for="c in connections" :key="c.role"><td>{{c.role}}</td><td>{{c.model||'未配置'}}</td><td>{{c.base_url}}</td><td>{{c.configured?'已配置':'未配置或服务不可达'}}</td></tr></tbody></table><p>此处读取服务端配置，不返回 API Key；已配置不等于连通性验收，实际模型调用与 token 证据见任务报告。LLM 评估器的模型引用和评分提示词可在评估器草稿中编辑。连接密钥仍由本机服务端管理，未实现多人授权或网页密钥编辑。</p></section>
 </main>
</template>
