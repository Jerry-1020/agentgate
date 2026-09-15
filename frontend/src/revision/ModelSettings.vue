<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import {request,type EvaluatorSummary,type EvaluatorDetail} from './api'
import {settingsPreview as catalog,permittedTeams,connectionState,visibleConnections,validateConnection,validateCredential,type PreviewConnection,type PreviewCredential} from './settings-preview'
const emit=defineEmits<{dirtyChange:[value:boolean]}>()
const models=ref<{provider_id:string;model_id:string}[]>([]),error=ref(''),busy=ref(false)
let disposed=false
async function load(){
 busy.value=true;error.value=''
 try{
  const entries=await request<EvaluatorSummary[]>('/evaluators')
  const judges=entries.filter(e=>e.source==='builtin'&&e.kind==='llm_judge')
  const details=await Promise.all(judges.map(e=>request<EvaluatorDetail>('/evaluators/'+encodeURIComponent(e.id))))
  const catalog=new Map<string,{provider_id:string;model_id:string}>()
  for(const d of details){const m=d.latest?.config.model as {provider_id?:unknown;model_id?:unknown}|undefined;if(typeof m?.provider_id==='string'&&typeof m.model_id==='string')catalog.set(m.provider_id+':'+m.model_id,{provider_id:m.provider_id,model_id:m.model_id})}
  if(!disposed)models.value=[...catalog.values()]
 }catch{if(!disposed)error.value='无法读取服务端评估器的模型配置，请重试。'}finally{if(!disposed)busy.value=false}
}
onMounted(load)
const tab=ref('connections'),query=ref(''),teamFilter=ref('')
const modal=ref<''|'connection'|'credential'|'rotate'|'team'>(''),formOpen=ref(false),formError=ref(''),baseline=ref('')
const emptyConnection=():PreviewConnection=>({id:'',name:'',provider:'openai-compatible',baseUrl:'',modelId:'',credentialId:'',ownerTeamId:teamFilter.value||catalog.teams[0]?.id||'',allowedTeamIds:[],enabled:true})
const emptyCredential=():PreviewCredential=>({id:'',name:'',provider:'openai-compatible',ownerTeamId:teamFilter.value||catalog.teams[0]?.id||'',allowedTeamIds:[],enabled:true,revision:1})
const connection=ref(emptyConnection()),credential=ref(emptyCredential()),secret=ref(''),teamName=ref(''),teamId=ref('')
const snapshot=()=>JSON.stringify([connection.value,credential.value,secret.value,teamName.value,teamId.value])
const dirty=computed(()=>formOpen.value&&snapshot()!==baseline.value)
watch(dirty,v=>emit('dirtyChange',v))
function unload(e:BeforeUnloadEvent){if(dirty.value){e.preventDefault();e.returnValue=''}}
onMounted(()=>window.addEventListener('beforeunload',unload))
onUnmounted(()=>{disposed=true;secret.value='';emit('dirtyChange',false);window.removeEventListener('beforeunload',unload)})
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value))
function openConnection(item?:PreviewConnection){connection.value=clone(item??emptyConnection());formError.value='';secret.value='';modal.value='connection';baseline.value=snapshot();formOpen.value=true}
function openCredential(item?:PreviewCredential,rotate=false){credential.value=clone(item??emptyCredential());secret.value='';formError.value='';modal.value=rotate?'rotate':'credential';baseline.value=snapshot();formOpen.value=true}
function openTeam(id=''){teamId.value=id;teamName.value=catalog.teams.find(t=>t.id===id)?.name??'';formError.value='';modal.value='team';baseline.value=snapshot();formOpen.value=true}
function close(force=false){if(!force&&dirty.value&&!window.confirm('放弃本次未保存的预览修改？'))return;secret.value='';formOpen.value=false;formError.value=''}
function acceptExample(event:Event){
 const input=event.target as HTMLInputElement,value=input.value
 if(value&&!('demo-'.startsWith(value)||value.startsWith('demo-'))){input.value='';secret.value='';formError.value='当前仅为前端预览，请勿输入真实密钥。可点击“填入示例密钥”。';return}
 secret.value=value;formError.value=''
}
function fillExample(){secret.value='demo-key-for-ui-preview';formError.value=''}
function save(){
 formError.value=''
 if(modal.value==='connection'){
  const value={...clone(connection.value),name:connection.value.name.trim(),modelId:connection.value.modelId.trim(),baseUrl:connection.value.baseUrl.trim()}
  formError.value=validateConnection(value,catalog);if(formError.value)return
  const index=catalog.connections.findIndex(c=>c.id===value.id)
  if(index<0)catalog.connections.push({...value,id:crypto.randomUUID()});else catalog.connections[index]=value
 }else if(modal.value==='credential'||modal.value==='rotate'){
  if((!credential.value.id||modal.value==='rotate')&&(!secret.value.startsWith('demo-')||secret.value.length<=5)){formError.value='请填入 demo- 开头的示例密钥；本页不接收真实密钥。';return}
  const value={...clone(credential.value),name:credential.value.name.trim()}
  formError.value=validateCredential(value,catalog);if(formError.value)return
  const index=catalog.credentials.findIndex(k=>k.id===value.id)
  if(index<0)catalog.credentials.push({...value,id:crypto.randomUUID()})
  else catalog.credentials[index]={...value,revision:value.revision+(modal.value==='rotate'?1:0)}
 }else if(modal.value==='team'){
  const name=teamName.value.trim()
  if(!name){formError.value='请填写团队名称。';return}
  if(catalog.teams.some(t=>t.id!==teamId.value&&t.name.toLowerCase()===name.toLowerCase())){formError.value='已有同名预览团队。';return}
  const item=catalog.teams.find(t=>t.id===teamId.value)
  if(item)item.name=name;else catalog.teams.push({id:crypto.randomUUID(),name})
 }
 close(true);ElMessage.success('已保存至本页预览，未写入后端')
}
const teamLabel=(id:string)=>catalog.teams.find(t=>t.id===id)?.name??'未找到团队'
const keyLabel=(id:string)=>catalog.credentials.find(k=>k.id===id)?.name??'未找到凭据'
const accessLabel=(item:{ownerTeamId:string;allowedTeamIds:string[]})=>permittedTeams(item).map(teamLabel).join('、')
const keyOptions=computed(()=>catalog.credentials.filter(k=>k.id===connection.value.credentialId||(k.enabled&&k.provider===connection.value.provider&&permittedTeams(k).includes(connection.value.ownerTeamId))))
const grantOptions=computed(()=>catalog.teams.filter(t=>t.id!==connection.value.ownerTeamId&&permittedTeams(catalog.credentials.find(k=>k.id===connection.value.credentialId)??{ownerTeamId:'',allowedTeamIds:[]}).includes(t.id)))
function resetConnectionAccess(){connection.value.credentialId='';connection.value.allowedTeamIds=[]}
function updateCredential(){const key=catalog.credentials.find(k=>k.id===connection.value.credentialId);connection.value.allowedTeamIds=connection.value.allowedTeamIds.filter(id=>key&&permittedTeams(key).includes(id))}
const filteredConnections=computed(()=>catalog.connections.filter(c=>(!teamFilter.value||permittedTeams(c).includes(teamFilter.value))&&[c.name,c.modelId,c.baseUrl].join(' ').toLowerCase().includes(query.value.toLowerCase())))
const filteredKeys=computed(()=>catalog.credentials.filter(k=>(!teamFilter.value||permittedTeams(k).includes(teamFilter.value))&&k.name.toLowerCase().includes(query.value.toLowerCase())))
watch(tab,()=>query.value='')
async function confirmChange(message:string){try{await ElMessageBox.confirm(message,'确认预览操作',{confirmButtonText:'确认',cancelButtonText:'取消'});return true}catch{return false}}
async function toggleConnection(item:PreviewConnection){if(await confirmChange((item.enabled?'停用':'启用')+'此模型连接的预览状态？不影响真实任务。'))item.enabled=!item.enabled}
async function removeConnection(item:PreviewConnection){if(await confirmChange('删除“'+item.name+'”的预览配置？'))catalog.connections=catalog.connections.filter(c=>c.id!==item.id)}
async function toggleKey(item:PreviewCredential){
 const count=catalog.connections.filter(c=>c.credentialId===item.id).length
 if(await confirmChange((item.enabled?'停用后，关联的 '+count+' 个模型在团队使用预览中将不可选。':'恢复此凭据的预览状态？')+' 不影响真实凭据或任务。'))item.enabled=!item.enabled
}
async function removeKey(item:PreviewCredential){
 const used=catalog.connections.filter(c=>c.credentialId===item.id)
 if(used.length){ElMessage.warning('仍被 '+used.length+' 个模型引用，请先更换模型凭据或删除对应预览连接。');return}
 if(await confirmChange('删除“'+item.name+'”的预览凭据？'))catalog.credentials=catalog.credentials.filter(k=>k.id!==item.id)
}
async function removeTeam(id:string){
 if([...catalog.connections,...catalog.credentials].some(item=>permittedTeams(item).includes(id))){ElMessage.warning('该团队仍有配置或授权，请先删除其所属预览配置，并收回其它配置对该团队的授权。');return}
 if(await confirmChange('删除该预览团队？')){catalog.teams=catalog.teams.filter(t=>t.id!==id);if(teamFilter.value===id)teamFilter.value=''}
}
const stateText={available:'预览启用',disabled:'预览停用',credential_disabled:'凭据已停用',invalid:'授权或凭据不匹配'}
const testing=ref<PreviewConnection|null>(null),scenario=ref('success')
const scenarios:Record<string,{title:string;text:string}>={
 success:{title:'示例：连接成功',text:'展示接口可达、模型可用时的结果样式。不表示该地址已实际验证。'},
 unauthorized:{title:'示例：凭据无效（401）',text:'正式功能应提示检查密钥有效性、所属服务和授权范围。'},
 missing:{title:'示例：模型不可用（404）',text:'正式功能应提示核对模型 ID 和服务端点。'},
 timeout:{title:'示例：请求超时',text:'正式功能应保留配置，允许检查网络后重试。'},
}
const teamPreview=ref(''),memberModel=ref('')
const memberModels=computed(()=>visibleConnections(catalog,teamPreview.value))
watch(teamPreview,()=>memberModel.value='')
function showTest(item:PreviewConnection){testing.value=item;scenario.value='success'}
const modalTitle=computed(()=>modal.value==='connection'?(connection.value.id?'编辑模型连接与授权':'新增模型连接'):modal.value==='rotate'?'替换 API Key（预览）':modal.value==='credential'?(credential.value.id?'编辑凭据与授权':'新增 API Key'):(teamId.value?'编辑团队（预览）':'新增团队（预览）'))
</script>

<template>
 <div class="model-settings">
  <div class="page-head"><div><h1 class="page-title">配置</h1><p class="page-sub">模型连接、API Key 与团队使用范围</p></div><button class="primary" @click="tab==='connections'?openConnection():tab==='credentials'?openCredential():openTeam()">{{tab==='connections'?'新增模型连接':tab==='credentials'?'新增 API Key':'新增团队'}}</button></div>
  <p class="preview-scope" role="status"><span class="badge warn">交互预览</span> 以下新增、启停和团队授权仅用于本页预览；刷新后重置，不影响后端或真实调用。</p>
  <section class="card settings-card">
   <div class="tabs" role="tablist" aria-label="配置分类"><button v-for="[key,label] in [['connections','模型连接'],['credentials','API Key'],['teams','团队授权']]" :key="key" role="tab" :aria-selected="tab===key" :class="['tab',{active:tab===key}]" @click="tab=key">{{label}}</button></div>
   <div v-if="tab!=='teams'" class="toolbar settings-filters"><input class="input" v-model="query" :aria-label="tab==='connections'?'搜索模型连接':'搜索 API Key'" :placeholder="tab==='connections'?'搜索连接名称、模型 ID 或地址':'搜索凭据名称'"/><label class="field">使用团队<select class="input" v-model="teamFilter" aria-label="筛选使用团队"><option value="">全部团队</option><option v-for="t in catalog.teams" :key="t.id" :value="t.id">{{t.name}}</option></select></label></div>
   <div v-if="tab==='connections'" class="table-wrap"><table class="data-table"><thead><tr><th>模型连接</th><th>凭据</th><th>团队使用范围</th><th>状态 / 连接验证</th><th>操作</th></tr></thead><tbody>
    <tr v-for="c in filteredConnections" :key="c.id" :data-testid="'connection-'+c.id"><td><b>{{c.name}}</b><small>{{c.modelId}}</small><details><summary>服务地址</summary><span>{{c.baseUrl}}</span></details></td><td>{{keyLabel(c.credentialId)}}<small>仅引用，不展示密钥</small></td><td><small>所属：{{teamLabel(c.ownerTeamId)}}</small><span>{{c.allowedTeamIds.length?'另授权 '+c.allowedTeamIds.map(teamLabel).join('、'):'仅所属团队'}}</span></td><td><span class="badge" :class="connectionState(c,catalog)==='available'?'info':'warn'">{{stateText[connectionState(c,catalog)]}}</span><small>未进行真实连接测试</small></td><td><div class="row-actions"><button class="link" @click="openConnection(c)">编辑与授权</button><button class="link" @click="showTest(c)">测试结果样例</button><button class="link" @click="toggleConnection(c)">{{c.enabled?'停用':'启用'}}</button><button class="link danger-text" @click="removeConnection(c)">删除</button></div></td></tr>
   </tbody></table><p v-if="!filteredConnections.length" class="empty">没有匹配的模型连接。可调整筛选或新增连接。</p></div>
   <div v-else-if="tab==='credentials'" class="table-wrap"><table class="data-table"><thead><tr><th>API Key</th><th>团队使用范围</th><th>关联模型</th><th>状态</th><th>操作</th></tr></thead><tbody>
    <tr v-for="k in filteredKeys" :key="k.id" :data-testid="'credential-'+k.id"><td><b>{{k.name}}</b><small>示例凭据 · 修订 {{k.revision}} · 不含真实密钥</small></td><td>{{accessLabel(k)}}</td><td><span v-for="c in catalog.connections.filter(c=>c.credentialId===k.id)" :key="c.id" class="block">{{c.name}}</span><span v-if="!catalog.connections.some(c=>c.credentialId===k.id)">尚未关联</span></td><td>{{k.enabled?'预览启用':'预览停用'}}</td><td><div class="row-actions"><button class="link" @click="openCredential(k)">编辑与授权</button><button class="link" @click="openCredential(k,true)">替换密钥</button><button class="link" @click="toggleKey(k)">{{k.enabled?'停用':'启用'}}</button><button class="link danger-text" @click="removeKey(k)">删除</button></div></td></tr>
   </tbody></table><p v-if="!filteredKeys.length" class="empty">没有匹配的 API Key。请新增示例凭据。</p></div>
   <div v-else class="team-grid"><article v-for="t in catalog.teams" :key="t.id" class="mini-card" :data-testid="'team-'+t.id"><h3>{{t.name}}</h3><p>可使用模型 {{visibleConnections(catalog,t.id).length}} 个 · 已授权凭据 {{catalog.credentials.filter(k=>permittedTeams(k).includes(t.id)).length}} 个</p><p class="muted">此处展示资源使用范围，不包含密钥查看权限。</p><div class="row-actions"><button class="secondary" @click="teamPreview=t.id">预览成员可选模型</button><button class="link" @click="openTeam(t.id)">编辑</button><button class="link danger-text" @click="removeTeam(t.id)">删除</button></div></article><p v-if="!catalog.teams.length" class="empty">请先新增一个预览团队。</p></div>
  </section>
  <section class="card section-gap live-models"><div class="toolbar"><h2 class="section-title">后端已接入模型</h2><button class="secondary" :disabled="busy" @click="load">刷新</button></div><p class="muted">从服务端内置 LLM 评估器读取当前模型元数据；不读取密钥。上方预览连接不会用于真实调用。</p><p v-if="error" role="alert">{{error}}</p><p v-else-if="busy">正在读取…</p><p v-else-if="!models.length">暂无已接入模型</p><table v-else class="data-table"><thead><tr><th>模型 ID</th><th>模型服务</th><th>来源</th><th>连接验证</th></tr></thead><tbody><tr v-for="m in models" :key="m.provider_id+m.model_id"><td>{{m.model_id}}</td><td>{{m.provider_id}}</td><td>服务端配置 · 只读</td><td>配置已加载；连通性以实际调用为准</td></tr></tbody></table></section>

  <el-dialog :model-value="formOpen" :title="modalTitle" width="min(760px,94vw)" :close-on-click-modal="false" :before-close="()=>close()" destroy-on-close>
   <p class="muted">前端交互预览 · 不写入后端，不产生真实授权或调用。</p><p v-if="formError" class="notice error" role="alert">{{formError}}</p>
   <div v-if="modal==='connection'" class="form-grid">
    <label class="field">连接名称<input class="input" v-model="connection.name" aria-label="连接名称" placeholder="例如：团队质量评分"/></label>
    <label class="field">所属团队<select class="input" v-model="connection.ownerTeamId" :disabled="!!connection.id" @change="resetConnectionAccess" aria-label="模型所属团队"><option v-for="t in catalog.teams" :value="t.id">{{t.name}}</option></select></label>
    <label class="field">接口协议<select class="input" v-model="connection.provider" aria-label="接口协议"><option value="openai-compatible">OpenAI 兼容</option></select></label>
    <label class="field">模型 ID<input class="input" v-model="connection.modelId" aria-label="模型 ID" placeholder="填写模型服务支持的精确 ID"/></label>
    <label class="field full">BaseURL<input class="input" v-model="connection.baseUrl" aria-label="BaseURL" placeholder="https://model.example.com/v1"/><small>仅 HTTPS，不包含 /chat/completions；不会访问此地址。</small></label>
    <label class="field full">API Key<select class="input" v-model="connection.credentialId" @change="updateCredential" aria-label="模型 API Key"><option value="">请选择已授权给所属团队的凭据</option><option v-for="k in keyOptions" :key="k.id" :value="k.id" :disabled="!k.enabled">{{k.name}}{{!k.enabled?'（已停用）':''}}</option></select><small>需要新凭据时，请先到“API Key”页新增预览凭据。</small></label>
    <fieldset class="field full grant-field"><legend>额外授权团队</legend><label v-for="t in grantOptions" :key="t.id" class="check-option"><input type="checkbox" v-model="connection.allowedTeamIds" :value="t.id"/>{{t.name}}</label><small>所属团队默认可用；其它团队必须也在凭据授权范围内。</small><small v-if="!grantOptions.length">该凭据未授权其它团队。</small></fieldset>
   </div>
   <div v-else-if="modal==='credential'||modal==='rotate'" class="form-grid">
    <label class="field">凭据名称<input class="input" v-model="credential.name" aria-label="凭据名称" :disabled="modal==='rotate'"/></label>
    <label class="field">所属团队<select class="input" v-model="credential.ownerTeamId" :disabled="!!credential.id" aria-label="凭据所属团队" @change="credential.allowedTeamIds=[]"><option v-for="t in catalog.teams" :key="t.id" :value="t.id">{{t.name}}</option></select></label>
    <label v-if="!credential.id||modal==='rotate'" class="field full">API Key<input class="input" type="password" :value="secret" autocomplete="new-password" aria-label="示例 API Key" @input="acceptExample" placeholder="仅接受 demo- 开头的示例值"/><small>请勿输入真实密钥；示例值只用于验证输入交互，保存后也不保留。</small><button type="button" class="link example-key" @click="fillExample">填入示例密钥</button></label>
    <p v-else class="field full muted">不回显原密钥；需要更新时使用“替换密钥”。</p>
    <fieldset v-if="modal!=='rotate'" class="field full grant-field"><legend>额外授权团队</legend><label v-for="t in catalog.teams.filter(t=>t.id!==credential.ownerTeamId)" :key="t.id" class="check-option"><input type="checkbox" v-model="credential.allowedTeamIds" :value="t.id"/>{{t.name}}</label><small>模型授权不能超出凭据的使用范围；撤销前需先调整关联模型。</small></fieldset>
    <p v-if="modal==='rotate'" class="field full">替换预览仅增加修订号，保留现有模型引用；不会改变真实密钥。</p>
   </div>
   <label v-else-if="modal==='team'" class="field">团队名称<input class="input" v-model="teamName" aria-label="团队名称" placeholder="用于前端授权预览"/><small>未连接真实组织、成员或登录系统。</small></label>
   <template #footer><button class="secondary" @click="close()">取消</button><button class="primary" @click="save">保存预览</button></template>
  </el-dialog>
  <el-dialog :model-value="!!testing" title="连接测试结果样例" width="min(660px,94vw)" @close="testing=null">
   <template v-if="testing"><h3>{{testing.name}}</h3><p class="muted">不发送请求，不消耗模型额度；下面仅展示反馈样式。</p><label class="field">结果场景<select class="input" v-model="scenario" aria-label="测试结果场景"><option value="success">成功样例</option><option value="unauthorized">凭据失效</option><option value="missing">模型不存在</option><option value="timeout">请求超时</option></select></label><article class="mini-card section-gap"><b>{{scenarios[scenario]?.title}}</b><p>{{scenarios[scenario]?.text}}</p></article><p class="muted">真实测试需要服务端安全代理接口；当前配置仍为“未验证”。</p></template>
   <template #footer><button class="secondary" @click="testing=null">关闭</button><button class="primary" disabled>真实连接测试 · 待接入</button></template>
  </el-dialog>
  <el-dialog :model-value="!!teamPreview" title="团队使用视图（预览）" width="min(660px,94vw)" @close="teamPreview=''">
   <h3>{{teamLabel(teamPreview)}}</h3><p class="muted">此选择只演示成员可用模型，不切换真实用户身份。</p><label class="field">成员可选模型<select class="input" v-model="memberModel" aria-label="成员可选模型"><option value="">请选择</option><option v-for="c in memberModels" :value="c.id">{{c.name}} · {{c.modelId}}</option></select></label><p v-if="!memberModels.length">当前团队没有预览可用模型，请检查授权、连接启停及凭据状态。</p><p v-if="memberModel">仅可使用模型，不提供 API Key 明文查看入口。预览选择不会加入正式评估器。</p>
   <template #footer><button class="secondary" @click="teamPreview=''">关闭</button></template>
  </el-dialog>
 </div>
</template>
<style scoped>
.preview-scope{font-size:13px;color:#64748b;margin:0 0 18px}.preview-scope .badge{margin-right:8px}.settings-card{min-width:0}.settings-filters{justify-content:flex-start;align-items:end}.settings-filters>.input{width:380px;max-width:100%}.settings-filters select{min-width:230px}.settings-filters .field{font-size:12px}
.row-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px 14px}.row-actions .link{font-size:13px;white-space:nowrap}.data-table td{max-width:290px;overflow-wrap:anywhere}.data-table td small,.block{display:block;font-size:12px;color:#64748b}.data-table details{margin:4px 0}.team-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.team-grid h3{margin-top:0}.danger-text{color:#c64444}.grant-field{border:1px solid #dce5e3;border-radius:6px;padding:12px;min-width:0}.grant-field legend{padding:0 5px}.check-option{display:flex;align-items:center;gap:8px}.check-option input{accent-color:#07ac8e}.example-key{text-align:left;align-self:flex-start}.live-models p{margin-bottom:0}.model-settings{min-width:0}
@media(max-width:1000px){.team-grid{grid-template-columns:1fr}.settings-filters{flex-wrap:wrap}}
</style>
