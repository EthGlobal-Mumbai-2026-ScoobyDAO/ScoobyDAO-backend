const fs=require('fs'), vm=require('vm');
const h=fs.readFileSync(process.argv[2],'utf8');
const names=['data','manifest','controls','selection','tldr','reasoning','irc','audit','unit'], values={};
for(const id of names) values[id]=JSON.parse(h.match(new RegExp('<script id="'+id+'" type="application/json">([\\s\\S]*?)</script>'))[1]);
const code=h.match(/<script>\s*('use strict';[\s\S]*?)<\/script>/)[1], all=[];
class Node {
  constructor(tag){this.tag=tag;this.tagName=tag.toUpperCase();this.children=[];this.style={};this.textContent='';all.push(this)}
  append(...nodes){this.children.push(...nodes);nodes.forEach(n=>n.parentElement=this)}
  setAttribute(k,v){this[k]=v} getAttribute(k){return this[k]} addEventListener(k,f){this.handler=f} scrollIntoView(){} querySelector(){return{focus(){}}}
}
const app=new Node('main'), document={createElement:t=>new Node(t),createElementNS:(ns,t)=>new Node(t),getElementById:id=>id==='app'?app:Object.hasOwn(values,id)?{textContent:JSON.stringify(values[id])}:all.find(n=>n.id===id)};
vm.runInNewContext(code,{document,JSON,Map,Object,Array,String,Number,Math,Date,encodeURIComponent,decodeURIComponent,location:{hash:''},requestAnimationFrame:f=>f()});
const text=all.map(n=>n.textContent).join('\n'), reasoning=values.reasoning;
if(reasoning?.profile==='scooby.reasoning/2'){
  const rec=reasoning.reasoning.conclusion.recommendation;
  for(const expected of ['Proposed action (pending review)',rec.action,rec.rationale.text,rec.counterevidence[0].text,rec.reversal_conditions[0]]) if(!text.includes(expected))throw Error('missing '+expected);
}
if(all.filter(n=>n.className==='card pillar').length!==5)throw Error('expected five pillars');
if(all.filter(n=>n.className==='tldr').length!==5)throw Error('expected five summary blocks');
for(const a of all.filter(n=>n.className==='tldr-ref')) if(!document.getElementById(a.href.slice(1)))throw Error('unresolved anchor '+a.href);
if(all.some(n=>n.tag==='script'))throw Error('unsafe text executed');
if(process.argv.includes('--partial-only')){
  if(all.filter(n=>n.className==='availability'&&n.textContent==='Partial coverage · mapped data available').length!==5)throw Error('partial status hidden');
  if(!text.includes('Source-linked summary')||text.includes('IRC TL;DR'))throw Error('sidecar heading does not match data');
  if(!text.includes(values.data.assessment.summary))throw Error('assessment summary omitted');
  if(all.some(n=>n.className==='chart-block'||n.className==='var-chart'))throw Error('chart without supported data');
}
if(process.argv.includes('--captured-partial')){
  const pillars=values.data.pillars;
  for(const [id,part] of Object.entries(pillars)){
    const card=all.find(n=>n.id==='pillar-'+id);
    if(!card)throw Error('missing pillar '+id);
    const expected=part.status==='partial'?'Partial coverage · mapped data available':part.status==='unavailable'?'Data unavailable':null;
    if(expected&&!card.children.some(n=>n.children?.some(c=>c.className==='availability'&&c.textContent===expected)))throw Error('missing status '+id);
  }
  if(!text.includes(values.data.assessment.summary))throw Error('assessment summary omitted');
  if(Object.values(pillars).every(p=>p.series.length===0)&&all.some(n=>n.className==='chart-block'||n.className==='var-chart'))throw Error('chart without supported data');
  for(const e of values.data.evidence)if(!document.getElementById('evidence-'+encodeURIComponent(e.id)))throw Error('missing evidence '+e.id);
}
console.log('PASS DOM, provenance anchors, coverage and safe text');
