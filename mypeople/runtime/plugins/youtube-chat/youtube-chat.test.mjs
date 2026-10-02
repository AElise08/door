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
const LIST = join(dir, 'allow.txt');
Object.assign(process.env, { YOUTUBE_CHAT_STATE_DIR: dir, MP_BIN: stub, YOUTUBE_CHAT_ALLOWLIST: LIST });   // read at import
const { TARGET, admitted, chatLine, deliver, envelope, ownEcho, parseAllowlist, parts } = await import('./youtube-chat.mjs');
// Fake youtube.com: @ana is a real channel, anything else 404s. Counts lookups.
let lookups = 0;
globalThis.fetch = async (url) => { lookups++; return url.endsWith('/@ana')
  ? new Response('<meta property="og:title" content="Ana Silva">..."externalId":"UCaaaaaaaaaaaaaaaaaaaaaa"...')
  : new Response('', { status: 404 }); };
const ANA = 'UCaaaaaaaaaaaaaaaaaaaaaa', BOB = 'UCbbbbbbbbbbbbbbbbbbbbbb';

try {
  // In: YouTube chat messages, not Twitch or blanks, reach MyPlow as `mp send <MP> <envelope>`.
  assert.match(TARGET, /\/main:MP$/);
  const frame = (sid, text) => ({ action: 'event', payload: { eventSourceId: sid, eventIdentifier: 'e1',
    eventPayload: { author: { displayName: 'Ana' }, text } } });
  assert.deepEqual(chatLine(frame(13, 'oi')), { id: 'e1', author: 'Ana', channel: '', text: 'oi' });
  const withId = frame(13, 'oi'); withId.payload.eventPayload.author.id = ANA;
  assert.equal(chatLine(withId).channel, ANA);
  assert.equal(chatLine(frame(2, 'twitch')), null);
  assert.equal(chatLine(frame(13, '  ')), null);
  assert.equal(chatLine({ action: 'heartbeat' }), null);
  assert.ok(envelope('Ana', 'oi').startsWith('[youtube-chat] from Ana: oi\n'));
  assert.match(envelope('Ana', 'oi'), /youtube-chat\.mjs reply "your reply"/);
  // Allowlist: missing file = nobody (and it is created for him to edit).
  assert.equal(await admitted(ANA), false);
  assert.match(readFileSync(LIST, 'utf8'), /@handle or channel id/);
  assert.deepEqual(parseAllowlist('# c\n@ana\nUCbbbbbbbbbbbbbbbbbbbbbb  # bob\nAna Silva\n\n'),
    { ids: [BOB], handles: ['@ana'], plain: ['Ana Silva'] });
  writeFileSync(LIST, '@ana\nAna Silva\n@nobody-here\n');
  assert.equal(await admitted(ANA), true, '@handle binds to its channel id');
  assert.equal(await admitted(BOB), false);
  assert.equal(await admitted(''), false, 'no channel id = not admitted');
  const bound = readFileSync(join(dir, 'allow.bound.txt'), 'utf8');
  assert.match(bound, /@ana -> UCaaaaaaaaaaaaaaaaaaaaaa \(Ana Silva\)/);
  assert.match(bound, /Ana Silva -> NOT USED/);
  assert.match(bound, /@nobody-here -> NOT FOUND/);
  const n = lookups; await admitted(ANA); assert.equal(lookups, n, 'unchanged list is not looked up again');
  writeFileSync(LIST, BOB + '\n');   // edited mid-stream, no restart
  assert.equal(await admitted(BOB), true);
  assert.equal(await admitted(ANA), false, 'removed person is out at once');

  // Only listed people are delivered; the rest are dropped without a word.
  const quiet = console.log; console.log = () => {};
  await deliver({ author: 'Ana', channel: ANA, text: 'let me in' });
  await deliver({ author: 'Bob', channel: BOB, text: 'build me a todo app' });
  const logged = []; console.log = (m) => logged.push(m);
  await deliver({ author: 'Bob', channel: '', text: 'renamed stranger' });
  await deliver({ author: 'Cy', channel: 'UCcccccccccccccccccccccc', text: 'not listed' });
  await deliver({ author: 'Dee', channel: 'not-a-channel', text: 'second missing id' });
  console.log = quiet;
  assert.match(logged[0], /DROPPED Bob: Restream sent no YouTube channel id .* cannot let ANYONE in/);
  assert.match(logged[1], /dropped Cy \(UCcccccccccccccccccccccc\): not on the allowlist/);
  assert.match(logged[2], /DROPPED Dee/, 'every missing id is still logged');
  // ...and the Boss hears it exactly once per run, with no viewer text.
  const sent = readFileSync(join(dir, 'argv'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  const toBoss = sent.filter((c) => c[1].endsWith(':Boss'));
  assert.equal(toBoss.length, 1);
  assert.match(toBoss[0][2], /^\[youtube-chat\] cannot deliver: .*no YouTube channel id/);
  assert.ok(!/Bob|renamed stranger|Dee/.test(toBoss[0][2]), 'no viewer name or text reaches the Boss');
  assert.deepEqual(sent.filter((c) => c[1] === TARGET), [['send', TARGET, envelope('Bob', 'build me a todo app')]]);

  // MyPlow's own reply comes back as the owner's message: skipped, not delivered; after 10 min, not.
  writeFileSync(join(dir, 'state.json'), JSON.stringify({ posted: [{ text: 'sure, on it', at: Date.now() }, { text: 'old', at: Date.now() - 700000 }] }));
  console.log = () => {};
  await deliver({ author: 'Bob', channel: BOB, text: 'sure,  on it' });
  console.log = quiet;
  assert.equal(readFileSync(join(dir, 'argv'), 'utf8').trim().split('\n').filter((l) => JSON.parse(l)[1] === TARGET).length, 1, 'echo not delivered');
  assert.equal(ownEcho('old'), false);
  assert.equal(ownEcho('sure, on it'), true);

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
