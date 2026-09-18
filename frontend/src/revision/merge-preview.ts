export type MergeSource={dataset_id:string;name:string;version:number;content_sha256:string;cases:any[]}
export type MergeRow={key:string;source:MergeSource;item:any;fingerprint:string;inputFingerprint:string;skills:string[]}
export function canonical(value:any):string {
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']'
 if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}'
 return JSON.stringify(value)
}
// Deliberately conservative: only remove generated identity fields, retain all other content.
function comparable(item:any){const {id,...rest}=item;return {...rest,turns:item.turns.map((t:any)=>{const {id,...turn}=t;return {...turn,expectations:(t.expectations??[]).map((e:any)=>{const {id,...expectation}=e;return expectation})}})}}
export function previewSources(sources:MergeSource[]){
 const rows:MergeRow[]=sources.flatMap(source=>source.cases.map(item=>({
  key:canonical([source.dataset_id,source.version,item.id]),source,item,
  fingerprint:canonical(comparable(item)),inputFingerprint:canonical(item.turns.map((t:any)=>t.input)),
  skills:[...new Set<string>(item.turns.flatMap((t:any)=>(t.expectations??[]).filter((e:any)=>e.kind==='skill_route'&&e.condition?.kind==='equals').map((e:any)=>e.condition?.expected).filter((v:any)=>typeof v==='string')))],
 })))
 const group=(key:'fingerprint'|'inputFingerprint')=>{const groups=new Map<string,MergeRow[]>();for(const r of rows)groups.set(r[key],[...(groups.get(r[key])??[]),r]);return [...groups.values()].filter(x=>x.length>1)}
 return {rows,duplicates:group('fingerprint'),differences:group('inputFingerprint').filter(g=>new Set(g.map(r=>r.fingerprint)).size>1)}
}
export const mergeService={available:false as const,reason:'合并服务未接入。当前仅本地预览，不创建评测集。'}
