const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function frontend(bootstrap){
 const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
 const ctx=vm.createContext({document:{addEventListener(){}},window:{addEventListener(){}}});
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
