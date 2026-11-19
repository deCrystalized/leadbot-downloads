'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const{create}=require('../ext/observer');
const h=(tag,attrs,...kids)=>({tag,attrs,kids:kids.flat()});
async function view(status){
 const ui=create({h,list:async()=>({items:[{id:'voice',state:'waiting',version:1}],more:false}),
  loadContext:async()=>({messages:[{id:'audio',direction:'in',body:'СЛОВА ИЗ АУДИО',
   voice_transcript:'СЛОВА ИЗ АУДИО',voice_transcript_status:status}]})});
 await ui.refresh();return JSON.stringify(ui.view());
}
test('ready done and completed all show the existing completed ASR text',async()=>{
 for(const status of ['ready','done','completed'])assert.match(await view(status),/СЛОВА ИЗ АУДИО/);
});
test('absent or unknown ASR status cannot look like a completed transcript',async()=>{
 for(const status of [undefined,'','unknown']){
  const text=await view(status);assert.doesNotMatch(text,/СЛОВА ИЗ АУДИО/);assert.match(text,/статус не подтверждён/);
 }
});
test('failed transcription is a visible failure distinct from processing',async()=>{
 for(const status of ['failed','error']){
  const text=await view(status);assert.doesNotMatch(text,/СЛОВА ИЗ АУДИО/);assert.match(text,/ошибка расшифровки/);
 }
 assert.doesNotMatch(await view('processing'),/СЛОВА ИЗ АУДИО/);
});
