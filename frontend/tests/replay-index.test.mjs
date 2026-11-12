import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const source = await readFile(new URL('../src/lib/replayIndex.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2021}}).outputText;
const {indexReplayPlaces,indexedTokenCounts,indexedCasesAtPlace} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
test('indexed replay preserves simultaneous moves, open intervals, and repeated tokens per case', () => {
 const rows = Array.from({length:12000},(_,i)=>({case_id:String(i%251),place:`p${i%31}`,zone:'Work',produced:(i*97)%1000,consumed:i%13===0?null:(i*97)%1000+(i%53)}));
 const index=indexReplayPlaces(rows);
 for(const time of [-1,0,53,500,999,1100]) {
  const expected={};for(const r of rows)if(r.produced<=time&&(r.consumed===null||r.consumed>time))expected[r.place]=(expected[r.place]??0)+1;
  assert.deepEqual(indexedTokenCounts(index,time),expected);
  for(const place of ['p0','p15','absent']) {
   const cases=[...new Set(rows.filter(r=>r.place===place&&r.produced<=time&&(r.consumed===null||r.consumed>time)).map(r=>r.case_id))].sort((a,b)=>Number(a)-Number(b)||a.localeCompare(b));
   assert.deepEqual(indexedCasesAtPlace(index,place,time),cases);
  }
 }
 assert.deepEqual(indexedCasesAtPlace(index,null,0),[]);
});
