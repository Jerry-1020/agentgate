<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch, ref, shallowRef } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError } from '../api/client'
import { request as revisionRequest } from '../../revision/api'
import type { EvaluationRun } from '../types/run'
import { datasetApi } from '../api/datasets'
import DatasetCatalog from '../components/dataset/DatasetCatalog.vue'
import DatasetImport from '../components/dataset/DatasetImport.vue'
import VersionSelector from '../components/dataset/VersionSelector.vue'
import CaseTable from '../components/dataset/CaseTable.vue'
import CaseEditor from '../components/dataset/CaseEditor.vue'
import type {
  DatasetExport, DatasetSummary, DatasetVersion, EvaluationCase, ValidationIssue,
} from '../types/dataset'

const props=defineProps<{initialId?:string}>()
const emit = defineEmits<{ dirtyChange:[dirty:boolean]; runVersion:[selection:{id:string;version:number;caseIds?:string[];caseName?:string}] }>()
function requestVersionRun(eventOrSingle: boolean | Event = false) {
  const single=eventOrSingle===true
  if(activeDataset.value?.archived || activeVersion.value?.version == null || busy.value)return
  if(single&&!activeCaseId.value)return
  emit('runVersion',{id:activeDatasetId.value,version:activeVersion.value.version,...(single?{caseIds:[activeCaseId.value],caseName:editedCase.value?.name}:{})})
}

const datasets = shallowRef<DatasetSummary[]>([])
const versions = shallowRef<DatasetVersion[]>([])
const activeDatasetId = ref(props.initialId??'')
const showingDetail = ref(Boolean(props.initialId))
const deleteItem=ref<DatasetSummary|null>(null),deleteVersions=shallowRef<DatasetVersion[]>([]),deleteVersionId=ref(''),deleting=ref(false)
async function openDelete(item:DatasetSummary){try{const result=await datasetApi.detail(item.id);deleteVersions.value=result.versions;deleteVersionId.value='';deleteItem.value=item}catch(e){showError(e,'无法读取待删除版本')}}
async function deleteSelectedDraft(){if(!deleteItem.value||deleting.value)return;const version=deleteVersions.value.find(v=>v.id===deleteVersionId.value);if(version?.status!=='draft')return;try{await ElMessageBox.confirm('确认删除此草稿及其中的用例？已发布版本和历史报告不变。','删除草稿',{type:'warning',confirmButtonText:'删除草稿',cancelButtonText:'取消'});deleting.value=true;await datasetApi.discardDraft(deleteItem.value.id);deleteItem.value=null;datasets.value=await datasetApi.list();ElMessage.success('草稿已删除，评测集记录保留')}catch(e){if(e!=='cancel'&&e!=='close')showError(e,'删除失败')}finally{deleting.value=false}}
async function openById(){try{const {value}=await ElMessageBox.prompt('输入评测集 ID，可打开已归档资产。','按 ID 打开',{inputValidator:v=>!!v?.trim()||'请输入 ID'});await openDataset(value.trim())}catch(e){if(e!=='cancel'&&e!=='close')showError(e,'无法打开')}}
async function openDataset(id: string,editDraft=true) {
  try { await selectDataset(id); if(!editDraft){const published=versions.value.find(v=>v.status!=='draft');if(published)selectVersion(published)} showingDetail.value=true;window.history.replaceState(null,'','#datasets/'+encodeURIComponent(id)) }
  catch(error) { showError(error,'无法打开评测集') }
}
async function backToList() {
  if(!canDiscard())return
  editorDirty.value=false
  selectFirstCase(activeVersion.value)
  showingDetail.value=false
  window.history.replaceState(null,'','#datasets')
  try { datasets.value=await datasetApi.list() } catch(error) { showError(error,'无法刷新评测集') }
}
const activeVersionId = ref('')
const activeCaseId = ref('')
const editedCase = ref<EvaluationCase|null>(null)
const busy = ref(false)
const caseEditor=ref<InstanceType<typeof CaseEditor>|null>(null)
async function restoreDataset(item:DatasetSummary){
 try{await datasetApi.update(item.id,{archived:false});datasets.value=await datasetApi.list();ElMessage.success('评测集已恢复')}
 catch(e){showError(e,'恢复失败')}
}
const detailTab = ref('samples')
const history = shallowRef<EvaluationRun[]>([])
const historyPage=ref(1),historyTotal=ref(0)
watch(historyPage,()=>void showHistory())
watch(activeDatasetId,()=>{historyPage.value=1;history.value=[];historyTotal.value=0;detailTab.value='samples'})
async function showHistory() {
  detailTab.value = 'history'
  try { const records=await revisionRequest<EvaluationRun[]>('/runs?limit=200');const matched=records.filter(r=>r.manifest.dataset.dataset_id===activeDatasetId.value);history.value=matched.slice((historyPage.value-1)*20,historyPage.value*20);historyTotal.value=matched.length }
  catch (error) { showError(error, '无法加载评测历史') }
}
const loading = ref(true)
const validationIssues = ref<ValidationIssue[]>([])
const datasetDialog = ref(false)
const dialogMode = ref<'create'|'copy'|'edit'>('create')
const copyVersion = ref<number|null>(null)
const copySources = computed(()=>versions.value.filter(v=>v.status==='published'))
const dialogName = ref('')
const dialogDescription = ref('')
const importInput = ref<HTMLInputElement|null>(null)
const importDialog=ref(false)
async function imported(id:string){importDialog.value=false;await loadDatasets(id);showingDetail.value=true;ElMessage.success('评测集已导入')}
async function downloadExcel(version:number){
 try{const r=await fetch(`/api/datasets/${encodeURIComponent(activeDatasetId.value)}/versions/${version}/export/xlsx`);if(!r.ok)throw Error('导出失败');const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=`${activeDataset.value?.name??'dataset'}-v${version}.xlsx`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){showError(e,'导出失败')}
}
const cloneJson = <T>(value: T): T => JSON.parse(JSON.stringify(value))

const activeVersion = computed<DatasetVersion|null>(
  () => versions.value.find(item => item.id === activeVersionId.value) ?? null,
)
const editable = computed(() => activeVersion.value?.status === 'draft'&&!activeDataset.value?.archived)
const publishedVersions = computed(() => versions.value.filter(item => item.status === 'published'))
const activeDataset = computed(() => datasets.value.find(item => item.id === activeDatasetId.value) ?? null)
const activeCaseIssues = computed(() => {
  const caseIndex = activeVersion.value?.cases.findIndex(item => item.id === activeCaseId.value) ?? -1
  if (caseIndex < 0) return []
  const prefix = `cases[${caseIndex}]`
  return validationIssues.value.filter(issue => issue.path.startsWith(prefix))
})

const editorDirty=ref(false)
const dirty=computed(()=>editable.value&&(editorDirty.value||(editedCase.value!==null&&JSON.stringify(editedCase.value)!==JSON.stringify(activeVersion.value?.cases.find(c=>c.id===editedCase.value?.id)??null))))
watch(dirty,v=>emit('dirtyChange',v))
function canDiscard(){return !dirty.value||window.confirm('当前样本有未保存的修改，确定放弃？')}
function warnBeforeUnload(event:BeforeUnloadEvent){if(dirty.value){event.preventDefault();event.returnValue=''}}
onMounted(()=>window.addEventListener('beforeunload',warnBeforeUnload))
onUnmounted(()=>{window.removeEventListener('beforeunload',warnBeforeUnload);emit('dirtyChange',false)})
function chooseVersion(preferredId = '') {
  const selected = versions.value.find(item => item.id === preferredId)
    ?? versions.value.find(item => item.version === Number(new URLSearchParams(location.hash.split('?')[1]??'').get('version')))
    ?? versions.value.find(item => item.status === 'draft')
    ?? publishedVersions.value[0]
    ?? null
  activeVersionId.value = selected?.id ?? ''
  selectFirstCase(selected)
}

function selectFirstCase(version: DatasetVersion|null) {
  const selected = version?.cases.find(item => item.id === activeCaseId.value)
    ?? version?.cases.find(item => item.id === new URLSearchParams(location.hash.split('?')[1]??'').get('case'))
    ?? version?.cases[0]
    ?? null
  activeCaseId.value = selected?.id ?? ''
  editedCase.value = selected ? cloneJson(selected) : null
}

async function loadDatasets(preferredDatasetId = activeDatasetId.value) {
  datasets.value = await datasetApi.list()
  if(preferredDatasetId&&!datasets.value.some(d=>d.id===preferredDatasetId)){await selectDataset(preferredDatasetId);return}
  const selected = datasets.value.find(item => item.id === preferredDatasetId) ?? datasets.value.find(item=>item.id==='loan-risk-policy'&&!item.archived) ?? datasets.value.find(item=>!item.archived)
  if (selected) await selectDataset(selected.id)
  else {
    activeDatasetId.value = ''
    versions.value = []
    chooseVersion()
  }
}

async function selectDataset(datasetId: string, preferredVersionId = '') {
  if(datasetId!==activeDatasetId.value&&!canDiscard())return
  loading.value = true
  try {
    activeDatasetId.value = datasetId
    const detail = await datasetApi.detail(datasetId)
    const published=detail.versions.filter(v=>v.status==='published').sort((a,b)=>(b.version??0)-(a.version??0))[0],draft=detail.versions.find(v=>v.status==='draft')
    const summary={...detail.dataset,version:published?.version??null,case_count:published?.cases.length??0,has_draft:!!draft,draft_case_count:draft?.cases.length??null,draft_based_on_version:draft?.based_on_version??null}
    datasets.value=[...datasets.value.filter(d=>d.id!==datasetId),summary]
    versions.value = detail.versions
    chooseVersion(preferredVersionId)
  } finally {
    loading.value = false
  }
}

function selectVersion(version: DatasetVersion) {
  if(!canDiscard())return
  activeVersionId.value = version.id
  validationIssues.value = []
  selectFirstCase(version)
}

function selectCase(item: EvaluationCase) {
  if(!canDiscard())return
  activeCaseId.value = item.id
  editedCase.value = cloneJson(item)
}

function newCase(): EvaluationCase {
  return {
    id: crypto.randomUUID(),
    name: '新用例',
    category: 'positive',
    difficulty: 'medium',
    tags: [],
    notes: '',
    initial_state: {},
    turns: [{
      id: crypto.randomUUID(),
      input: {},
      expected_skill: null,
      expectations: [],
      required_tools: [],
      forbidden_tools: [],
      policy_rules: [],
      notes: '',
    }],
  }
}

function addCase() {
  if(!canDiscard())return
  const item = newCase()
  activeCaseId.value = item.id
  editedCase.value = item
  validationIssues.value = []
}

async function refreshAfterMutation(version: DatasetVersion, caseId = activeCaseId.value) {
  datasets.value = await datasetApi.list()
  versions.value = await datasetApi.versions(activeDatasetId.value)
  activeVersionId.value = version.id
  activeCaseId.value = caseId
  const current = versions.value.find(item => item.id === version.id) ?? version
  const selected = current.cases.find(item => item.id === caseId) ?? current.cases[0] ?? null
  editedCase.value = selected ? cloneJson(selected) : null
}

async function saveCase(item: EvaluationCase) {
  if (!activeDatasetId.value || !editable.value) return
  busy.value = true
  try {
    const exists = activeVersion.value?.cases.some(entry => entry.id === item.id) ?? false
    const version = exists
      ? await datasetApi.updateCase(activeDatasetId.value, item, activeVersion.value!.content_sha256)
      : await datasetApi.addCase(activeDatasetId.value, item, activeVersion.value!.content_sha256)
    await refreshAfterMutation(version, item.id)
    validationIssues.value = []
    editorDirty.value = false
    ElMessage.success('当前用例已保存到草稿')
  } catch (error) {
    if(error instanceof ApiError&&error.status===409)ElMessage.error('其他用户已修改此草稿。本次修改未覆盖服务器，请复制保留本地内容后刷新。');else showError(error, '保存用例失败')
  } finally {
    busy.value = false
  }
}

async function copyCase(item: EvaluationCase) {
  if (!editable.value||!canDiscard()) return
  const version = await datasetApi.copyCase(activeDatasetId.value, item.id, activeVersion.value!.content_sha256)
  const copied = version.cases.find(entry => !activeVersion.value?.cases.some(old => old.id === entry.id))
  await refreshAfterMutation(version, copied?.id)
  ElMessage.success('已复制用例')
}

async function removeCase(item: EvaluationCase) {
  if(!canDiscard())return
  await ElMessageBox.confirm(`删除草稿中的“${item.name}”？已发布版本不会受影响。`, '删除用例', { type: 'warning' })
  const version = await datasetApi.removeCase(activeDatasetId.value, item.id, activeVersion.value!.content_sha256)
  activeCaseId.value = ''
  await refreshAfterMutation(version)
  ElMessage.success('用例已从草稿移除')
}

async function reorderCases(ids: string[]) {
  if(!canDiscard())return
  const version = await datasetApi.reorderCases(activeDatasetId.value, ids, activeVersion.value!.content_sha256)
  await refreshAfterMutation(version)
}

function openCreate() {
  if(!canDiscard())return
  dialogMode.value = 'create'
  dialogName.value = ''
  dialogDescription.value = ''
  datasetDialog.value = true
}

function openCopy(item: DatasetSummary) {
  if(!canDiscard())return
  if(!copySources.value.length)return ElMessage.warning('发布首个版本后才可复制评测集')
  copyVersion.value = activeVersion.value?.version ?? copySources.value[0]?.version ?? null
  dialogMode.value = 'copy'
  dialogName.value = `${item.name}（副本）`
  dialogDescription.value = item.description
  datasetDialog.value = true
}

function openMetadata(item: DatasetSummary) {
  if(!canDiscard())return
  dialogMode.value='edit';dialogName.value=item.name;dialogDescription.value=item.description;datasetDialog.value=true
}

async function submitDatasetDialog() {
  if (!dialogName.value.trim()) return ElMessage.warning('请输入评测集名称')
  busy.value = true
  try {
    if(dialogMode.value==='edit'){
      await datasetApi.update(activeDatasetId.value,{name:dialogName.value.trim(),description:dialogDescription.value})
      datasetDialog.value=false;await loadDatasets(activeDatasetId.value);ElMessage.success('基本信息已保存');return
    }
    if(dialogMode.value==='copy'&&!copySources.value.some(v=>v.version===copyVersion.value))throw Error('请选择已发布的来源版本')
    const result = dialogMode.value === 'create'
      ? await datasetApi.create(dialogName.value, dialogDescription.value)
      : await datasetApi.copy(
          activeDatasetId.value,
          dialogName.value,
          copyVersion.value,
        )
    datasetDialog.value = false
    await loadDatasets(result.dataset.id)
    showingDetail.value = true
    window.history.replaceState(null,'','#datasets/'+encodeURIComponent(result.dataset.id))
    ElMessage.success(dialogMode.value === 'create' ? '评测集已创建' : '评测集已复制')
  } catch (error) {
    showError(error, '操作失败')
  } finally {
    busy.value = false
  }
}

async function archiveDataset(item: DatasetSummary) {
  if(!canDiscard())return
  try { await ElMessageBox.confirm(`归档“${item.name}”？历史版本和运行记录仍可读取。主仓不提供归档列表，请保留 ID：${item.id}，通过“按 ID 打开”恢复。`, '归档评测集', { type: 'warning',confirmButtonText:'确定',cancelButtonText:'取消' }) } catch { return }
  await datasetApi.archive(item.id)
  await loadDatasets('')
  showingDetail.value = false
  ElMessage.success('评测集已归档')
}

async function createDraft(base: number|null) {
  if(!canDiscard())return
  busy.value = true
  try {
    const draft = await datasetApi.createDraft(activeDatasetId.value, base)
    await selectDataset(activeDatasetId.value, draft.id)
    datasets.value = await datasetApi.list()
    ElMessage.success('新版本草稿已创建')
  } catch (error) {
    showError(error, '创建草稿失败')
  } finally {
    busy.value = false
  }
}

async function discardDraft() {
  await ElMessageBox.confirm('放弃当前草稿？草稿中的修改将无法恢复。', '放弃草稿', { type: 'warning' })
  await datasetApi.discardDraft(activeDatasetId.value)
  await selectDataset(activeDatasetId.value)
  datasets.value = await datasetApi.list()
  ElMessage.success('草稿已放弃')
}

async function publishDraft() {
  if(dirty.value){ElMessage.warning('请先保存当前样本，再发布评测集');return}
  busy.value = true
  validationIssues.value = []
  try {
    const published = await datasetApi.publish(activeDatasetId.value, activeVersion.value!.content_sha256)
    await selectDataset(activeDatasetId.value, published.id)
    datasets.value = await datasetApi.list()
    ElMessage.success(`已发布 v${published.version}`)
  } catch (error) {
    if (error instanceof ApiError && Array.isArray(error.detail)) {
      validationIssues.value = error.detail as ValidationIssue[]
    } else if (
      error instanceof ApiError
      && error.status === 422
      && error.detail === 'published DatasetVersion requires at least one Case'
    ) {
      validationIssues.value = [{ path: 'cases', message: '评测集至少需要一个用例' }]
    }
    showError(error, '发布失败，请检查用例')
  } finally {
    busy.value = false
  }
}

async function exportVersion(version: number) {
  const payload = await datasetApi.exportVersion(activeDatasetId.value, version)
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${activeDataset.value?.name ?? 'dataset'}-v${version}.json`
  link.click()
  URL.revokeObjectURL(url)
}

function openImport() {
  if(!canDiscard())return
  importDialog.value=true
}

async function importDataset(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const payload = JSON.parse(await file.text()) as DatasetExport
    const result = await datasetApi.importDataset(payload)
    await loadDatasets(result.dataset.id)
    showingDetail.value = true
    ElMessage.success('评测集已导入')
  } catch (error) {
    showError(error, '导入失败')
  } finally {
    input.value = ''
  }
}



function showError(error: unknown, fallback: string) {
  ElMessage.error(error instanceof Error ? error.message : fallback)
}

onMounted(async () => {
  try {
    await loadDatasets()
  } catch (error) {
    showError(error, '无法加载评测集')
  } finally { loading.value=false }
})
</script>

<template>
  <section class="dataset-workspace" aria-labelledby="dataset-workspace-title">
    <div class="workspace-heading">
      <div>
        <span class="step">DATASET WORKSPACE</span>
        <button v-if="showingDetail" class="link" data-testid="back-datasets" @click="backToList">← 返回评测集列表</button>
        <h1 id="dataset-workspace-title">{{showingDetail ? activeDataset?.name : '评测集'}}</h1>
      </div>
      <div v-if="!showingDetail" class="actions" style="margin-left:auto"><button class="secondary" :disabled="busy" @click="openImport">导入测评集</button><button class="primary" data-testid="create-dataset" :disabled="busy" @click="openCreate">创建</button></div>
      <div v-else-if="activeDataset" class="actions"><span v-if="activeDataset.archived">已归档 · 只读</span><button v-if="activeDataset.archived" class="secondary" @click="restoreDataset(activeDataset)">恢复评测集</button><button class="secondary" :disabled="busy || activeDataset.archived" @click="openMetadata(activeDataset)">编辑基本信息</button><button class="secondary" :disabled="busy || !copySources.length" @click="openCopy(activeDataset)">复制评测集</button><div class="field"><button class="primary" data-testid="run-dataset-version" :disabled="busy || activeDataset.archived || activeVersion?.version == null" @click="requestVersionRun" :title="activeDataset.archived?'恢复后可运行':activeVersion?.version==null?'请先发布草稿':'使用当前版本发起评测'">发起评测</button></div></div>
    </div>

    <DatasetCatalog v-show="!showingDetail" :items="datasets" :loading="loading" @select="openDataset($event,false)" @edit="openDataset($event,true)" @remove="openDelete" />
    <template v-if="showingDetail">
    <div v-if="editable" class="toolbar" style="padding:12px 24px"><span role="status">{{dirty?'有未保存修改':'草稿已保存'}} · 切换用例前请保存当前编辑</span><button class="primary" :disabled="busy||!editedCase||!dirty" @click="caseEditor?.save()">保存草稿</button></div>
    <VersionSelector
      v-if="activeDatasetId && !activeDataset?.archived"
      :versions="versions"
      :active-id="activeVersionId"
      :busy="busy"
      @select="selectVersion"
      @create-draft="createDraft"
      @publish="publishDraft"
      @discard="discardDraft"
      @export="exportVersion"
      @export-excel="downloadExcel"
    />

    <div class="dataset-detail-tabs tabs">
      <button :class="['tab',{active:detailTab==='samples'}]" @click="detailTab='samples'">样本维护</button>
      <button :class="['tab',{active:detailTab==='versions'}]" @click="detailTab='versions'">版本记录</button>
      <button :class="['tab',{active:detailTab==='history'}]" @click="showHistory">关联评测历史</button>
    </div>
    <section v-if="detailTab==='versions'" class="dataset-tab-content"><table class="data-table"><thead><tr><th>版本</th><th>状态</th><th>样本数量</th><th>发布时间</th><th>操作</th></tr></thead><tbody><tr v-for="v in versions" :key="v.id"><td>{{v.version == null ? '草稿' : 'v'+v.version}}</td><td>{{v.status==='draft'?'草稿':'已发布'}}</td><td>{{v.cases.length}}</td><td>{{v.published_at??'—'}}</td><td><button class="link" @click="selectVersion(v);detailTab='samples'">查看样本</button></td></tr></tbody></table></section>
    <section v-if="detailTab==='history'" class="dataset-tab-content"><table class="data-table"><thead><tr><th>任务</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="r in history" :key="r.id"><td>{{r.id}}</td><td>v{{r.manifest.dataset.version}}</td><td>{{r.status}}</td><td><a class="link" :href="'#tasks/'+r.id">查看任务</a></td></tr></tbody></table><p v-if="!history.length" class="empty">暂无关联评测任务</p><p class="muted">最近 200 条任务中，{{historyTotal}} 条关联任务 · 第 {{historyPage}} 页 <button class="link" :disabled="historyPage<=1" @click="historyPage--">上一页</button><button class="link" :disabled="historyPage*20>=historyTotal" @click="historyPage++">下一页</button></p></section>

    <el-alert
      v-if="validationIssues.length"
      class="validation-alert"
      title="草稿尚不能发布"
      type="error"
      :closable="false"
      show-icon
    >
      <ul><li v-for="issue in validationIssues" :key="`${issue.path}-${issue.message}`"><code>{{ issue.path }}</code>：{{ issue.message }}</li></ul>
    </el-alert>

    <div v-show="detailTab==='samples'" class="dataset-layout" v-loading="loading">
      <CaseTable
        :items="activeVersion?.cases ?? []"
        :selected-id="activeCaseId"
        :editable="editable"
        @select="selectCase"
        @add="addCase"
        @copy="copyCase"
        @remove="removeCase"
        @reorder="reorderCases"
      />
      <div class="case-editor-container"><CaseEditor ref="caseEditor"
        :item="editedCase"
        :editable="editable"
        :saving="busy"
        :validation-issues="activeCaseIssues"
        @save="saveCase"
        @dirty-change="editorDirty=$event"
      /></div>
    </div>

    </template>

    <el-dialog v-model="importDialog" title="导入评测集" width="min(720px,94vw)" :close-on-click-modal="false"><DatasetImport v-if="importDialog" @imported="imported"/></el-dialog>

    <el-dialog v-model="datasetDialog" :title="dialogMode === 'create' ? '新建评测集' : dialogMode === 'edit' ? '编辑基本信息' : '复制评测集'" width="min(460px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="dialogName" data-testid="dataset-name" /></el-form-item>
        <el-form-item v-if="dialogMode !== 'copy'" label="描述"><el-input v-model="dialogDescription" type="textarea" :rows="3" /></el-form-item>
        <el-form-item v-if="dialogMode === 'copy'" label="来源版本"><select class="input" aria-label="复制来源版本" v-model="copyVersion"><option v-for="v in copySources" :key="v.version!" :value="v.version">v{{v.version}} · {{v.cases.length}} 条用例</option></select><small>生成独立评测集草稿，不包含当前未发布修改。</small></el-form-item>
      </el-form>
      <template #footer><el-button @click="datasetDialog = false">取消</el-button><el-button type="primary" :loading="busy" data-testid="submit-dataset" @click="submitDatasetDialog">{{dialogMode === 'create' ? '保存草稿' : dialogMode === 'edit' ? '保存' : '保存副本'}}</el-button></template>
    </el-dialog>
  </section>
    <el-dialog :model-value="!!deleteItem" title="删除评测集版本" width="560px" @close="!deleting&&(deleteItem=null)">
      <p>{{deleteItem?.name}}</p><label>选择版本<select v-model="deleteVersionId" class="input" aria-label="待删除版本"><option value="">请选择版本</option><option v-for="v in deleteVersions" :key="v.id" :value="v.id">{{v.status==='draft'?'当前草稿':'已发布 v'+v.version}} · {{v.cases.length}} 条用例</option></select></label>
      <p class="muted">当前后端只支持删除草稿。已发布版本删除和整个评测集删除尚无接口，暂不可提交；不会用归档替代删除。</p>
      <template #footer><button class="secondary" :disabled="deleting" @click="deleteItem=null">取消</button><button class="primary" :disabled="deleting||deleteVersions.find(v=>v.id===deleteVersionId)?.status!=='draft'" @click="deleteSelectedDraft">删除草稿</button></template>
    </el-dialog>
</template>

<style scoped>
section.dataset-workspace { overflow: visible; }
.dataset-workspace .dataset-layout {
  grid-template-columns: minmax(220px, .7fr) minmax(360px, 2fr);
  height: auto;
  max-height: none;
  align-items: start;
  overflow: visible;
}
.case-editor-container { min-width: 0; }
.dataset-workspace :deep(.case-editor-panel) { overflow: visible; max-height: none; }
.dataset-workspace :deep(.case-editor-panel > .dataset-panel-heading) { top: 64px; }
.dataset-workspace :deep(.case-list-panel) {
  position: sticky;
  top: 80px;
  max-height: calc(100vh - 96px);
  overflow: auto;
}
.workspace-heading .link { margin-bottom: 12px; }
@media(max-width:760px) {
  .dataset-workspace .dataset-layout { display: block; min-height: 0; }
  .dataset-workspace :deep(.case-list-panel) { position: static; max-height: 320px; }
  .dataset-workspace :deep(.case-editor-panel > .dataset-panel-heading) { position: static; }
}
</style>
