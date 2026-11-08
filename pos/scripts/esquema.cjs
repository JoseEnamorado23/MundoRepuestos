const o=require('../openapi.json');
const S=o.components.schemas;
function t(s){ if(!s)return'?'; if(s.$ref)return s.$ref.split('/').pop(); if(s.anyOf)return s.anyOf.map(t).join('|'); if(s.type==='array')return t(s.items)+'[]'; if(s.enum)return s.enum.map(e=>JSON.stringify(e)).join('|'); return s.type+(s.format?':'+s.format:'')}
function show(n){const s=S[n]; if(!s){console.log(n,'NO');return} console.log('#',n); for(const [k,v] of Object.entries(s.properties||{})) console.log('  ',k+((s.required||[]).includes(k)?'':'?'),t(v))}
const argv=process.argv.slice(2);
for(const a of argv){ if(a.startsWith('/')){const p=Object.entries(o.paths).find(([k])=>k==='/api/v1'+a); for(const [m,d] of Object.entries(p[1])){console.log('==',m.toUpperCase(),a, 'params:',(d.parameters||[]).map(x=>x.name+(x.required?'*':'')+':'+t(x.schema)).join(', ')); const rb=d.requestBody?.content?.['application/json']?.schema; if(rb)console.log(' body',t(rb)); const r=d.responses['200']||d.responses['201']; console.log(' resp',t(r?.content?.['application/json']?.schema))}} else show(a)}
