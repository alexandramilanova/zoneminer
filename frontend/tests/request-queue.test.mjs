import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/lib/requestQueue.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { requestQueue } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('page bursts stay within admission capacity and complete in FIFO order', async () => {
  const queue = requestQueue(3), gates = [], started = [];
  const tasks = Array.from({ length: 9 }, (_, i) => queue(async () => {
    started.push(i);
    await new Promise(resolve => gates.push(resolve));
    return i;
  }));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(started, [0, 1, 2]);
  for (let i = 0; i < 9; i++) {
    gates[i]();
    await new Promise(resolve => setImmediate(resolve));
    assert.ok(started.length <= i + 4);
  }
  assert.deepEqual(await Promise.all(tasks), [0, 1, 2, 3, 4, 5, 6, 7, 8]);
});

test('cancelled queued requests never run; failures release capacity', async () => {
  const queue = requestQueue(1), controller = new AbortController();
  let release, called = 0;
  const first = queue(() => new Promise(resolve => { release = resolve; }));
  await new Promise(resolve => setImmediate(resolve));
  const aborted = queue(async () => { called++; }, controller.signal);
  const rejected = assert.rejects(aborted, { name: 'AbortError' });
  controller.abort();
  await rejected;
  release(); await first;
  await assert.rejects(queue(async () => { throw new Error('failed'); }), /failed/);
  assert.equal(await queue(async () => 42), 42);
  assert.equal(called, 0);
});
