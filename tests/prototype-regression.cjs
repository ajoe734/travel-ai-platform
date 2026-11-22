'use strict';
/**
 * Repeatable UX 2.1 regression checks. Run from the repository root:
 *   node tests/prototype-regression.cjs
 *
 * Executes the prototype's actual inline script using only Node standard libraries.
 * DOM elements, localStorage, and timers below are minimal test substitutes.
 * This verifies state changes and generated markup, NOT actual browser clicks,
 * visual layout, accessibility, HTML constraint validation, or browser E2E.
 * No network requests or real transactions are made.
 *
 * Eighteen existing regression cases are assertions. Two known prototype limitations
 * are reported as observations separately; future fixes need not preserve those limits.
 */
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const htmlPath=path.resolve(__dirname,'../prototypes/merchant-assistant/ux-v2.1/index.html');
const html=fs.readFileSync(htmlPath,'utf8');
const scriptBlocks=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/gi)];
if(scriptBlocks.length!==1)throw new Error('Expected one inline UX 2.1 script');
const source=scriptBlocks[0][1];
const storageKey=source.match(/const storageKey='([^']+)'/)[1];
function environment(seed){
 const elements=new Map(),events={},timers=[];
 function element(id){if(!elements.has(id))elements.set(id,{id,innerHTML:'',value:'',checked:false,disabled:false,textContent:'',classList:{toggle(){}},focus(){},click(){},setAttribute(){},remove(){},addEventListener(k,fn){this[k]=fn}});return elements.get(id)}
 const storage=new Map(seed?[[storageKey,JSON.stringify(seed)]]:[]);
 const document={getElementById:element,querySelector(){return null},querySelectorAll(){return[]},activeElement:element('initial-focus'),addEventListener(k,fn){events[k]=fn},createElement(){return {setAttribute(){},remove(){}}},body:{append(){}}};
 const window={scrollTo(){}};
 const context=vm.createContext({document,window,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},URL:{createObjectURL:()=> 'blob:local-test',revokeObjectURL(){}},setTimeout(fn,ms){timers.push({fn,ms});return timers.length},clearTimeout(){},console});
 vm.runInContext(source,context,{filename:'ux-v2.1/index.html#script',timeout:1000});
 return{context,api:window.uxPrototype,e:element,events,timers,storage,flush(ms){timers.filter(t=>t.ms===ms).forEach(t=>t.fn())},submit(id){events.submit({target:{id},preventDefault(){}})}};
}
const checks=[];
const observations=[];
function observe(name,fn){try{observations.push({name,...fn()})}catch(e){checks.push({name,status:'error',error:e.message})}}
function check(name,fn){try{checks.push({name,...fn()})}catch(e){checks.push({name,status:'error',error:e.message})}}
check('Initial render',()=>{let x=environment();return{status:x.api.getState().view==='home'&&x.e('main').innerHTML.includes('日常接單，我在處理。')?'pass':'fail',view:x.api.getState().view}});
check('Missing approval prerequisites',()=>{let x=environment();x.api.act('approve');return{status:x.api.getState().approvedRevision===null?'pass':'fail'}});
check('Happy publication simulation',()=>{let x=environment();x.api.fixtureReview();x.api.act('approve');let pending=x.api.getState();x.flush(900);let accepted=x.api.getState();x.api.act('demo-complete');let done=x.api.getState();return{status:pending.web==='pending'&&pending.partner==='pending'&&accepted.web==='live'&&accepted.partner==='review'&&done.web==='live'&&done.partner==='live'?'pass':'fail',pending:[pending.web,pending.partner],afterTimeout:[accepted.web,accepted.partner],afterSimulatedReport:[done.web,done.partner]}});
check('Auth loss blocks publication completion',()=>{let x=environment();x.api.act('scenario-auth');x.api.act('demo-complete');return{status:x.api.getState().channelProblem&&x.api.getState().partner!=='live'?'pass':'fail'}});
check('Editing invalidates active approval',()=>{let x=environment();x.api.act('scenario-auth');x.api.act('scenario-revision');return{status:x.api.getState().approvedRevision===null?'pass':'fail'}});
check('Home during 900ms pending window',()=>{let x=environment();x.api.fixtureReview();x.api.act('approve');x.api.act('home');let s=x.api.getState();return{status:s.web==='pending'&&!x.e('main').innerHTML.includes('官網已更新')?'pass':'fail',web:s.web,homeClaimsUpdated:x.e('main').innerHTML.includes('官網已更新')}});
check('Custom service description preserved on review',()=>{let x=environment();x.api.act('discuss');x.e('merchantText').value='提供咖啡拉花課，不提供茶點，每人980元，90分鐘，最多4人，週末15:00。';x.submit('merchantform');return{status:x.api.getState().phase==='material'&&x.api.getState().facts.content===x.e('merchantText').value?'pass':'fail',acceptedFields:{price:x.api.getState().facts.price,duration:x.api.getState().facts.duration,capacity:x.api.getState().facts.capacity},contentStillDemo:x.api.getState().facts.content.includes('兩款茶')}});
check('Zero capacity in natural-language intake',()=>{let x=environment();x.api.act('discuss');x.e('merchantText').value='保留原體驗。新方案每人680元，60分鐘，最多0人，平日14:00。';x.submit('merchantform');return{status:x.api.getState().phase==='discuss'&&x.api.getState().facts.capacity!==0?'pass':'fail'}});
observe('Remedy submission flag',()=>{let x=environment();x.api.act('scenario-complaint');x.api.act('approve-remedy');let s=x.api.getState();return{status:'documented_limitation',exceptionResolved:s.exceptionResolved,visibleStillAwaiting:x.e('main').innerHTML.includes('尚待正式結果')}});
observe('Refresh loses active simulation timer',()=>{let x=environment();x.api.fixtureReview();x.api.act('approve');let y=environment(x.api.getState());return{status:'documented_limitation',restoredPhase:y.api.getState().phase,restoredWeb:y.api.getState().web,restoredTimers:y.timers.length}});
check('Capacity boundaries',()=>{const results=[];for(const n of [1,8,9]){let x=environment();x.api.act('discuss');x.e('merchantText').value='服務說明，每人680元，60分鐘，最多'+n+'人，平日14:00。';x.submit('merchantform');results.push({n,accepted:x.api.getState().phase==='material'})}return{status:results[0].accepted&&results[1].accepted&&!results[2].accepted?'pass':'fail',results}});
check('Content is escaped on review',()=>{let x=environment();x.api.act('discuss');x.e('merchantText').value='咖啡課程 <img src=x onerror=alert(1)> 每人680元，60分鐘，最多4人。';x.submit('merchantform');x.api.act('sample-asset');x.events.change({target:{id:'rights',checked:true}});x.api.act('review');return{status:x.e('main').innerHTML.includes('&lt;img src=x onerror=alert(1)&gt;')&&!x.e('main').innerHTML.includes('<img src=x onerror=alert(1)>')?'pass':'fail'}});
check('Both channels needed for completion title',()=>{let x=environment();vm.runInContext("s.web='pending';s.partner='live';s.phase='result';route('result');",x.context);return{status:!x.e('main').innerHTML.includes('兩個入口都已核對完成。')?'pass':'fail'}});

function channelRows(x){let h=x.e('main').innerHTML;return [...h.matchAll(/<strong>(官網|合作旅宿)<\/strong><p>(.*?)<\/p><\/div><span class="badge[^"]*">(.*?)<\/span>/g)].map(m=>({channel:m[1],detail:m[2],label:m[3]}))}
function inState(web,partner,problem=false){let x=environment();x.api.fixtureReview();vm.runInContext('s.web='+JSON.stringify(web)+';s.partner='+JSON.stringify(partner)+';s.channelProblem='+problem+';s.approvedRevision=s.revision;s.phase="result";route("result");',x.context);return x}
check('Pending/pending has no premature review claim',()=>{let x=inState('pending','pending'),rows=channelRows(x);return{status:rows.length===2&&rows.every(r=>r.label==='核對中'&&!r.detail.includes('審核中'))?'pass':'fail',rows}});
check('Web live with partner pending',()=>{let x=inState('live','pending'),rows=channelRows(x);x.api.act('home');return{status:rows[0]?.label==='已生效'&&rows[1]?.label==='核對中'&&!x.e('main').innerHTML.includes('旅宿端等待審核')?'pass':'fail',rows}});
check('Partner live with web pending',()=>{let x=inState('pending','live'),rows=channelRows(x);return{status:rows[0]?.label==='核對中'&&rows[1]?.label==='已生效'&&rows[1]?.detail.includes('已讀回核准版本')&&!x.e('main').innerHTML.includes('兩個入口都已核對完成。')?'pass':'fail',rows}});
check('Known review status on each channel',()=>{let x=inState('review','live'),a=channelRows(x),y=inState('live','review'),b=channelRows(y);return{status:a[0]?.label==='待外部審核'&&a[1]?.label==='已生效'&&b[0]?.label==='已生效'&&b[1]?.label==='待外部審核'?'pass':'fail',webReview:a,partnerReview:b}});
check('Not started is not sent or under review',()=>{let x=inState('not_started','not_started'),rows=channelRows(x);return{status:rows.length===2&&rows.every(r=>r.label==='尚未開始'&&r.detail==='尚未建立發布工作。')?'pass':'fail',rows}});
check('Auth loss overrides partner status',()=>{let x=inState('live','live',true),rows=channelRows(x);return{status:rows[0]?.label==='已生效'&&rows[1]?.label==='需要授權'&&!x.e('main').innerHTML.includes('兩個入口都已核對完成。')?'pass':'fail',rows}});
check('Activity and evidence preserve pending distinction',()=>{let x=inState('live','pending');x.api.act('activity');let activity=x.e('modalroot').innerHTML;x.api.act('publication-proof');let proof=x.e('modalroot').innerHTML;return{status:activity.includes('合作旅宿 尚待核對')&&!activity.includes('合作旅宿 審核中')&&proof.includes('結果待核對，尚無生效證據')?'pass':'fail'}});

console.log('UX 2.1 regression: Node VM with minimal DOM substitutes; NOT browser E2E.');
for(const result of checks){
 console.log('['+result.status.toUpperCase()+'] '+result.name);
 if(result.status!=='pass')console.log(JSON.stringify(result,null,2));
}
const failures=checks.filter(x=>x.status!=='pass');
console.log(JSON.stringify({checks:checks.length,passed:checks.length-failures.length,failed:failures.length,observations},null,2));
if(failures.length)process.exitCode=1;
