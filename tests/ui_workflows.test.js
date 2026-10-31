import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// Run the shipped state/transport code with rendering stubbed; no DOM dependency is needed.
const source = readFileSync(new URL('../src/whatsent/ui/app.js', import.meta.url), 'utf8');
const boundary = source.indexOf('  // ---------- chrome (title bar, progress) ----------');
assert.ok(boundary > 0);

function page(fetch) {
  const streams = [];
  const dialogs = [];
  const context = vm.createContext({
    fetch, navigator: { language: 'en' }, localStorage: { getItem: () => null },
    document: { querySelector: () => ({ content: 'test-token' }) },
    setTimeout, clearTimeout,
    EventSource: class {
      static OPEN = 1;
      constructor(url) { this.url = url; streams.push(this); }
      close() { this.closed = true; }
    },
  });
  context.dialogs = dialogs;
  vm.runInContext(source.slice(0, boundary) + `
    function go(screen) { S.screen = screen; }
    function refresh() {}
    function sheet(value) { dialogs.push(value); }
    function closeSheet() { S.sheet = null; }
    globalThis.app = { S, api, startJob, leavePreparation, finishJob, connect, disconnect, onEvent };
  })();`, context);
  return { ...context.app, streams, dialogs };
}

const ok = (value = {}) => ({ ok: true, json: async () => value });

test('job controls carry the originating job, including an explicit cancellation target', async () => {
  const sent = [];
  const p = page(async (path, options) => { sent.push(JSON.parse(options.body)); return ok(); });
  p.S.job = { id: 'current' };
  await p.api('/api/stop', {});
  await p.api('/api/stop', { job: 'cancelled-start' });
  assert.deepEqual(sent, [{ job: 'current' }, { job: 'cancelled-start' }]);
});

test('back before start returns cancels that job without reconnecting it', async () => {
  let respond;
  const stopped = [];
  const p = page((path, options) => {
    if (path === '/api/start') return new Promise(resolve => { respond = resolve; });
    stopped.push(JSON.parse(options.body).job);
    return Promise.resolve(ok());
  });
  const starting = p.startJob({ tool: 'fake' });
  p.leavePreparation();
  respond(ok({ job: 'late-start' }));
  await starting;
  assert.deepEqual(stopped, ['late-start']);
  assert.equal(p.S.screen, 'pick');
  assert.equal(p.streams.length, 0);
});

test('a delayed start response cannot overwrite a newer selection', async () => {
  const pending = [];
  const stopped = [];
  const p = page((path, options) => {
    if (path === '/api/start') return new Promise(resolve => pending.push(resolve));
    stopped.push(JSON.parse(options.body).job);
    return Promise.resolve(ok());
  });
  const first = p.startJob({ tool: 'old' });
  const second = p.startJob({ tool: 'new' });
  pending[1](ok({ job: 'new-id' }));
  await second;
  pending[0](ok({ job: 'old-id' }));
  await first;
  assert.equal(p.S.job.id, 'new-id');
  assert.deepEqual(stopped, ['old-id']);
  p.disconnect();
});

test('failed stop can be retried instead of leaving the button stuck', async () => {
  let calls = 0;
  const p = page(async () => {
    if (++calls === 1) throw new Error('temporary network failure');
    return ok();
  });
  p.S.job = { id: 'current' };
  await p.finishJob();
  assert.equal(p.S.finishing, false);
  assert.equal(p.dialogs.length, 1);
  await p.finishJob();
  assert.equal(calls, 2);
  assert.equal(p.S.finishing, true);
});

test('late events from a closed stream cannot change the new run', () => {
  const p = page(async () => ok());
  p.connect('old');
  const old = p.streams[0];
  p.connect('new');
  old.onmessage({ data: JSON.stringify({ kind: 'done', report: { agent: 'old' } }) });
  old.onerror();
  assert.equal(old.closed, true);
  assert.equal(p.S.report, null);
  assert.equal(p.dialogs.length, 0);
  p.disconnect();
});

for (const kind of ['done', 'cancelled', 'error']) {
  test(`${kind} closes the event connection`, () => {
    const p = page(async () => ok());
    p.connect('current');
    p.onEvent({ kind, report: {}, code: 'internal', message: 'test' });
    assert.equal(p.streams[0].closed, true);
  });
}
