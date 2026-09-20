import {test,expect} from '@playwright/test'
import {webcrypto} from 'node:crypto'
import ExcelJS from 'exceljs'
import {zipSync,strToU8} from 'fflate'
import {parseCsv,rowsToSamples,normalizeCases,parseSampleFile} from '../src/views/datasets/utils/sample-import'
import {toApiCase} from '../src/api/datasets'
Object.defineProperty(globalThis,'crypto',{value:webcrypto,configurable:true})
const file=(name:string,bytes:Uint8Array)=>({name,size:bytes.length,arrayBuffer:async()=>bytes.slice().buffer as ArrayBuffer})
test('CSV handles BOM, quotes, commas, multiline and rejects malformed input',()=>{
 expect(parseCsv('\uFEFFcase_name,query\r\na,"hello,\n""world"""')[0]).toEqual({case_name:'a',query:'hello,\n"world"'})
 for(const text of ['a,a\n1,2','a,b\n1','a\n"bad'])expect(()=>parseCsv(text)).toThrow()
})
test('blank case ids remain distinct while shared ids form sorted multi-turn cases',()=>{
 expect(rowsToSamples([{case_id:'',case_name:'a',query:'one'},{case_id:'',case_name:'b',query:'two'}])).toHaveLength(2)
 const sample=rowsToSamples([{case_id:'x',case_name:'a',query:'two',turn_order:2},{case_id:'x',case_name:'a',query:'one',turn_order:1}])[0]
 expect(sample.turns.map(t=>t.input.query)).toEqual(['one','two'])
 expect(()=>rowsToSamples([{case_id:'x',case_name:'a',query:'one',turn_order:1},{case_id:'x',case_name:'a',query:'two',turn_order:1}])).toThrow()
})
test('canonical JSON preserves route, tools, policy, output and complex checks',()=>{
 const expectations=[{kind:'skill_route',condition:{kind:'one_of',allowed:['a','b']}},{kind:'tool_call',tool:'lookup',mode:'required'},{kind:'policy',policy_id:'p'},{kind:'output',path:null,condition:{kind:'equals',expected:'yes'}}]
 const sample=normalizeCases([{name:'a',turns:[{input:{query:'hi'},expectations}]}])[0]
 expect(toApiCase(sample).turns[0].expectations.map(({id,name,...e})=>e)).toEqual(expectations)
 expect(()=>normalizeCases([{name:'bad',turns:[{input:{},expectations:[{kind:'skill_route'}]}]}])).toThrow('condition')
})
test('JSON and CSV parse into editable samples with human expectations',async()=>{
 const csv=await parseSampleFile(file('sample.csv',strToU8('case_name,query,expected\na,hi,hello')))
 expect(csv[0].turns[0].expectations[0].condition).toEqual({kind:'equals',expected:'hello'})
 const json=await parseSampleFile(file('sample.json',strToU8(JSON.stringify({version:{cases:[toApiCase(csv[0])]}}))))
 expect(json[0].turns[0].input).toEqual({query:'hi'})
})
test('Excel Cases worksheet imports values but rejects formulas',async()=>{
 const book=new ExcelJS.Workbook(),sheet=book.addWorksheet('Cases')
 sheet.addRow(['case_name','query','expected']);sheet.addRow(['excel','hi','hello'])
 let bytes=await book.xlsx.writeBuffer()
 expect((await parseSampleFile(file('sample.xlsx',new Uint8Array(bytes))))[0].name).toBe('excel')
 sheet.getCell('B2').value={formula:'1+1',result:2}
 bytes=await book.xlsx.writeBuffer()
 await expect(parseSampleFile(file('sample.xlsx',new Uint8Array(bytes)))).rejects.toThrow('公式')
})
test('ZIP accepts supported samples and rejects paths, unsupported files and excessive entry counts',async()=>{
 const csv=strToU8('case_name,query\na,hi')
 expect(await parseSampleFile(file('a.zip',zipSync({'a.csv':csv})))).toHaveLength(1)
 for(const files of [{'../a.csv':csv},{'run.js':csv},Object.fromEntries(Array.from({length:21},(_,i)=>[i+'.csv',csv]))]){
  await expect(parseSampleFile(file('bad.zip',zipSync(files)))).rejects.toThrow()
 }
})
