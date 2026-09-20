import { test, expect } from '@playwright/test'
import { webcrypto } from 'node:crypto'
import { blankSample, parseSampleFile } from '../src/views/datasets/utils/sample-import'
import { exportSamples, sampleExportBlob } from '../src/views/datasets/utils/sample-export'
import type { DatasetVersion } from '../src/views/datasets/types/index'
import { http, httpRequest, ApiError } from '../src/utils/request'
if (!globalThis.crypto) Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
const a=blankSample('样本甲'), b=blankSample('样本乙')
a.turns[0].input={query:'输入甲'}; a.turns[0].required_tools=['lookup']
b.turns[0].input={query:'输入乙'}
const version={dataset_name:'导出测试',version:3,status:'published',cases:[a,b],content_sha256:'original'} as DatasetVersion
test('selected exports preserve expectations and never impersonate published version hashes',()=>{
 const before=JSON.stringify(version), data=exportSamples(version,[a.id])
 expect(data.cases).toHaveLength(1)
 expect(data.cases[0].turns[0].expectations).toEqual([expect.objectContaining({kind:'tool_call',tool:'lookup'})])
 expect(data).not.toHaveProperty('content_sha256')
 expect(JSON.stringify(version)).toBe(before)
 expect(exportSamples(version).cases).toHaveLength(2)
 expect(()=>exportSamples(version,[])).toThrow('至少')
 expect(()=>exportSamples(version,['unknown'])).toThrow('至少')
})
for(const format of ['json','xlsx'] as const) test(format+' export can be imported preserving samples and tool checks',async()=>{
 const blob=await sampleExportBlob(version,[a.id],format)
 const parsed=await parseSampleFile({name:'export.'+format,size:blob.size,arrayBuffer:()=>blob.arrayBuffer()})
 expect(parsed).toHaveLength(1);expect(parsed[0].name).toBe(a.name)
 expect(parsed[0].turns[0].input).toEqual(a.turns[0].input)
 expect(parsed[0].turns[0].required_tools).toEqual(['lookup'])
})
test('shared Axios handles raw/envelope/204 responses and does not double the API prefix',async()=>{
 const previous=http.defaults.adapter
 try{
  let data:unknown={value:3}
  http.defaults.adapter=async config=>{expect(config.url).toBe('/datasets');return {data,status:200,statusText:'OK',headers:{},config}}
  expect(await httpRequest('/api/datasets')).toEqual({value:3})
  data={code:'0',message:'ok',data:[1]};expect(await httpRequest('/datasets')).toEqual([1])
  http.defaults.adapter=async config=>({data:'',status:204,statusText:'No Content',headers:{},config})
  expect(await httpRequest('/datasets')).toBe('')
  http.defaults.adapter=async config=>({data,status:200,statusText:'OK',headers:{},config})
  data={code:'error',message:'blocked',data:null};await expect(httpRequest('/datasets')).rejects.toBeInstanceOf(ApiError)
 }finally{http.defaults.adapter=previous}
})
test('shared Axios preserves validation details and never retries a timed-out write',async()=>{
 const previous=http.defaults.adapter
 try{
  let calls=0
  http.defaults.adapter=async()=>{calls++;throw {isAxiosError:true,code:'ECONNABORTED',message:'timeout'}}
  await expect(httpRequest('/datasets',{method:'POST',data:{name:'test'}})).rejects.toMatchObject({status:0})
  expect(calls).toBe(1)
  const detail=[{message:'version conflict'}]
  http.defaults.adapter=async()=>{throw {isAxiosError:true,response:{status:422,data:{detail}}}}
  await expect(httpRequest('/datasets')).rejects.toMatchObject({status:422,detail})
 }finally{http.defaults.adapter=previous}
})
