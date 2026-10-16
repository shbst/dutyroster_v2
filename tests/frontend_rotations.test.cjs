const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function frontend(bootstrap){
 const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
 const ctx=vm.createContext({TextDecoder,TextEncoder,document:{addEventListener(){}},window:{addEventListener(){}}});
 vm.runInContext(source.slice(0,source.lastIndexOf('reload().catch')),ctx);
 ctx.bootstrap=bootstrap;
 vm.runInContext('B=bootstrap',ctx);
 return expression=>vm.runInContext(expression,ctx);
}

test('old bootstrap without rotation_sites renders all four rotations',()=>{
 const run=frontend({members:[]});
 for(const kind of ['anesthesia','outpatient','psychiatry','community']){
  const html=run(`rotationRow({kind:'${kind}',hospital:'',start:'2027-04-01',end:'2027-04-30'})`);
  assert.match(html,/name="hospital"/);
 }
 assert.match(run("placementOptions('anesthesia','shin_abuyama')"),/value="" selected>院内/);
 assert.doesNotMatch(run("placementOptions('anesthesia','')"),/新阿武山/);
 assert.match(run("placementOptions('psychiatry','shin_abuyama')"),/value="shin_abuyama" selected/);
 assert.match(run("placementOptions('community','remote')"),/value="remote" selected>へき地/);
});

test('missing, null and empty option lists use the default mapping',()=>{
 for(const bootstrap of [null,{}, {rotation_sites:null},{rotation_sites:{}},{rotation_sites:{anesthesia:[]}},{rotation_sites:{anesthesia:[null]}}]){
  assert.match(frontend(bootstrap)("placementOptions('anesthesia','')"),/>院内/);
 }
});

test('new metadata is used when available',()=>{
 const run=frontend({rotation_sites:{anesthesia:[['','院内']]}});
 assert.equal(run("placementOptions('anesthesia','')"),'<option value="" selected>院内</option>');
});

test('old servers receive remote kind so the prohibition remains effective',()=>{
 const run=frontend({});
 const payload=JSON.parse(run("JSON.stringify(rotationPayload([{kind:'community',hospital:'remote'},{kind:'community',hospital:'takatsuki_nearby'},{kind:'psychiatry',hospital:'shin_abuyama'}]))"));
 assert.deepEqual(payload,[{kind:'remote',hospital:''},{kind:'community',hospital:''},{kind:'psychiatry',hospital:'shin_abuyama'}]);
 assert.match(run("rotationRow({kind:'remote',hospital:'',start:'2027-04-01',end:'2027-04-30'})"),/value="remote" selected>へき地/);
});

test('new servers keep community placements unchanged',()=>{
 const run=frontend({rotation_sites:{community:[['takatsuki_nearby','高槻病院近傍'],['remote','へき地']]}});
 assert.equal(run("JSON.stringify(rotationPayload([{kind:'community',hospital:'remote'}]))"),'[{"kind":"community","hospital":"remote"}]');
});

test('anesthesia status renders both fulfilled and unmet priorities',()=>{
 const run=frontend({});
 const row={name:'麻酔科担当',start:'2027-04-01',end:'2027-04-30',all_met:false,checks:{weekday_night:{count:1,target:2,met:false},holiday_duty:{count:2,target:2,met:true},friday_night:{count:1,target:1,met:true}}};
 const html=run(`renderAnesthesiaStatus(${JSON.stringify([row])})`);
 assert.match(html,/麻酔科担当/);assert.match(html,/1 \/ 2回/);assert.match(html,/未達/);assert.match(html,/達成/);assert.match(html,/要確認/);
 assert.equal(run('renderAnesthesiaStatus([])'),'');
 assert.match(run('renderAnesthesiaStatus(undefined)'),/サーバーを再起動/);
});

test('working day settings show overrides and restore controls',()=>{
 const run=frontend({});
 const html=run(`renderWorkingDays({'2027-05-03':false,'2027-12-29':'休業'})`);
 assert.match(html,/2027-05-03/);
 assert.match(html,/data-action="reset-working-day"/);
 assert.match(html,/data-date="2027-05-03"/);
 assert.doesNotMatch(html,/2027-12-29/);
 assert.match(run('renderWorkingDays({})'),/平日扱いの指定はありません/);
});

test('empty slot offers checked lock and assigned slot keeps existing controls',()=>{
 const run=frontend({});
 run(`P={status:'draft',slots:[{id:1,date:'2027-04-03',kind:'day',number:1,member_id:null,locked:0}],members:[{id:2,name:'担当',color:'#ffffff',periods:[{start:'2026-04-01',end:'2028-03-31'}]}],summaries:{}}; modal=(title,body)=>{globalThis.body=body;}; slotModal(1);`);
 assert.match(run('body'),/type="checkbox" id="assign-locked" checked/);
 run('P.slots[0].member_id=2;slotModal(1)');
 assert.doesNotMatch(run('body'),/id="assign-locked"/);
 assert.match(run('body'),/この割り当てを固定/);
});

test('assignment sends checkbox value in the same request',async()=>{
 const run=frontend({});
 run(`perform=async(path,body)=>{globalThis.sent=body;};toast=()=>{};document.querySelector=()=>({checked:true});`);
 await run("action('assign',{dataset:{id:'1',member:'2'}})");
 assert.equal(run('sent.locked'),true);
 run('document.querySelector=()=>({checked:false})');
 await run("action('assign',{dataset:{id:'1',member:'2'}})");
 assert.equal(run('sent.locked'),false);
 run('document.querySelector=()=>null');
 await run("action('assign',{dataset:{id:'1',member:'2'}})");
 assert.equal(run("'locked' in sent"),false);
});

test('generation stream handles split UTF-8 and final result',async()=>{
 const run=frontend({});
 run(`globalThis.seen=[];globalThis.cancelled=false;globalThis.released=false;
 const encoded=new TextEncoder().encode(JSON.stringify({type:'progress',stage:'休日枠を充足中'})+'\\n'+JSON.stringify({type:'heartbeat'})+'\\n'+JSON.stringify({type:'result',plan:{id:12}}));
 let offset=0;globalThis.response={ok:true,body:{getReader:()=>({read:async()=>offset<encoded.length?{value:encoded.slice(offset,offset+=3),done:false}:{done:true},cancel:async()=>{cancelled=true},releaseLock:()=>{released=true}})}};`);
 const result=await run('readGenerationStream(response,e=>seen.push(e.stage))');
 assert.equal(result.id,12);
 assert.equal(run('seen[0]'),'休日枠を充足中');
 assert.equal(run('seen.length'),1);
 assert.equal(run('cancelled&&released'),true);
});

test('generation stream rejects errors and missing completion',async()=>{
 for(const event of [{type:'error',detail:['条件を確認してください']},{type:'progress',stage:'探索中'}]){
  const run=frontend({});
  run(`let done=false;const encoded=new TextEncoder().encode(${JSON.stringify(JSON.stringify(event)+'\n')});globalThis.response={ok:true,body:{getReader:()=>({read:async()=>done?{done:true}:(done=true,{value:encoded,done:false}),cancel:async()=>{},releaseLock:()=>{}})}};`);
  await assert.rejects(run('readGenerationStream(response,()=>{})'),event.type==='error'?/条件を確認/:/接続が途切れ/);
 }
});
