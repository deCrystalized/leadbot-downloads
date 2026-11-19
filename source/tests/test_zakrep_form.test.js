'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(){
 const code=fs.readFileSync(require.resolve('../ext/content'),'utf8');
 const start=code.indexOf('  function выбратьЗакреп('),end=code.indexOf('  // закреп города на дату визита',start);
 assert.ok(start>=0&&end>start,'actual form choice helpers must exist');
 const s={S:{zkChoice:'by',lead:{is_zakrep:true},zakrep:{text:'Мастер Сергей'}},keepEdits:()=>{},render:()=>{},h:(tag,attrs,...children)=>({tag,attrs,children})};
 vm.createContext(s);vm.runInContext(code.slice(start,end)+';globalThis.choose=выбратьЗакреп;globalThis.apply=применитьЗакреп;globalThis.view=закрепФорма;',s);return s;
}
test('choosing not by the city pin clears a previous true flag before CRM preparation',()=>{
 const s=fixture();s.choose('not');const lead={is_zakrep:true,service_comment:'Клиент просит позвонить'};s.apply(lead);
 assert.equal(s.S.zkChoice,'not');assert.equal(lead.is_zakrep,false);assert.equal(lead.service_comment,'Клиент просит позвонить');
 s.choose('');assert.equal(s.S.zkChoice,'');s.apply(lead);assert.equal(lead.is_zakrep,false);
});
test('all three choices remain available and neutral removes only the exact generated pin line',()=>{
 const s=fixture(),tree=s.view();const buttons=[];function walk(n){if(!n||typeof n!=='object')return;if(n.tag==='button')buttons.push(n);(n.children||[]).flat().forEach(walk)}walk(tree);
 const button=buttons.find(b=>b.children.includes('Не по закрепу'));assert.ok(button);button.attrs.onclick();assert.equal(s.S.zkChoice,'not');
 s.choose('by');const lead={service_comment:'Звонок'};s.apply(lead);s.apply(lead);assert.equal(lead.is_zakrep,true);assert.equal(lead.service_comment,'Звонок\nЗакреп: Мастер Сергей');
 s.choose('none');s.apply(lead);assert.equal(lead.is_zakrep,false);assert.equal(lead.service_comment,'Звонок');
 const neutral=buttons.find(b=>b.children.includes('Без закрепа'));assert.ok(neutral);neutral.attrs.onclick();assert.equal(s.S.zkChoice,'none');
 s.S.zkChoice='';const defaultTree=s.view();assert.equal(defaultTree.children[1].children[0].attrs['aria-pressed'],'true');
});
test('neutral choice survives reading the previous checked form state',()=>{
 const s=fixture();s.keepEdits=()=>{s.S.lead.is_zakrep=true;s.S.lead.service_comment='Позвонить за 15 минут\nЗакреп: Мастер Сергей'};
 s.choose('none');assert.equal(s.S.lead.is_zakrep,false);assert.equal(s.S.lead.service_comment,'Позвонить за 15 минут');
});
function creationFixture(choice){
 const s=fixture(),code=fs.readFileSync(require.resolve('../ext/content'),'utf8'),jobs=[],alerts=[];
 const lead={phone:'9001112233',addr:{street:'ул Ленина',building:'1'},city:'Оренбург',name:'Клиент',partner:'7',comment:'Собрать шкаф',service_comment:'Позвонить\nЗакреп: Мастер Сергей',is_zakrep:true};
 Object.assign(s,{S:{...s.S,id:'synthetic-pin-neutral',dir:'mnc',zkChoice:choice,lead,ctx:{messages:[]},prep:{ok:true,cityId:'synthetic-city',cityText:'Оренбург'},check:{ok:true,reviewed_policy:true}},
  формаЭтого:()=>true,задачаИдёт:()=>jobs.length?{ход:{}}:null,кнопкаФормы:()=>{},readForm:()=>({lead:structuredClone(lead),sel:{cityId:'synthetic-city'}}),
  отпечатокФормы:()=>'',panel:{querySelectorAll:()=>[],querySelector:()=>null},визитПроблема:()=>({}),прошлыйАдрес:()=>false,белаяНаБТ:()=>false,историяКлиента:()=>null,
  alertBox:x=>alerts.push(x),location:{origin:'https://synthetic.invalid'},LC_WORKFLOW:require('../ext/workflow'),LC_TG:{кодИсточника:()=>''},sentList:()=>[],кодАккаунта:()=>'',новыйId:()=> 'synthetic-job',копия:structuredClone,безКода:()=>'',
  минимумДоВизита:()=>60,визитАвто:()=>false,окноКлиента:()=>null,лидБот:()=>false,запустить:x=>jobs.push(x),dirName:()=> 'МНЧ',отмечено:()=>false});
 const start=code.indexOf('  function createNow()'),end=code.indexOf('  // снимок → задача:',start);
 vm.runInContext(code.slice(start,end)+';globalThis.createNowForTest=createNow;',s);
 const mainStart=code.indexOf('  function главнаяКнопка()'),mainEnd=code.indexOf('  const кратко =',mainStart);
 vm.runInContext(code.slice(mainStart,mainEnd)+';globalThis.mainForTest=главнаяКнопка;',s);
 return {s,jobs,alerts};
}
test('one ordinary create click works with an active city pin and no selection or neutral selection',()=>{
 for(const choice of ['',undefined,'none']){
  const {s,jobs,alerts}=creationFixture(choice),button=s.mainForTest();
  assert.equal(button.label,'Создать заявку в МНЧ');assert.equal(button.variants,undefined);
  s.createNowForTest();assert.equal(alerts.length,0);assert.equal(jobs.length,1);
  assert.equal(jobs[0].lead.is_zakrep,false);assert.equal(jobs[0].отписать.zakrepNot,false);
  assert.equal(jobs[0].lead.service_comment.includes('Закреп:'),false);assert.ok(jobs[0].lead.service_comment.includes('Позвонить'));
  s.createNowForTest();assert.equal(jobs.length,1,'second click must not schedule a second request');
 }
});
test('explicit pin and not-by-pin still produce distinct creation snapshots',()=>{
 for(const choice of ['by','not']){
  const {s,jobs,alerts}=creationFixture(choice);s.createNowForTest();assert.equal(alerts.length,0);assert.equal(jobs.length,1);
  assert.equal(jobs[0].lead.is_zakrep,choice==='by');assert.equal(jobs[0].отписать.zakrepNot,choice==='not');
  assert.equal(jobs[0].lead.service_comment.includes('Закреп: Мастер Сергей'),choice==='by');
 }
});
test('actual CRM serialization clears a template checkbox and verifies saved zero rather than the checkbox value',async()=>{
 const code=fs.readFileSync(require.resolve('../ext/crm'),'utf8'),crm=require('../ext/crm');
 const field='CustomerRequest[is_zakrep]';
 for(const selected of [false,true]){
  const hidden={name:field,type:'hidden',tagName:'INPUT',value:'0'},checkbox={name:field,type:'checkbox',tagName:'INPUT',value:'1',checked:true};
  const elements=[hidden,checkbox];elements[field]=[hidden,checkbox];const form={elements};
  const s={lead:{comment:'',is_zakrep:selected},form,setVal:crm._внутр.setVal,ДОМОФОН:crm._внутр.ДОМОФОН,полеВидаУслуг:()=>null,fetchDoc:async()=>({querySelector:()=>form})};
  vm.createContext(s);
  const start=code.indexOf("    const comment = String(lead.comment || '');",code.indexOf('// 2.2.3: сомнение в адресе')),end=code.indexOf('    // тип: Впервые',start);
  assert.ok(start>=0&&end>start);vm.runInContext('(function(){'+code.slice(start,end)+'})();',s);
  assert.equal(checkbox.checked,selected);const body=crm._внутр.serializeForm(form);assert.equal(body.getAll(field).at(-1),selected?'1':'0');
  const verifyStart=code.indexOf('  async function verifyCreated('),verifyEnd=code.indexOf('  /* СОЗДАНИЕ —',verifyStart);
  vm.runInContext(code.slice(verifyStart,verifyEnd)+';globalThis.verify=verifyCreated;',s);
  const correct=await s.verify('https://synthetic.invalid','1234567',body);assert.equal(correct.checked,1);assert.equal(correct.diffs.length,0);assert.equal(correct.fields[0],'закреп');
  checkbox.checked=!selected;const mismatch=await s.verify('https://synthetic.invalid','1234567',body);assert.equal(mismatch.diffs.length,1);assert.match(mismatch.diffs[0],/закреп/);
 }
});
test('actual createNow stops before reading or submitting a form with stale rules, a direct ban, or the wrong branch',()=>{
 const code=fs.readFileSync(require.resolve('../ext/content'),'utf8'),start=code.indexOf('  function createNow()'),end=code.indexOf('  // снимок → задача:',start);
 assert.ok(start>=0&&end>start);
 for(const check of [undefined,{ok:true,reviewed_policy:false},{ok:true,reviewed_policy:true,hard_block:true,reason:'Direct rule'},
    {ok:true,reviewed_policy:true,crm_route:{city_id:'709'}}]){
  const notes=[],s={S:{prep:{ok:true,cityId:'3'},check},формаЭтого:()=>true,alertBox:x=>notes.push(x),readForm:()=>{throw Error('must stop before transport')}};
  vm.createContext(s);vm.runInContext(code.slice(start,end)+';globalThis.run=createNow;',s);s.run();assert.equal(notes.length,1);
 }
});
