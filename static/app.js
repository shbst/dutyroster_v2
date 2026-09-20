'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds={anesthesia:'麻酔科',outpatient:'外来研修',psychiatry:'精神科',community:'地域研修'};
// Older running servers do not yet return rotation_sites in bootstrap.
const defaultRotationSites={
 anesthesia:[['','院内']],outpatient:[['','院内']],
 psychiatry:[['','院内'],['shin_abuyama','新阿武山病院']],
 community:[['takatsuki_nearby','高槻病院近傍'],['remote','へき地']],
};
const colors=['#dce9fb','#e1efdf','#ece2f6','#f8e6dc','#dcf0ef','#f4e2ed','#e8e9ce','#e1e3f7'];
let B=null,P=null,monthIndex=0,selected=null,dragging=null,toastTimer,scrollTimer;
let route=()=>location.hash.slice(1).split('/')[0]||'home';
async function api(path,method='GET',body){
 const r=await fetch('/api'+path,{method,cache:'no-store',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
 if(r.status===405&&method==='DELETE'&&path.startsWith('/plans/'))throw Error('接続先は削除機能のない旧サーバーです。WSLでサーバーを再起動し、接続先のポートを確認してください。');
 if(!r.ok){let e=await r.json().catch(()=>({detail:'通信できませんでした。'}));let d=e.detail;throw Error(Array.isArray(d)?d.map(x=>typeof x==='string'?x:x.msg).join('\n'):(d||'処理に失敗しました'));}return r.json();
}
function toast(msg,error=false){clearTimeout(toastTimer);const t=$('#toast');t.textContent=msg;t.className=error?'error':'';t.hidden=false;toastTimer=setTimeout(()=>t.hidden=true,error?12000:4500);}
function modal(title,body){$('#dialog-content').innerHTML=`<div class="dialog-header"><h2>${esc(title)}</h2><button data-action="close" aria-label="閉じる">×</button></div>${body}`;if(!$('#dialog').open)$('#dialog').showModal();}
function close(){ $('#dialog').close(); }
function head(kicker,title,sub,actions=''){return `<div class="page-head"><div><div class="eyebrow">${kicker}</div><h1>${title}</h1><p>${sub}</p></div><div class="actions">${actions}</div></div>`;}
const btn=(label,action,cls='',extra='')=>`<button type="button" class="${cls}" data-action="${action}" ${extra}>${label}</button>`;
function planRows(){return B.plans.length?`<div class="plan-list">${B.plans.map(p=>`<a class="plan-row" href="#calendar/${p.id}"><div><strong>${esc(p.name)}</strong><small>${p.start.replaceAll('-','/')} — ${p.end.replaceAll('-','/')}</small></div><div class="actions"><span class="pill ${p.status==='final'?'green':''}">${p.status==='final'?'確定':'下書き'}</span><span>↗</span></div></a>`).join('')}</div>`:'<div class="card empty"><p>まだ当直表がありません。メンバーを登録して、最初の当直表を作りましょう。</p></div>';}
function home(){
 const active=B.members.filter(m=>!m.archived).length;
 $('#app').innerHTML=head('YOUR DUTY WORKSPACE','無理のない当直を、みんなで。','条件に沿って作成し、カレンダーで直感的に調整。')+
 `<div class="welcome-grid"><section class="card start-card"><div><div class="step-line"><b>01 メンバー登録</b><span>—</span><b>02 自動生成</b><span>—</span><b>03 調整・確定</b></div><h2>次の当直表をつくる</h2><p>研修の予定と勤務の間隔を考慮して、<br>一人ひとりにバランスのよい割り当てを。</p></div><div class="actions">${btn('＋ 当直表を作成','new-plan','primary')}<a class="text-button" href="#members">メンバーを管理 ↗</a></div></section><section class="card stats-card"><div class="stat-row"><span class="muted">登録メンバー</span><strong>${active}<small>名</small></strong></div><div class="stat-row"><span class="muted">保存した当直表</span><strong>${B.plans.length}<small>件</small></strong></div><div class="stat-row"><span class="muted">対象コホート</span><strong>2026<small>年4月入職</small></strong></div></section></div>`+
 `<div class="section-title"><h2>保存した当直表</h2><a class="muted" href="#calendar">カレンダーへ ↗</a></div>${planRows()}`+
 `<div class="section-title"><h2>割り当てのルール</h2><span class="pill">自動生成・手動編集に適用</span></div><div class="rules-grid">${[['必須条件','必ず守るルール',B.hard_rules,'✓',''],['優先条件','可能な範囲で調整するルール',B.soft_rules,'≈','soft']].map(([t,sub,rs,icon,cl])=>`<section class="card card-pad"><div class="rule-title"><span class="rule-icon ${cl}">${icon}</span><div><h2>${t}</h2><small class="muted">${sub}</small></div></div><ol class="rule-list">${rs.map((r,i)=>`<li><span>${String(i+1).padStart(2,'0')}</span><div>${esc(r)}</div></li>`).join('')}</ol></section>`).join('')}</div>`+
 `<div class="note">名称はすべて「当直」で統一。希望日・外科副直・振休申請は対象外です。通常業務を含む休日確保や、麻酔科への事前確認はこのアプリでは判定しません。</div><div class="section-title"><h2>病院独自の休日</h2>${btn('＋ 休日を登録','holiday')}</div><p class="muted">土日・日本の祝日は自動で反映します。年末年始などは追加登録できます。</p><div class="actions">${Object.entries(B.holidays).map(([d,n])=>`<span class="pill">${d} ${esc(n)}</span>`).join('')||'<small class="muted">追加の休日はありません</small>'}</div>`;
}
function members(){
 $('#app').innerHTML=head('MEMBERS','メンバー','当直対象期間と、研修の予定を登録します。',btn('＋ メンバーを登録','new-member','primary'))+
 (B.members.length?`<div class="member-grid">${B.members.map(m=>`<section class="card member-card ${m.archived?'archived':''}"><div class="member-top"><span class="avatar" style="background:${m.color}">${esc(m.name.slice(0,1))}</span><div><h2>${esc(m.name)}</h2><small class="muted">2026年4月入職 · 成人系${m.archived?' · 非表示':''}</small></div></div><small class="eyebrow">当直対象期間</small>${m.periods.map(p=>`<p>${p.start.replaceAll('-','/')} — ${p.end.replaceAll('-','/')}</p>`).join('')}<div class="actions"><span class="pill">研修 ${m.rotations.length}件</span>${btn('詳細・編集','edit-member','',`data-id="${m.id}"`)}</div></section>`).join('')}</div>`:`<div class="card empty"><div class="empty-icon">♧</div><h2>まずはメンバーの登録から</h2><p>在籍期間に応じた公平な割り当てを行います。</p>${btn('メンバーを登録','new-member','primary')}</div>`)+
 '<p class="footer-note">2027年3月までは1年目、2027年4月からは2年目の回数条件を適用します。対象期間が終了した人は、その後の生成対象から自動で外れます。</p>';
}
function periodRow(p={start:'2026-04-01',end:'2028-03-31'}){return `<div class="repeat-row period-row"><div class="form-row"><label>開始日<input type="date" name="start" value="${esc(p.start)}" required min="2026-04-01" max="2028-03-31"></label><label>終了日<input type="date" name="end" value="${esc(p.end)}" required min="2026-04-01" max="2028-03-31"></label></div>${btn('削除','remove-row','remove')}</div>`;}
function placementOptions(kind,current){
 const received=B?.rotation_sites?.[kind];
 const valid=Array.isArray(received)&&received.length>0&&received.every(o=>Array.isArray(o)&&o.length===2&&o.every(v=>typeof v==='string'));
 const options=valid?received:defaultRotationSites[kind];
 if(!options)throw Error('研修科を選択し直してください。');
 const selected=options.some(([value])=>value===current)?current:options[0][0];
 return options.map(([value,label])=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(label)}</option>`).join('');
}
function rotationPayload(rotations){
 // Preserve the remote-duty prohibition when saving to a pre-update server.
 if(Array.isArray(B?.rotation_sites?.community))return rotations;
 return rotations.map(r=>r.kind==='community'
  ?{...r,kind:r.hospital==='remote'?'remote':'community',hospital:''}:r);
}
function rotationRow(r={kind:'anesthesia',hospital:'',start:'2027-04-01',end:'2027-04-30'}){
 if(r.kind==='remote')r={...r,kind:'community',hospital:'remote'};
 return `<div class="repeat-row rotation-row"><div class="form-row"><label>研修科<select name="kind">${Object.entries(kinds).map(([k,v])=>`<option value="${k}" ${r.kind===k?'selected':''}>${v}</option>`).join('')}</select></label><label>配属先<select name="hospital">${placementOptions(r.kind,r.hospital)}</select></label></div><div class="form-row"><label>開始日<input name="start" type="date" value="${esc(r.start)}" required></label><label>終了日<input name="end" type="date" value="${esc(r.end)}" required></label></div>${btn('削除','remove-row','remove')}</div>`;
}
function eventRow(e={date:'',kind:'counseling'}){return `<div class="repeat-row event-row"><div class="form-row"><label>日付<input type="date" name="date" value="${esc(e.date)}" required></label><label>種類<select name="kind">${[['counseling','土曜カウンセリング'],['training','新阿武山：追加研修日'],['no_training','新阿武山：研修なし']].map(([k,l])=>`<option value="${k}" ${e.kind===k?'selected':''}>${l}</option>`).join('')}</select></label></div>${btn('削除','remove-row','remove')}</div>`;}
function memberForm(id){
 const m=B.members.find(x=>x.id===Number(id))||{name:'',color:colors[B.members.length%colors.length],periods:[{start:'2026-04-01',end:'2028-03-31'}],rotations:[],events:[]};
 modal(id?'メンバーを編集':'メンバーを登録',`<form id="member-form" data-id="${id||''}"><div class="form-row"><label>名前<input name="name" value="${esc(m.name)}" maxlength="40" required placeholder="例：山田 太郎"></label><label style="flex:0">表示色<input name="color" type="color" value="${m.color}"></label></div><div class="form-section"><h3>当直対象期間</h3><div id="periods">${m.periods.map(periodRow).join('')}</div>${btn('＋ 対象期間を追加','add-period','text-button')}</div><div class="form-section"><h3>ローテーション</h3><div id="rotations">${m.rotations.map(rotationRow).join('')}</div>${btn('＋ 研修期間を追加','add-rotation','text-button')}</div><div class="form-section"><h3>個別の研修日</h3><p class="muted" style="font-size:.8rem">新阿武山病院の研修は原則平日です。例外日も登録できます。</p><div id="events">${m.events.map(eventRow).join('')}</div>${btn('＋ 研修日を追加','add-event','text-button')}</div>${id?`<label class="form-section"><input name="archived" type="checkbox" ${m.archived?'checked':''}>新規生成の対象から外す（過去の記録は保持）</label>`:''}<div class="dialog-actions">${btn('キャンセル','close')}<button class="primary" type="submit">保存する</button></div></form>`);
}
function newPlan(){modal('当直表を作成',`<form id="plan-form"><label>タイトル<input name="name" value="当直表" required maxlength="80"></label><div class="form-grid"><label>開始日<input name="start" type="date" value="2027-04-01" min="2026-04-01" max="2028-03-31" required></label><label>終了日<input name="end" type="date" value="2027-04-30" min="2026-04-01" max="2028-03-31" required></label></div><div class="note">休日は日直・当直各1枠、月〜金は祝日を含め週3日を用意します。作成後に2枠目を指定できます。</div><div class="dialog-actions">${btn('キャンセル','close')}<button type="submit" class="primary">カレンダーを作成</button></div></form>`);}
function calendarEmpty(){ $('#app').innerHTML=head('CALENDAR','当直カレンダー','期間と必要な枠を決めて、割り当てを始めましょう。',btn('＋ 新しい当直表','new-plan','primary'))+planRows(); }
function fmtMonth(m){const [y,n]=m.split('-');return `${y}年 ${Number(n)}月`;}
function monthPage(month){
 const [y,m]=month.split('-').map(Number),first=new Date(y,m-1,1).getDay(),days=new Date(y,m,0).getDate(); let cells='';
 const names=Object.fromEntries(P.members.map(m=>[m.id,m]));
 for(let i=0;i<Math.ceil((first+days)/7)*7;i++){
  const n=i-first+1,ds=`${y}-${String(m).padStart(2,'0')}-${String(n).padStart(2,'0')}`;
  if(n<1||n>days||!P.days[ds]){cells+='<div class="day outside"></div>';continue;}
  const info=P.days[ds];let body='';
  for(const kind of info.holiday?['day','night']:['night']){
   const ss=P.slots.filter(s=>s.date===ds&&s.kind===kind),on=ss.filter(s=>s.enabled);
   body+=`<div class="slot-group"><div class="slot-group-label"><span>${kind==='day'?'日直':'当直'}</span></div>`;
   for(const s of on){const person=names[s.member_id];body+=`<button class="slot ${person?'':'empty-slot'} ${s.locked?'locked':''} ${selected===s.id?'selected':''}" data-action="slot" data-id="${s.id}" ${person&&!s.locked&&P.status!=='final'?'draggable="true"':''} style="${person?`background:${person.color}`:''}" aria-label="${ds} ${kind==='day'?'日直':'当直'} ${s.number}枠目 ${esc(person?.name||'未割り当て')}${s.locked?' 固定':''}"><span class="name">${esc(person?.name||'未割当')}</span></button>`;}
   const add=ss.find(s=>!s.enabled);
   if(add&&P.status!=='final')body+=btn(on.length?'＋2枠':'＋枠','enable-slot','add-slot',`data-id="${add.id}" aria-label="${ds} ${kind==='day'?'日直':'当直'} ${on.length?'2枠目を追加':'枠を追加'}"`);
   body+='</div>';
  }
  cells+=`<div class="day ${info.holiday?'holiday':''}"><div class="day-header"><span class="date-number">${n}</span><span class="holiday-name" title="${esc(info.name)}">${esc(info.name)}</span></div>${body}</div>`;
 }
 return `<section class="month-page" aria-label="${fmtMonth(month)}"><div class="weekday-row">${[...'日月火水木金土'].map(d=>`<span>${d}</span>`).join('')}</div><div class="calendar-grid">${cells}</div></section>`;
}
function renderCalendar(){
 if(!P){calendarEmpty();return;}
 monthIndex=Math.min(monthIndex,P.months.length-1);
 const final=P.status==='final';
 $('#app').innerHTML=head('CALENDAR','当直カレンダー','枠を指定して生成。担当者をタップすると編集できます。',btn('＋ 新規作成','new-plan'))+
 `<div class="period-bar"><div><strong>${esc(P.name)}</strong> <span class="pill ${final?'green':''}">${final?'確定':'下書き・自動保存'}</span><div class="muted" style="margin-top:7px">${P.start.replaceAll('-','/')} — ${P.end.replaceAll('-','/')} · 案 #${P.id}（他の案と独立）</div></div><div class="actions"><select id="plan-select" aria-label="保存した当直表">${B.plans.map(p=>`<option value="${p.id}" ${P.id===p.id?'selected':''}>#${p.id} ${esc(p.name)} · ${p.start}</option>`).join('')}</select>${btn('当直表を削除','delete-plan','danger')}</div></div>`+
 `<div class="calendar-toolbar"><div class="month-controls">${btn('‹','prev','icon-btn','aria-label="前の月"')}<h2 id="month-title">${fmtMonth(P.months[monthIndex])}</h2>${btn('›','next','icon-btn','aria-label="次の月"')}</div><div class="actions">${!final?btn('↶ 取り消し','undo')+btn('✧ 自動生成','generate','primary'):''}${btn('PDF 出力','pdf')}${btn(final?'編集を再開':'最終確定',final?'reopen':'finalize',final?'':'mint-btn')}</div></div>`+
 `<div id="selection"></div><div class="calendar-shell"><div class="month-track" id="month-track">${P.months.map(monthPage).join('')}</div><div class="legend"><span>← 横スクロール・スワイプで月を移動 →</span><span><strong>日直</strong> 9:00〜17:00　 <strong>当直</strong> 17:00〜翌日</span></div></div><div id="summary"></div><div id="diagnostics"></div><p class="footer-note">当直の終了時間は研修時期で異なります。確定前に院内の運用をご確認ください。勤務間隔は日付の差で表示しています。</p><details class="footer-note"><summary>最近の変更</summary>${P.history.map(h=>`<div>${esc(h.created_at)} · ${esc(h.action)}</div>`).join('')||'変更履歴はありません'}</details>`;
 const track=$('#month-track');track.scrollLeft=track.clientWidth*monthIndex;
 track.addEventListener('scroll',()=>{clearTimeout(scrollTimer);scrollTimer=setTimeout(()=>{const i=Math.round(track.scrollLeft/track.clientWidth);if(i!==monthIndex&&P.months[i]){monthIndex=i;$('#month-title').textContent=fmtMonth(P.months[i]);renderSummary();}},80);},{passive:true});
 renderSummary();renderSelection();
}
function renderAnesthesiaStatus(rows){
 if(!rows)return '<p class="note">麻酔科の内訳表示にはPythonサーバーの更新が必要です。サーバーを再起動して再読み込みしてください。</p>';
 if(!rows.length)return '';
 const cell=c=>`<td>${c.count} / ${c.target}回<br><span class="pill ${c.met?'green':'amber'}">${c.met?'達成':'未達'}</span></td>`;
 return `<section class="card summary-card"><div class="summary-head"><h2>麻酔科の内訳</h2><span class="pill">優先条件</span></div><div class="table-scroll"><table><thead><tr><th>メンバー・研修期間</th><th>平日当直<br>目安2回</th><th>休日系<br>目安2回</th><th>金曜当直<br>目安1回</th><th>判定</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.name)}<br><small class="muted">${esc(r.start)} 〜 ${esc(r.end)}</small></td>${cell(r.checks.weekday_night)}${cell(r.checks.holiday_duty)}${cell(r.checks.friday_night)}<td><span class="pill ${r.all_met?'green':'amber'}">${r.all_met?'達成':'要確認'}</span></td></tr>`).join('')}</tbody></table></div><p class="footer-note" style="padding:0 20px 16px">この案・表示月の麻酔科研修期間内を集計。休日系は休日日直または明け休日の当直です。金曜当直は平日当直と休日系に重複計上できます。各目安以上で達成とし、未達でも保存・確定できます。</p></section>`;
}
function renderSummary(){
 if(!P)return;const month=P.months[monthIndex],rs=P.summaries[month]||[],slots=P.slots.filter(s=>s.enabled&&s.date.startsWith(month)),filled=slots.filter(s=>s.member_id).length;
 $('#summary').innerHTML=`<section class="card summary-card"><div class="summary-head"><div><h2>メンバー別集計</h2><small class="muted">${fmtMonth(month)} · 変更をリアルタイムに反映</small></div><span class="pill ${filled===slots.length?'green':''}">${filled} / ${slots.length} 枠を配置</span></div><div class="table-scroll"><table><thead><tr><th>メンバー</th><th>平日当直</th><th>休日日直</th><th>休日当直</th><th>合計</th><th>最短間隔</th></tr></thead><tbody>${rs.map(r=>`<tr><td><span class="table-name"><i class="color-dot" style="background:${r.color}"></i>${esc(r.name)}</span></td><td>${r.weekday_night}</td><td>${r.holiday_day}</td><td>${r.holiday_night}</td><td><strong class="total-badge">${r.total}</strong></td><td class="${r.min_gap&&r.min_gap<5?'gap-short':''}">${r.min_gap===null?'—':`${r.min_gap}日`}</td></tr>`).join('')||'<tr><td colspan="6">この月の当直対象メンバーがいません。</td></tr>'}</tbody></table></div></section>`;
 const anesthesia=P.anesthesia_checks?.[month];
 $('#summary').insertAdjacentHTML('beforeend',renderAnesthesiaStatus(anesthesia));
 const unfilled=P.unfilled.filter(s=>s.date.startsWith(month));
 const warnings=[];
 for(const r of rs){if(r.min_gap!==null&&r.min_gap<5)warnings.push(`${r.name}：最短間隔が${r.min_gap}日です。可能なら勤務を離してください。`);}
 for(const r of anesthesia||[]){
  const labels={weekday_night:'平日当直',holiday_duty:'休日系',friday_night:'金曜当直'};
  const missing=Object.entries(r.checks).filter(([,c])=>!c.met).map(([key,c])=>`${labels[key]} ${c.count}/${c.target}回`);
  if(missing.length)warnings.push(`${r.name}（麻酔科 ${r.start}〜${r.end}）：${missing.join('、')}が目安に未達です（優先条件）。`);
 }
 $('#diagnostics').innerHTML=(P.errors.length?`<div class="issues">${P.errors.map(esc).join('<br>')}</div>`:'')+(unfilled.length?`<details class="issues" ${P.last_run?'open':''}><summary>未割り当て ${unfilled.length}枠</summary><ul>${unfilled.map(s=>`<li>${s.date} ${s.kind==='day'?'日直':'当直'} ${s.number}枠目：${P.last_run?esc(s.reason):'自動生成、または担当者を選択してください。'}</li>`).join('')}</ul></details>`:'')+(warnings.length?`<details class="issues"><summary>勤務バランスの確認 ${warnings.length}件</summary><ul>${warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`:'');
}
function renderSelection(){if(!$('#selection'))return;const s=P.slots.find(s=>s.id===selected);$('#selection').innerHTML=s?`<div class="selection-bar"><span>${s.date}の担当者を移動・交換します。移動先の枠をタップ。</span>${btn('キャンセル','cancel-select','text-button')}</div>`:'';}
function slotModal(id){
 const s=P.slots.find(s=>s.id===id);if(!s)return;
 if(selected!==null){if(selected===id){selected=null;renderCalendar();return;}return perform('/assignment',{slot_id:selected,target_id:id}).then(()=>{selected=null;renderCalendar();toast('担当者を交換・移動しました');});}
 const person=P.members.find(m=>m.id===s.member_id),month=s.date.slice(0,7),rs=P.summaries[month]||[];
 const title=`${s.date.slice(5).replace('-','/')} ${s.kind==='day'?'日直':'当直'} · ${s.number}枠目`;
 if(P.status==='final'){modal(title,`<p>${esc(person?.name||'未割り当て')}</p><div class="note">変更するには「編集を再開」を押してください。</div>`);return;}
 modal(title,`<p class="muted">${person?`現在の担当：${esc(person.name)}`:'担当者を選択してください。'}${s.locked?'（固定中）':''}</p>${person?`<div class="actions" style="margin-bottom:20px">${btn(s.locked?'固定を解除':'この割り当てを固定','lock','',`data-id="${id}"`)}${!s.locked?btn('移動・交換','select-source','',`data-id="${id}"`)+btn('割り当てを解除','unassign','danger',`data-id="${id}"`):''}</div>`:''}${!s.locked?`<div class="choice-list">${P.members.filter(m=>!m.archived&&m.periods.some(p=>p.start<=s.date&&s.date<=p.end)).map(m=>{const r=rs.find(r=>r.id===m.id);return `<button class="choice" data-action="assign" data-id="${id}" data-member="${m.id}"><span class="person"><i class="color-dot" style="background:${m.color}"></i>${esc(m.name)}</span><small>今月 ${r?.total||0}回${m.id===s.member_id?' ✓':''}</small></button>`;}).join('')||'<p class="muted">当直対象期間に該当するメンバーがいません。</p>'}</div><p class="footer-note">選択時に研修条件・連日勤務・月の上限をチェックします。</p>`:''}${!person?`<div class="dialog-actions">${btn('この枠を無効にする','disable-slot','danger',`data-id="${id}"`)}</div>`:''}`);
}
async function loadPlan(id){P=await api('/plans/'+id);monthIndex=Math.min(monthIndex,P.months.length-1);selected=null;localStorage.setItem('duty-plan',String(id));renderCalendar();}
async function perform(path,body={}){P=await api(`/plans/${P.id}${path}`,'POST',{version:P.version,...body});close();renderCalendar();}
async function reload(){B=await api('/bootstrap');await render();}
async function render(){
 const notice=$('#server-notice');
 notice.hidden=Number(B.api_version||0)>=3;
 notice.className='note';
 notice.textContent=notice.hidden?'':'更新前のPythonサーバーに接続しています。同じ期間の複数案と当直表の削除を使うには、サーバーを停止し、WSLで「bash run-wsl.sh」を実行してから再読み込みしてください。ブラウザーの再読み込みだけでは更新されません。';
 $$('[data-nav]').forEach(n=>n.classList.toggle('active',n.dataset.nav===route()));
 if(route()==='members')members();else if(route()==='calendar'){
  const id=Number(location.hash.split('/')[1]||localStorage.getItem('duty-plan'));const valid=B.plans.find(p=>p.id===id)||B.plans[0];
  if(valid)await loadPlan(valid.id);else{P=null;calendarEmpty();}
 }else home();
}
async function action(a,el){
 const id=Number(el.dataset.id);
 switch(a){
 case 'close':close();break;
 case 'new-plan':newPlan();break;
 case 'new-member':memberForm();break;
 case 'edit-member':memberForm(id);break;
 case 'add-period':$('#periods').insertAdjacentHTML('beforeend',periodRow());break;
 case 'add-rotation':$('#rotations').insertAdjacentHTML('beforeend',rotationRow());break;
 case 'add-event':$('#events').insertAdjacentHTML('beforeend',eventRow());break;
 case 'remove-row':el.closest('.repeat-row').remove();break;
 case 'holiday':modal('病院独自の休日を追加',`<form id="holiday-form"><label>日付<input name="date" type="date" min="2026-04-01" max="2028-03-31" required></label><label>名称<input name="name" placeholder="例：年末年始休業" required maxlength="40"></label><div class="dialog-actions"><button type="submit" class="primary">登録する</button></div></form>`);break;
 case 'prev':case 'next':{const i=Math.max(0,Math.min(P.months.length-1,monthIndex+(a==='prev'?-1:1)));$('#month-track').scrollTo({left:$('#month-track').clientWidth*i,behavior:'smooth'});break;}
 case 'slot':await slotModal(id);break;
 case 'enable-slot':case 'disable-slot':P=await api(`/plans/${P.id}/slots/${id}`,'PUT',{version:P.version,enabled:a==='enable-slot'});close();renderCalendar();break;
 case 'assign':await perform('/assignment',{slot_id:id,member_id:Number(el.dataset.member)});toast('担当者を保存しました');break;
 case 'unassign':await perform('/assignment',{slot_id:id,member_id:null});break;
 case 'lock':await perform('/assignment',{slot_id:id,locked:!P.slots.find(s=>s.id===id).locked});break;
 case 'select-source':selected=id;close();renderCalendar();break;
 case 'cancel-select':selected=null;renderCalendar();break;
 case 'generate':modal('自動生成しますか？',`<p>この表の対象期間全体を生成します。固定した担当者は維持し、それ以外の割り当ては作り直します。</p><div class="note">まず必要な2枠目を追加してください。生成後は「取り消し」で直前の状態に戻せます。</div><div class="dialog-actions">${btn('キャンセル','close')}${btn('自動生成を開始','run-generate','primary')}</div>`);break;
 case 'run-generate':close();$('#busy').hidden=false;try{await perform('/generate');toast('当直表を生成しました。集計と未割り当てをご確認ください。');}finally{$('#busy').hidden=true;}break;
 case 'undo':await perform('/undo');toast('直前の変更を取り消しました');break;
 case 'finalize':modal('当直表を確定',`<p>未割り当てと必須条件を確認し、現在の当直表を確定します。</p><p class="muted">勤務間隔や診療科への確認も済ませてから確定してください。</p><div class="dialog-actions">${btn('戻る','close')}${btn('確定する','confirm-finalize','primary')}</div>`);break;
 case 'confirm-finalize':await perform('/finalize');B=await api('/bootstrap');toast('当直表を確定しました');break;
 case 'reopen':await perform('/reopen');B=await api('/bootstrap');break;
 case 'delete-plan':
  if(Number(B.api_version||0)<3)throw Error('削除機能を使うにはPythonサーバーの再起動が必要です。WSLで「bash run-wsl.sh」を実行してください。');
  modal('当直表を削除しますか？',`<p><strong>${esc(P.name)}（案 #${P.id}）</strong><br>${P.start} 〜 ${P.end}</p><p>この案の割り当てと変更履歴を削除します。この操作は取り消せません。メンバー登録と他の案は残ります。</p><div class="dialog-actions">${btn('キャンセル','close')}${btn('この当直表を削除','confirm-delete-plan','danger')}</div>`);break;
 case 'confirm-delete-plan':
  await api(`/plans/${P.id}`,'DELETE',{version:P.version});close();P=null;selected=null;monthIndex=0;localStorage.removeItem('duty-plan');B=await api('/bootstrap');
  if(location.hash==='#calendar')await render();else location.hash='calendar';
  toast('当直表を削除しました');break;
 case 'pdf':window.open(`/api/plans/${P.id}/pdf`,'_blank','noopener');break;
 }
}
document.addEventListener('click',async e=>{if(Date.now()<suppressClickUntil){e.preventDefault();return;}const el=e.target.closest('[data-action]');if(!el)return;try{await action(el.dataset.action,el);}catch(err){toast(err.message,true);}});
document.addEventListener('submit',async e=>{
 e.preventDefault();const f=e.target,submit=$('[type=submit]',f);if(submit)submit.disabled=true;
 try{
  if(f.id==='member-form'){
   const rows=sel=>$$(sel,f).map(row=>Object.fromEntries($$('input,select',row).map(i=>[i.name,i.value])));
   const body={name:f.elements.name.value,color:f.elements.color.value,archived:!!f.elements.archived?.checked,periods:rows('.period-row'),rotations:rotationPayload(rows('.rotation-row')),events:rows('.event-row')};
   await api('/members'+(f.dataset.id?'/'+f.dataset.id:''),f.dataset.id?'PUT':'POST',body);close();await reload();toast('メンバーを保存しました');
  }else if(f.id==='plan-form'){
   const body=Object.fromEntries(new FormData(f));const p=await api('/plans','POST',body);close();B=await api('/bootstrap');monthIndex=0;location.hash='calendar/'+p.id;
  }else if(f.id==='holiday-form'){
   await api('/holidays','POST',Object.fromEntries(new FormData(f)));close();await reload();toast('休日を登録しました');
  }
 }catch(err){toast(err.message,true);}finally{if(submit)submit.disabled=false;}
});
document.addEventListener('change',e=>{
 if(e.target.id==='plan-select'){monthIndex=0;location.hash='calendar/'+e.target.value;}
 if(e.target.matches('.rotation-row select[name="kind"]')){
  const placement=$('select[name="hospital"]',e.target.closest('.rotation-row'));
  placement.innerHTML=placementOptions(e.target.value,placement.value);
 }
});
document.addEventListener('dragstart',e=>{const s=e.target.closest('.slot[draggable]');if(s){dragging=Number(s.dataset.id);e.dataTransfer.setData('text/plain',String(dragging));e.dataTransfer.effectAllowed='move';}});
document.addEventListener('dragover',e=>{const s=e.target.closest('.slot');if(s&&dragging){e.preventDefault();s.classList.add('drag-over');}});
document.addEventListener('dragleave',e=>e.target.closest('.slot')?.classList.remove('drag-over'));
document.addEventListener('drop',async e=>{const s=e.target.closest('.slot');if(s&&dragging){e.preventDefault();const from=dragging;dragging=null;try{await perform('/assignment',{slot_id:from,target_id:Number(s.dataset.id)});toast('担当者を交換・移動しました');}catch(err){s.classList.remove('drag-over');toast(err.message,true);}}});
document.addEventListener('dragend',()=>{dragging=null;$$('.drag-over').forEach(s=>s.classList.remove('drag-over'));});
// A normal swipe scrolls months. Long-press enables drag-to-slot or tap-to-destination.
let pressTimer=null,pressStart=null,touchSource=null,suppressClickUntil=0;
document.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse')return;const el=e.target.closest('.slot');if(!el||!P||P.status==='final')return;const s=P.slots.find(s=>s.id===Number(el.dataset.id));if(!s?.member_id||s.locked)return;pressStart={x:e.clientX,y:e.clientY};pressTimer=setTimeout(()=>{selected=s.id;touchSource=s.id;el.classList.add('selected');renderSelection();toast('移動先へ指を動かすか、枠をタップしてください');pressTimer=null;},550);},{passive:true});
document.addEventListener('pointermove',e=>{if(touchSource!==null){if(e.cancelable)e.preventDefault();$$('.drag-over').forEach(s=>s.classList.remove('drag-over'));document.elementFromPoint(e.clientX,e.clientY)?.closest('.slot')?.classList.add('drag-over');}else if(pressStart&&Math.hypot(e.clientX-pressStart.x,e.clientY-pressStart.y)>8){clearTimeout(pressTimer);pressTimer=null;}},{passive:false});
document.addEventListener('touchmove',e=>{if(touchSource!==null&&e.cancelable)e.preventDefault();},{passive:false});
document.addEventListener('pointerup',async e=>{clearTimeout(pressTimer);pressStart=null;if(touchSource===null)return;const from=touchSource;touchSource=null;suppressClickUntil=Date.now()+500;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.slot');$$('.drag-over').forEach(s=>s.classList.remove('drag-over'));if(target&&Number(target.dataset.id)!==from){try{await perform('/assignment',{slot_id:from,target_id:Number(target.dataset.id)});selected=null;renderCalendar();toast('担当者を交換・移動しました');}catch(err){toast(err.message,true);}}},{passive:true});
document.addEventListener('pointercancel',()=>{clearTimeout(pressTimer);pressStart=null;touchSource=null;$$('.drag-over').forEach(s=>s.classList.remove('drag-over'));},{passive:true});
window.addEventListener('hashchange',()=>render().catch(e=>toast(e.message,true)));
window.addEventListener('resize',()=>{const t=$('#month-track');if(t)t.scrollLeft=t.clientWidth*monthIndex;});
reload().catch(e=>{$('#app').innerHTML=`<div class="error-panel"><h2>読み込みに失敗しました</h2><p>${esc(e.message)}</p><p>サーバーの起動状態を確認してページを再読み込みしてください。</p></div>`;});
