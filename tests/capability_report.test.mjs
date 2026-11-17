import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('../Resources/Web/capability-report.html',import.meta.url),'utf8');
const ctx=vm.createContext({TextEncoder});
vm.runInContext("const LABELS=['supported','unsupported','unknown'];"+html.split('// CAPABILITY-CORE-START')[1].split('// CAPABILITY-CORE-END')[0]+';globalThis.request=capabilityRequest;globalThis.compare=compare;globalThis.batches=capabilityBatches;globalThis.applyBatch=applyCapabilityBatch;globalThis.effectiveBatchSize=effectiveBatchSize;',ctx);
test('judge receives full model catalog and definitions but no expected labels or secret fields',()=>{
 const catalog={capabilities:[{id:'box',name:'Box',definition:'Image localization'}],models:[{id:'a',name:'A',model:'future',evidence:{protocol:'native'},expected:{box:{value:'supported'}},api_key:'secret'},{id:'b',name:'B',evidence:{}}]};
 const req=ctx.request(catalog,catalog.models[0]);
 const input=JSON.parse(req.contexts[0]);assert.equal(input.models.length,2);assert.equal(input.target_id,'a');assert.equal(input.models[0].expected,undefined);assert.equal(input.models[0].api_key,undefined);assert.equal(req.schema.box.type,'choice');assert.deepEqual(Array.from(req.schema.box.choices),['yes','no','unknown']);assert.match(req.schema.box.instructions,/allow the \"box\" question type/);assert.match(req.schema.box.instructions,/answer unknown/);
});
test('unknown is valid and matches unknown expectations; only yes/no contradict',()=>{
 assert.equal(ctx.compare('supported',true),'Match');assert.equal(ctx.compare('unsupported',false),'Match');assert.equal(ctx.compare('supported',false),'Disagreement');assert.equal(ctx.compare('unknown',false),'Unknown');assert.equal(ctx.compare('supported','supported'),'Match');assert.equal(ctx.compare('supported','unsupported'),'Disagreement');assert.equal(ctx.compare('unknown','unknown'),'Match');assert.equal(ctx.compare('unknown','other'),'Match');assert.equal(ctx.compare('supported','yes'),'Match');assert.equal(ctx.compare('unsupported','no'),'Match');assert.equal(ctx.compare('unknown','supported'),'Unknown');assert.equal(ctx.compare('supported',undefined),'Error');
});
test('report scripts parse',()=>{for(const s of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(s[1])});

test('question batches share evidence, stay bounded and retain unique model/capability mappings',()=>{
 const catalog={capabilities:[{id:'choice',name:'Choice',definition:'Categorical'},{id:'box',name:'Box',definition:'Image location'}],models:[{id:'a',name:'A',model:'A',evidence:{image_adapter:'unsupported'},expected:{box:'private'}},{id:'b',name:'B',model:'B',evidence:{image_adapter:'systemone'}}]};
 const batches=ctx.batches(catalog,catalog.models,3);
 assert.equal(batches.length,2);assert.equal(batches[0].mapping.length,3);assert.equal(batches[1].mapping.length,1);
 const ids=batches.flatMap(b=>Object.keys(b.request.schema));assert.equal(new Set(ids).size,4);assert.equal(ids.includes('m1_box'),true);
 for(const batch of batches){const evidence=JSON.parse(batch.request.contexts[0]);assert.equal(evidence.models.length,2);assert.equal(evidence.target_id,undefined);assert.equal(evidence.models[0].expected,undefined)}
 const singles=ctx.batches(catalog,catalog.models,1),maxBytes=Math.max(...singles.map(b=>new TextEncoder().encode(JSON.stringify(b.request)).length));
 const bounded=ctx.batches(catalog,catalog.models,64,maxBytes);assert.equal(bounded.length,4);
 assert.throws(()=>ctx.batches(catalog,catalog.models,64,1),/exceeds/);
});
test('partial batch mapping preserves false answers and exposes only missing fields as errors',()=>{
 const assessments=[{response:{results:[{decision:{},fields:{}}]}},{response:{results:[{decision:{},fields:{}}]}}];
 const batch={mapping:[{id:'m0_box',modelIndex:0,capability:'box'},{id:'m1_box',modelIndex:1,capability:'box'}],response:{results:[{decision:{m0_box:false},fields:{m0_box:{value:false,noul:.02}}}]},error:'Rate limited'};
 ctx.applyBatch(assessments,batch);assert.equal(assessments[0].response.results[0].decision.box,false);assert.equal(assessments[0].response.results[0].fields.box.noul,.02);assert.equal(assessments[1].response.results[0].decision.box,undefined);assert.equal(assessments[1].response.results[0].fields.box.error,'Rate limited');
});

test('batch preference can reach 512 while known provider limits remain separate',()=>{
 assert.equal(ctx.effectiveBatchSize(512,{}),512);assert.equal(ctx.effectiveBatchSize(512,{max_questions_per_request:64}),64);assert.equal(ctx.effectiveBatchSize(32,{max_questions_per_request:64}),32);
});
