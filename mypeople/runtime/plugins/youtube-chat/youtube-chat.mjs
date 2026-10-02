#!/usr/bin/env node
/*
YouTube chat plugin: a bridge between the owner's YouTube live chat and MyPlow (MP), the same
shape as plow-chat for iMessage. Chat messages go in to MP; MP's replies go back out to the chat.

In: Restream's chat websocket (the owner's Restream already relays his YouTube stream), so reading
needs no Google login. Each YouTube chat message reaches MP through `mp send` as

    [youtube-chat] from <author>: <text>
    (... To answer, run: node youtube-chat.mjs reply "your reply" ...)

Out: `reply "text"` posts into the chat of the live video the bridge is reading (videos.list ->
activeLiveChatId) through the YouTube Data API liveChatMessages.insert. It needs a Google token
with scope https://www.googleapis.com/auth/youtube.force-ssl at ~/.config/yt-livechat/tokens.json:
one Allow click on the posting account (~/.mpsay/yt_auth.py). YouTube takes at most 200
characters per chat message, so a longer reply goes out as several messages, in order. Each
message costs ~50 of the 10,000 daily quota units.

Node, not Python like the other plugins: Python's stdlib has no websocket client and Node's does.

Config (env, or the file MYPEOPLE_CONFIG_PATH names, default ~/.config/mypeople/queue.env):

    YOUTUBE_CHAT=1                     # supervise.sh keeps `serve` running

    youtube-chat.mjs serve             read and deliver forever
    youtube-chat.mjs reply "text"      MP's reply, into the live chat
    youtube-chat.mjs status            target and current video
*/
import { execFile } from 'node:child_process';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HOME = homedir();
const INSTALL = process.env.INSTALL_DIR || process.env.MYPEOPLE_HOME || join(HOME, '.local/share/mypeople');
const STATE_DIR = process.env.YOUTUBE_CHAT_STATE_DIR || join(INSTALL, 'state/youtube-chat');
const STATE = join(STATE_DIR, 'state.json');   // {"video": id}
const RESTREAM = join(HOME, '.config/restream-bridge');   // config.json (client) + tokens.json
const GOOGLE = join(HOME, '.config/yt-livechat');         // client_secret.json + tokens.json
const MP_BIN = process.env.MP_BIN || join(INSTALL, 'bin/mp');
export const TARGET = `${process.env.HOST_ID || hostname().split('.')[0]}/main:MP`;
const SELF = resolve(fileURLToPath(import.meta.url));
const YOUTUBE = 13;   // Restream eventSourceId; 2 is Twitch

const log = (m) => console.log(`${new Date().toISOString()} [youtube-chat] ${m}`);
const readJson = (p, d) => { try { return JSON.parse(readFileSync(p, 'utf8')); } catch { return d; } };

function writeJson(p, obj) {
  mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(p + '.tmp', JSON.stringify(obj), { mode: 0o600 });
  renameSync(p + '.tmp', p);
}

// --- In: YouTube chat -> MP ---

export function envelope(author, text) {
  return `[youtube-chat] from ${author}: ${text}\n`
    + `(This is the owner's YouTube live chat. To answer, run: node ${SELF} reply "your reply" `
    + `-- it posts into the live chat.)`;
}

// One YouTube chat message out of a Restream websocket frame, or null.
export function chatLine(frame) {
  const p = frame?.action === 'event' ? frame.payload : null;
  if (p?.eventSourceId !== YOUTUBE) return null;
  const ep = p.eventPayload || {};
  const text = String(ep.text ?? '').trim();
  return text ? { id: p.eventIdentifier, author: ep.author?.displayName || 'unknown', text } : null;
}

let chain = Promise.resolve();   // one mp send at a time, in arrival order
export function deliver(line) {
  const msg = envelope(line.author, line.text);
  return chain = chain.then(() => new Promise((ok) => execFile(MP_BIN, ['send', TARGET, msg], { timeout: 30000 },
    (err, _out, stderr) => { log(err ? `mp send failed: ${String(stderr || err.message).slice(0, 200)}` : 'delivered to MP'); ok(); })));
}

let tokens = null;
async function restreamToken() {
  tokens ??= readJson(join(RESTREAM, 'tokens.json'), {});
  const now = Math.floor(Date.now() / 1000);
  if (tokens.access_token && now < (tokens.obtained_at || 0) + (tokens.expires_in || 3600) - 300) return tokens.access_token;
  const c = readJson(join(RESTREAM, 'config.json'), {});
  const res = await fetch('https://api.restream.io/oauth/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded',
      Authorization: 'Basic ' + Buffer.from(`${c.clientId}:${c.clientSecret}`).toString('base64') },
    body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: tokens.refresh_token }),
  });
  if (!res.ok) throw new Error(`Restream token refresh ${res.status}`);
  tokens = { ...tokens, ...(await res.json()), obtained_at: now };
  writeFileSync(join(RESTREAM, 'tokens.json'), JSON.stringify(tokens, null, 2), { mode: 0o600 });
  return tokens.access_token;
}

async function serve() {
  log(`up, delivering to ${TARGET}`);
  const seen = new Set();
  let backoff = 1000;
  const connect = async () => {
    let ws;
    try {
      ws = new WebSocket(`wss://chat.api.restream.io/ws?accessToken=${encodeURIComponent(await restreamToken())}`);
    } catch (e) {
      log(`connect failed: ${e.message}`);
      return setTimeout(connect, backoff = Math.min(backoff * 2, 60000));
    }
    ws.addEventListener('open', () => { backoff = 1000; log('websocket open'); });
    ws.addEventListener('message', (evt) => {
      let f; try { f = JSON.parse(evt.data); } catch { return; }
      if (f.action === 'connection_info' && f.payload?.eventSourceId === YOUTUBE && f.payload.target?.event?.id) {
        writeJson(STATE, { ...readJson(STATE, {}), video: f.payload.target.event.id });
      }
      const line = chatLine(f);
      if (!line || (line.id && seen.has(line.id))) return;
      if (line.id) { seen.add(line.id); if (seen.size > 2000) seen.delete(seen.values().next().value); }
      deliver(line);
    });
    ws.addEventListener('close', (e) => {
      log(`websocket closed ${e.code}, retry in ${backoff}ms`);
      setTimeout(connect, backoff = Math.min(backoff * 2, 60000));
    });
  };
  connect();
}

// --- Out: MP's reply -> YouTube chat ---

// YouTube takes at most 200 characters per chat message and no line breaks: split on word
// boundaries, in order.
export function parts(text, max = 200) {
  const out = [];
  let cur = '';
  for (let w of String(text).replace(/\s+/g, ' ').trim().split(' ')) {
    while (w.length > max) { if (cur) { out.push(cur); cur = ''; } out.push(w.slice(0, max)); w = w.slice(max); }
    if (!w) continue;
    if (cur && cur.length + 1 + w.length > max) { out.push(cur); cur = ''; }
    cur = cur ? `${cur} ${w}` : w;
  }
  if (cur) out.push(cur);
  return out;
}

async function googleToken() {
  const t = readJson(join(GOOGLE, 'tokens.json'), null);
  if (!t?.refresh_token) throw new Error('no Google token yet (see header)');
  const c = readJson(join(GOOGLE, 'client_secret.json'), {});
  const { client_id, client_secret } = c.installed || c.web || {};
  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: t.refresh_token, client_id, client_secret }),
  });
  if (!res.ok) throw new Error(`Google token refresh ${res.status}`);
  return (await res.json()).access_token;
}

async function reply(text) {
  const all = parts(text);
  if (!all.length) { console.error('usage: youtube-chat.mjs reply "text"'); process.exit(2); }
  const st = readJson(STATE, {});
  if (!st.video) { console.error('not posted: no live video seen yet (is serve running?)'); process.exit(1); }
  const auth = { Authorization: `Bearer ${await googleToken()}` };
  const yt = 'https://www.googleapis.com/youtube/v3';
  // The chat of the video the bridge is reading, so it works whichever Google account posts.
  const v = await (await fetch(`${yt}/videos?part=liveStreamingDetails&id=${encodeURIComponent(st.video)}`, { headers: auth })).json();
  const liveChatId = v.items?.[0]?.liveStreamingDetails?.activeLiveChatId;
  if (!liveChatId) { console.error('not posted: that video has no active live chat'); process.exit(1); }
  for (const [i, messageText] of all.entries()) {
    const res = await fetch(`${yt}/liveChat/messages?part=snippet`, {
      method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' },
      body: JSON.stringify({ snippet: { liveChatId, type: 'textMessageEvent', textMessageDetails: { messageText } } }),
    });
    if (!res.ok) { console.error(`posted ${i} of ${all.length}; stopped: YouTube ${res.status}`); process.exit(1); }
  }
  console.log(`posted ${all.length} message(s)`);
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const [cmd = 'serve', ...rest] = process.argv.slice(2);
  if (cmd === 'serve') serve();
  else if (cmd === 'reply') reply(rest.join(' ')).catch((e) => { console.error(`not posted: ${e.message}`); process.exit(1); });
  else if (cmd === 'status') console.log(JSON.stringify({ target: TARGET, video: readJson(STATE, {}).video || null }, null, 2));
  else { console.error('usage: youtube-chat.mjs serve | reply "text" | status'); process.exit(2); }
}
