import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyQueue, queueReducer as reduce, currentQueueItem, peekNext, queueSession } from './queue.js';

const start = () => reduce(emptyQueue(), { type: 'replace', items: ['A', 'B', 'C', 'D'].map((title) => ({ title, entryId: title })), index: 0 });
test('random visits every song once; previous follows actual listening history', () => {
  let state = reduce(start(), { type: 'shuffle' });
  const order = [state.currentId];
  while (peekNext(state)) { state = reduce(state, { type: 'next' }); order.push(state.currentId); }
  assert.equal(new Set(order).size, 4);
  assert.equal(order.length, 4);
  state = reduce(state, { type: 'previous' });
  assert.equal(state.currentId, order[2]);
  state = reduce(state, { type: 'next' });
  assert.equal(state.currentId, order[3]);
});
test('single repeat changes natural end only; list repeat wraps', () => {
  let state = reduce(start(), { type: 'repeat', value: 'one' });
  assert.equal(peekNext(state, true), 'A');
  assert.equal(peekNext(state), 'B');
  state = reduce(state, { type: 'select', id: 'D' });
  state = reduce(state, { type: 'repeat', value: 'all' });
  assert.equal(peekNext(state), 'A');
});
test('reordering and removing other entries never changes the playing entry', () => {
  let state = reduce(start(), { type: 'move', id: 'A', beforeId: 'C' });
  assert.equal(state.currentId, 'A');
  assert.deepEqual(state.items.map((i) => i.title), ['B', 'C', 'A', 'D']);
  state = reduce(state, { type: 'remove', id: 'B' });
  assert.equal(state.currentId, 'A');
  state = reduce(state, { type: 'remove', id: 'A' });
  assert.equal(state.currentId, 'D');
});
test('next insertion overrides shuffle order; identical songs have independent entry IDs', () => {
  let state = reduce(start(), { type: 'shuffle' });
  state = reduce(state, { type: 'insert', item: { title: 'A' }, next: true });
  const id = peekNext(state);
  assert.notEqual(id, 'A');
  state = reduce(state, { type: 'next' });
  assert.equal(currentQueueItem(state).title, 'A');
  assert.equal(state.items.length, 5);
});
test('session round trip preserves cursor, mode, upcoming random order, and history', () => {
  let state = reduce(start(), { type: 'shuffle' });
  state = reduce(state, { type: 'next' });
  const restored = reduce(emptyQueue(), { type: 'restore', session: queueSession(state, 35, 'rock') });
  assert.deepEqual(restored, state);
});
test('empty queue and removed last entry have no phantom next song', () => {
  let state = reduce(emptyQueue(), { type: 'replace', items: [{ title: 'only', entryId: 'only' }] });
  state = reduce(state, { type: 'remove', id: 'only' });
  assert.equal(peekNext(state), null);
  assert.equal(currentQueueItem(state), null);
});
