// node youtube-chat.test.mjs -- no network, no real mp, nothing posted.
import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dir = mkdtempSync(join(tmpdir(), 'yt-chat-test-'));
// A stub mp that records its argv, one JSON line per call.
const stub = join(dir, 'mp');
writeFileSync(stub, `#!/usr/bin/env node\nrequire('fs').appendFileSync(${JSON.stringify(join(dir, 'argv'))}, JSON.stringify(process.argv.slice(2)) + '\\n')\n`);
chmodSync(stub, 0o755);
Object.assign(process.env, { YOUTUBE_CHAT_STATE_DIR: dir, MP_BIN: stub });   // read at import
const { TARGET, chatLine, deliver, envelope, parts } = await import('./youtube-chat.mjs');

try {
  // In: YouTube chat messages, not Twitch or blanks, reach MyPlow as `mp send <MP> <envelope>`.
  assert.match(TARGET, /\/main:MP$/);
  const frame = (sid, text) => ({ action: 'event', payload: { eventSourceId: sid, eventIdentifier: 'e1',
    eventPayload: { author: { displayName: 'Ana' }, text } } });
  assert.deepEqual(chatLine(frame(13, 'oi')), { id: 'e1', author: 'Ana', text: 'oi' });
  assert.equal(chatLine(frame(2, 'twitch')), null);
  assert.equal(chatLine(frame(13, '  ')), null);
  assert.equal(chatLine({ action: 'heartbeat' }), null);
  assert.ok(envelope('Ana', 'oi').startsWith('[youtube-chat] from Ana: oi\n'));
  assert.match(envelope('Ana', 'oi'), /youtube-chat\.mjs reply "your reply"/);
  const quiet = console.log; console.log = () => {};
  await deliver({ author: 'Ana', text: 'build me a todo app' });
  console.log = quiet;
  assert.deepEqual(readFileSync(join(dir, 'argv'), 'utf8').trim().split('\n').map((l) => JSON.parse(l)),
    [['send', TARGET, envelope('Ana', 'build me a todo app')]]);

  // Out: long replies become several chat messages, each <=200 (YouTube's limit), nothing lost, in order.
  const long = Array.from({ length: 120 }, (_, i) => `word${i}`).join(' ') + '\nnext line ' + 'z'.repeat(450);
  const ps = parts(long);
  assert.ok(ps.length > 3 && ps.every((p) => p && p.length <= 200 && !/\n/.test(p)));
  assert.equal(ps.join(' ').replace(/\s+/g, ''), long.replace(/\s+/g, ''), 'nothing lost or reordered');
  assert.deepEqual(parts('see https://github.com/x/y'), ['see https://github.com/x/y']);
  assert.deepEqual(parts('a'.repeat(200)), ['a'.repeat(200)]);
  assert.deepEqual(parts('b'.repeat(201)), ['b'.repeat(200), 'b']);
  assert.deepEqual(parts('  '), []);

  console.log('youtube-chat: all checks pass');
} finally {
  rmSync(dir, { recursive: true, force: true });
}
