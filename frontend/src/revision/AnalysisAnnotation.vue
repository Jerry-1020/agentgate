<script setup lang="ts">
import {ref} from 'vue'
import {ElMessageBox} from 'element-plus'
import {request} from './api'
import type {EvaluationCase} from '../upstream/types/dataset'
const props=defineProps<{runId:string;caseId:string;caseName:string;datasetName:string;modelValue:string}>()
const emit=defineEmits<{'update:modelValue':[value:string]}>()
const busy=ref(false),error=ref(''),savedDataset=ref(''),savedNote=ref('')
async function save(){
 if(busy.value||!props.modelValue.trim())return
 busy.value=true;error.value=''
 const note=props.modelValue.trim()
 try{
  await ElMessageBox.confirm(`将“${props.caseName}”及人工备注加入“${props.datasetName}”草稿。同 ID 用例将被本次运行快照覆盖；已发布版本及历史结果不变。`,'加入评测集草稿',{type:'warning',confirmButtonText:'确认加入',cancelButtonText:'取消'})
  const source=await request<{case:EvaluationCase}>(`/runs/${encodeURIComponent(props.runId)}/cases/${encodeURIComponent(props.caseId)}`)
  const edited={...source.case,notes:[source.case.notes,`【调优人工备注 · 运行 ${props.runId}】\n${note}`].filter(Boolean).join('\n\n')}
  const result=await request<{source_dataset_id:string}>(`/runs/${encodeURIComponent(props.runId)}/cases/${encodeURIComponent(props.caseId)}/writeback`,'POST',{case:edited})
  savedDataset.value=result.source_dataset_id;savedNote.value=note
 }catch(e){if(e!=='cancel'&&e!=='close')error.value=String(e)}finally{busy.value=false}
}
</script>
<template><aside class="annotation-panel" aria-label="人工标注">
 <h4>人工备注</h4>
 <textarea class="input" :aria-label="caseName+'人工备注'" :value="modelValue" @input="emit('update:modelValue',($event.target as HTMLTextAreaElement).value)" :disabled="busy" rows="6" placeholder="记录问题判断、修正说明或回归关注点"/>
 <p class="muted">样本级备注，将随用例保存至“{{datasetName}}”草稿；不会修改期望值。</p>
 <button class="primary" :disabled="busy||!modelValue.trim()" @click="save">{{busy?'处理中…':'加入评测集草稿'}}</button>
 <p v-if="savedDataset&&savedNote===modelValue.trim()" role="status">已加入草稿 · <a class="link" :href="'#datasets/'+encodeURIComponent(savedDataset)+'?version=draft'">查看评测集</a></p>
 <p v-if="error" role="alert">{{error}}</p>
</aside></template>
<style scoped>.annotation-panel{border-left:1px solid #e4e9e7;padding-left:20px;min-width:0}.annotation-panel h4{margin:0 0 12px}.annotation-panel textarea{resize:vertical;width:100%;box-sizing:border-box}.annotation-panel p{font-size:12px;line-height:1.6}.annotation-panel button{width:100%}@media(max-width:1000px){.annotation-panel{border-left:0;border-top:1px solid #e4e9e7;padding:16px 0 0}}</style>
