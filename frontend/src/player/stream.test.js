import test from 'node:test';
import assert from 'node:assert/strict';
import { readSearchStream } from './stream.js';
test('progressive search retains split UTF-8 characters and multiple events', async () => {
  const bytes = new TextEncoder().encode('event: results\ndata: {"results":[{"title":"夜曲"}],"pending":["youtube"]}\n\nevent: results\ndata: {"results":[{"title":"夜曲","variants":[1,2]}]}\n\nevent: done\ndata: {}\n\n');
  const stream = new ReadableStream({ start(controller) { for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3)); controller.close(); } });
  const updates = [];
  await readSearchStream(new Response(stream), (value) => updates.push(value));
  assert.equal(updates.length, 2);
  assert.equal(updates[0].results[0].title, '夜曲');
  assert.deepEqual(updates[1].results[0].variants, [1, 2]);
});
