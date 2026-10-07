"""The owner's local screen: how Door is being used on THIS computer, read straight from the host's own audit log.

Only reachable from this machine (127.0.0.1), only with the secret link printed at start, only with the right Host header (so a web page
in a browser cannot talk to it through DNS tricks), and changes (pause, allow/deny a step) need a custom header a foreign page cannot send.
"""
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import settings
from .common import day_key, month_key

MAX_ROWS = 40000          # newest audit lines considered
MAX_REQUESTS = 120


def usage_report(host):
    rows = []
    for r in host.audit.rows():
        rows.append(r)
        if len(rows) > MAX_ROWS:
            rows.pop(0)
    by = {}
    order = []
    for r in rows:
        rid = r.get("request_id")
        if not rid:
            continue
        q = by.get(rid)
        if q is None:
            q = by[rid] = {"id": rid, "at": r["at"], "ts": r["ts"], "guest": (r.get("guest_id") or "")[-6:], "agent": r.get("agent_alias", ""), "kind": "ask",
                           "question": "", "answer": "", "state": "received", "tokens": 0, "cost": 0.0, "verification": "", "verdict": "", "branch": "", "files": []}
            order.append(rid)
        d, ev = r.get("detail") or {}, r["event"]
        if r.get("agent_alias"):
            q["agent"] = r["agent_alias"]
        if ev == "request_received":
            q["question"] = d.get("text") or ""
        elif ev == "recheck":
            q["state"] = "running" if d.get("ok") else "refused: %s" % d.get("reason", "?")
        elif ev == "act_started":
            q["kind"] = "task"
        elif ev == "routed":
            q["agent"] = r.get("agent_alias", q["agent"])
        elif ev == "reply_filtered":
            q["answer"] = d.get("text") or ""
            q["verification"] = d.get("verification", "")
            if d.get("refused"):
                q["state"] = "declined (outside the allowed topics)"
        elif ev == "reply_sent":
            if not q["state"].startswith("declined"):
                q["state"] = "answered"
        elif ev == "reply_held":
            q["state"] = "held for your review"
        elif ev == "act_finished":
            q["state"] = "task: " + d.get("verdict", "?")
            q["verdict"], q["branch"] = d.get("verdict", ""), d.get("branch") or ""
        elif ev == "canceled":
            q["state"] = "canceled"
        elif ev == "usage":
            q["tokens"] += d.get("input_tokens", 0) + d.get("output_tokens", 0)
            q["cost"] += d.get("cost", 0.0)
        elif ev == "sandbox_exited" and d.get("timeout"):
            q["state"] = "timed out"
    with host._guard:
        running = set(host._running)
    for rid in running:
        if rid in by:
            by[rid]["state"] = "running now"
    today, month = day_key(), month_key()
    tot = {"today_requests": 0, "today_tokens": 0, "month_requests": 0, "month_tokens": 0, "month_cost": 0.0}
    for q in by.values():
        if q["state"].startswith("refused"):
            continue
        if q["at"][:10] == today:
            tot["today_requests"] += 1; tot["today_tokens"] += q["tokens"]
        if q["at"][:7] == month:
            tot["month_requests"] += 1; tot["month_tokens"] += q["tokens"]; tot["month_cost"] += q["cost"]
    pol = host.holder.policy or {}
    pending = []
    for rid, runner in list(host._acts.items()):
        for a in runner.pending_actions():
            pending.append(dict(a, request=rid))
    recent = [by[i] for i in order][-MAX_REQUESTS:][::-1]
    for q in recent:
        q["cost"] = round(q["cost"], 4)
    tot["month_cost"] = round(tot["month_cost"], 4)
    return {"status": {"paused": host.paused(), "policy_ok": host.holder.error is None, "policy_error": host.holder.error,
                       "mode": (pol.get("egress") or {}).get("mode", "api"), "provider": (pol.get("egress") or {}).get("provider", ""),
                       "agents": [{"alias": a["alias"], "backend": a["backend"], "tasks": bool(a.get("act"))} for a in pol.get("agents", [])],
                       "budget": (pol.get("limits") or {}).get("monthly_budget"), "paired": bool(host._kv("host.json")),
                       "running": len(running)},
            "totals": tot, "waiting": pending, "recent": recent}


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Door on this computer</title>
<style nonce="{{N}}">
:root{--bg:#fff;--side:#f7f7f5;--fg:#37352f;--mut:#787774;--line:#e9e9e7;--acc:#2383e2;--ok:#1f7a4d;--bad:#c0392b;--warn:#b7791f}
@media(prefers-color-scheme:dark){:root{--bg:#191919;--side:#202020;--fg:#ffffffcf;--mut:#ffffff71;--line:#ffffff18;--acc:#2f81f7;--ok:#4dab9a;--bad:#eb5757;--warn:#ffa344}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:980px;margin:0 auto;padding:40px 22px 100px}h1{font-size:30px;letter-spacing:-.02em;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 22px}
h2{font-size:15px;margin:30px 0 8px}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:99px;background:var(--side);font-size:13px}.dot{width:8px;height:8px;border-radius:50%;background:var(--ok)}.dot.bad{background:var(--bad)}.dot.warn{background:var(--warn)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card{background:var(--side);border-radius:8px;padding:12px 14px}.card b{display:block;font-size:22px;letter-spacing:-.02em}.card span{color:var(--mut);font-size:12.5px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}th{color:var(--mut);font-weight:400;font-size:12.5px}
tr.q{cursor:pointer}tr.q:hover{background:var(--side)}.det{background:var(--side)}.det pre{white-space:pre-wrap;word-break:break-word;margin:4px 0 10px;font:13px ui-monospace,Menlo,monospace}
button{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:4px 12px;font:inherit;cursor:pointer}button.go{background:var(--acc);color:#fff;border:0}button.no{color:var(--bad)}
.mut{color:var(--mut)}.empty{color:var(--mut);padding:10px 0}
.tabs{display:flex;gap:4px;margin:0 0 22px;border-bottom:1px solid var(--line)}.tabs button{all:unset;cursor:pointer;padding:8px 12px;color:var(--mut)}.tabs button.on{color:var(--fg);box-shadow:inset 0 -2px 0 var(--fg)}
.box{background:var(--side);border-radius:10px;padding:16px 18px;margin:0 0 16px}.box h3{margin:0 0 4px;font-size:15px}.box p.mut{margin:0 0 12px}
input,select,textarea{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font:inherit}textarea{width:100%;min-height:64px;font:13px ui-monospace,Menlo,monospace}
.proj{display:flex;gap:10px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line)}.proj:last-child{border:0}.proj code{color:var(--mut);font-size:12.5px;overflow-wrap:anywhere;flex:1}
label.opt{display:flex;gap:8px;align-items:flex-start;margin:6px 0}label.opt span{color:var(--mut);font-size:12.5px;display:block}
.msg{padding:8px 12px;border-radius:6px;margin:0 0 14px;font-size:13px}.msg.ok{background:#1f7a4d1f;color:var(--ok)}.msg.bad{background:#c0392b1f;color:var(--bad)}
code.cmd{display:block;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:8px 0 0;font-size:12.5px;overflow-wrap:anywhere}
</style></head><body><main>
<h1>Door on this computer</h1><p class="sub">What your agents are doing, and what they may do. This page only opens on this computer; nothing here leaves it.</p>
<nav class="tabs"><button id="t-act" class="on">Activity</button><button id="t-set">Settings</button></nav>
<section id="v-act">
<div class="row" id="status"></div>
<div id="waitbox"></div>
<h2>Usage</h2><div class="cards" id="totals"></div>
<h2>Recent activity</h2><table><thead><tr><th>When</th><th>Who</th><th>Agent</th><th>What happened</th><th>Tokens</th></tr></thead><tbody id="rows"></tbody></table>
<div class="empty" id="none" hidden>Nothing yet.</div>
</section>
<section id="v-set" hidden>
<div id="smsg"></div>
<div class="box"><h3>Projects people can ask about</h3><p class="mut">Door shares a clean copy of the committed files (no .env, keys or secrets folders). Add the folder of a git project.</p>
  <div id="projects"></div>
  <form class="row" id="addp" style="margin-top:10px"><input id="ppath" placeholder="/Users/you/code/my-app" style="flex:1;min-width:260px" required><button class="go">Add project</button></form></div>
<div class="box"><h3>Tasks: having things done</h3><p class="mut" id="where"></p>
  <label class="opt"><input type="checkbox" id="ten"><div>Let people I trust have things done<span>They are trusted one by one in the panel, or with Door Trust in a group.</span></div></label>
  <div id="tmore">
  <div class="row" style="margin:10px 0"><span>Work on</span><select id="tproj"></select></div>
  <label class="opt"><span style="min-width:150px;color:var(--fg)">Running commands</span><select id="tbash"><option value="ask">Ask me each time (unless listed below)</option><option value="off">Never</option></select></label>
  <label class="opt"><span style="min-width:150px;color:var(--fg)">Opening things on my screen</span><select id="topen"><option value="off">Never</option><option value="ask">Ask me each time</option><option value="allow">Allow project files and https links (anything else asks)</option></select></label>
  <label class="opt"><span style="min-width:150px;color:var(--fg)">When I ask for something myself</span><select id="town"><option value="auto">Do it without asking me again</option><option value="ask">Ask me for each risky step</option></select></label>
  <div class="mut" style="margin-top:10px">Commands that run without asking (one per line, e.g. npm test)</div><textarea id="tcmds"></textarea>
  <div class="mut" style="margin-top:10px">Checks Door runs to prove a task worked (one per line; the agent cannot skip them)</div><textarea id="tchecks"></textarea>
  </div>
  <div class="row" style="margin-top:12px"><button class="go" id="tsave">Save tasks</button></div></div>
<div class="box"><h3>Model</h3><p class="mut">Who pays for the AI and which model answers. Keys are read from the macOS Keychain or your own sign-in, never from a file.</p>
  <div class="row"><select id="macc"></select><input id="mmodel" placeholder="model" style="width:240px"><button class="go" id="msave">Save model</button></div>
  <div id="mkey"></div><div id="mrestart"></div></div>
<div class="box"><h3>Monthly budget</h3><p class="mut">New requests stop when this month's model cost reaches it.</p>
  <div class="row">US$ <input id="budget" type="number" min="1" max="10000" step="1" style="width:110px"><button class="go" id="bsave">Save budget</button></div></div>
</section>
</main><script nonce="{{N}}">
const $ = id => document.getElementById(id);
function el(t, c, x){ const e = document.createElement(t); if(c) e.className = c; if(x !== undefined) e.textContent = x; return e; }
function chip(text, kind){ const c = el('span','chip'); c.appendChild(el('i','dot'+(kind?' '+kind:''))); c.appendChild(document.createTextNode(text)); return c; }
async function post(path, body){ const r = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Door-Local':'1'},body:JSON.stringify(body)}); if(!r.ok) alert('Could not do that ('+r.status+')'); load(); }
function when(t){ return new Date(t).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}); }
const open = new Set();
function render(d){
  const s = d.status, st = $('status'); st.textContent = '';
  st.appendChild(chip(s.paused ? 'Paused' : 'Running', s.paused ? 'warn' : ''));
  st.appendChild(chip(s.paired ? 'Paired with the cloud' : 'Not paired yet', s.paired ? '' : 'warn'));
  st.appendChild(chip(s.policy_ok ? 'Policy OK' : 'Policy problem: ' + s.policy_error, s.policy_ok ? '' : 'bad'));
  st.appendChild(chip(s.mode === 'login' ? 'Using your own sign-in' : 'API key (' + (s.provider||'') + ')'));
  s.agents.forEach(a => st.appendChild(chip(a.alias + ' · ' + a.backend + (a.tasks ? ' · can run tasks' : ''))));
  const b = el('button', s.paused ? 'go' : '', s.paused ? 'Resume' : 'Pause everything'); b.onclick = () => post('/api/pause', {paused: !s.paused}); st.appendChild(b);
  const w = $('waitbox'); w.textContent = '';
  if(d.waiting.length){ w.appendChild(el('h2','','Waiting for your OK'));
    d.waiting.forEach(a => { const r = el('div','row'); r.style.marginBottom = '8px'; r.appendChild(el('span','', a.summary));
      const y = el('button','go','Allow'); y.onclick = () => post('/api/decide',{request:a.request,action:a.id,decision:'allow'});
      const n = el('button','no','Refuse'); n.onclick = () => post('/api/decide',{request:a.request,action:a.id,decision:'deny'}); r.appendChild(y); r.appendChild(n); w.appendChild(r); }); }
  const t = d.totals, tt = $('totals'); tt.textContent = '';
  [['Today', t.today_requests + ' requests', t.today_tokens.toLocaleString('en-US') + ' tokens'], ['This month', t.month_requests + ' requests', t.month_tokens.toLocaleString('en-US') + ' tokens'],
   ['Cost this month', 'US$ ' + t.month_cost.toFixed(2), s.mode === 'login' ? 'not metered in sign-in mode' : (s.budget ? 'of US$ ' + s.budget + ' budget' : '')], ['Running now', String(s.running), 'at most one at a time']].forEach(([a,b2,c]) => {
    const k = el('div','card'); k.appendChild(el('span','',a)); k.appendChild(el('b','',b2)); k.appendChild(el('span','',c)); tt.appendChild(k); });
  const body = $('rows'); body.textContent = ''; $('none').hidden = d.recent.length > 0;
  d.recent.forEach(q => {
    const tr = el('tr','q'); [when(q.ts*1000), 'guest …' + q.guest, q.agent + (q.kind === 'task' ? ' (task)' : ''), q.state + (q.verification && q.verification !== 'off' && q.verification !== 'n/a' ? ' · ' + q.verification : ''), q.tokens ? q.tokens.toLocaleString('en-US') : ''].forEach(x => tr.appendChild(el('td','',x)));
    body.appendChild(tr);
    const dt = el('tr','det'); dt.hidden = !open.has(q.id); const td = el('td'); td.colSpan = 5;
    td.appendChild(el('div','mut','Question')); td.appendChild(el('pre','',q.question)); if(q.answer){ td.appendChild(el('div','mut','Answer')); td.appendChild(el('pre','',q.answer)); }
    if(q.branch) td.appendChild(el('div','mut','Saved on branch ' + q.branch)); dt.appendChild(td); body.appendChild(dt);
    tr.onclick = () => { dt.hidden = !dt.hidden; dt.hidden ? open.delete(q.id) : open.add(q.id); };
  });
}
async function load(){ try{ const r = await fetch('/api/usage'); if(r.ok) render(await r.json()); }catch(e){} }
load(); setInterval(load, 3000);
// ---- settings ----
function tab(x){ $('v-act').hidden = x !== 'act'; $('v-set').hidden = x !== 'set'; $('t-act').className = x === 'act' ? 'on' : ''; $('t-set').className = x === 'set' ? 'on' : ''; if(x === 'set') loadSettings(); }
$('t-act').onclick = () => tab('act'); $('t-set').onclick = () => tab('set');
function say(text, ok){ const m = $('smsg'); m.textContent = ''; if(text){ const d = el('div','msg ' + (ok ? 'ok' : 'bad'), text); m.appendChild(d); } window.scrollTo(0, 0); }
async function change(body, done){
  const r = await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json','X-Door-Local':'1'},body:JSON.stringify(body)});
  const d = await r.json().catch(() => ({error:'Could not save'}));
  if(!r.ok){ say(d.error || 'Could not save', false); return; }
  showSettings(d); say(done + (d.restart_needed ? ' Restart Door to use it (button below).' : ''), true);
}
function lines(x){ return x.value.split('\\n').map(s => s.trim()).filter(Boolean); }
function showSettings(d){
  const P = $('projects'); P.textContent = '';
  d.projects.forEach(p => { const r = el('div','proj'); r.appendChild(el('b','',p.name)); r.appendChild(el('code','',p.path));
    const x = el('button','no','Remove'); x.onclick = () => { if(confirm('Stop sharing ' + p.name + '?')) change({op:'project.remove', name:p.name}, 'Removed ' + p.name + '.'); }; r.appendChild(x); P.appendChild(r); });
  const t = d.tasks; $('ten').checked = t.enabled; $('tmore').hidden = !t.enabled;
  const sel = $('tproj'); sel.textContent = ''; d.projects.forEach(p => { const o = el('option','',p.name + '  (' + p.path + ')'); o.value = p.path; sel.appendChild(o); });
  if(t.project) sel.value = t.project;
  $('tbash').value = t.bash; $('topen').value = t.open_on_mac; $('town').value = t.owner_steps; $('tcmds').value = (t.allow_commands||[]).join('\\n'); $('tchecks').value = (t.checks||[]).join('\\n');
  $('where').textContent = 'Where changes go: ' + d.changes_go_to + '. You review the branch and merge it when you want.';
  const a = $('macc'); a.textContent = ''; d.model.choices.forEach(c => { const o = el('option','',c.label); o.value = c.id; o.dataset.model = c.model; a.appendChild(o); });
  a.value = d.model.access; $('mmodel').value = d.model.model;
  a.onchange = () => { $('mmodel').value = a.selectedOptions[0].dataset.model; };
  const k = $('mkey'); k.textContent = '';
  if(d.model.keychain_item){ k.appendChild(el('div','mut','Store the key in the Keychain once (Terminal; it asks for the key without showing it):'));
    k.appendChild(el('code','cmd','security add-generic-password -U -a "$USER" -s ' + d.model.keychain_item + ' -w')); }
  if(d.model.access === 'claude-login'){ k.appendChild(el('div','mut','Sign in once, in Terminal:')); k.appendChild(el('code','cmd','door-host login claude')); }
  const rs = $('mrestart'); rs.textContent = '';
  if(d.restart_needed){ const b = el('button','go','Restart Door now'); b.style.marginTop = '10px';
    b.onclick = async () => { const r = await fetch('/api/restart',{method:'POST',headers:{'Content-Type':'application/json','X-Door-Local':'1'},body:'{}'}); const x = await r.json().catch(() => ({}));
      say(x.message || 'Restarting…', r.ok); if(r.ok) setTimeout(() => location.reload(), 6000); }; rs.appendChild(b); }
  $('budget').value = d.budget;
}
async function loadSettings(){ const r = await fetch('/api/settings'); if(r.ok) showSettings(await r.json()); }
$('addp').onsubmit = e => { e.preventDefault(); change({op:'project.add', path:$('ppath').value}, 'Project added.'); $('ppath').value = ''; };
$('ten').onchange = () => { $('tmore').hidden = !$('ten').checked; };
$('tsave').onclick = () => change({op:'tasks.set', enabled:$('ten').checked, project:$('tproj').value, bash:$('tbash').value, open_on_mac:$('topen').value, owner_steps:$('town').value,
  allow_commands:lines($('tcmds')), checks:lines($('tchecks'))}, $('ten').checked ? 'Tasks saved.' : 'Tasks are off.');
$('msave').onclick = () => change({op:'model.set', access:$('macc').value, model:$('mmodel').value.trim()}, 'Model saved.');
$('bsave').onclick = () => change({op:'budget.set', monthly:$('budget').value}, 'Budget saved.');
if(location.hash === '#settings') tab('set');
</script></body></html>"""


class LocalUI:
    def __init__(self, host, port=9631):
        self.host, self.port = host, port
        tok = Path(host.state_dir) / "local-ui-token"
        if not tok.exists():
            fd = os.open(tok, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, secrets.token_urlsafe(24).encode()); os.close(fd)
        self.token = tok.read_text().strip()
        ui = self
        self._docker = (0.0, False)

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _send(self, code, body=b"", ctype="application/json", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers(); self.wfile.write(body)

            def _ok_host(self):
                return (self.headers.get("Host") or "") in ("127.0.0.1:%d" % ui.port, "localhost:%d" % ui.port)

            def _authed(self):
                ck = {k.strip(): v for k, v in (p.split("=", 1) for p in (self.headers.get("Cookie") or "").split(";") if "=" in p)}
                return secrets.compare_digest(ck.get("door_local", ""), ui.token)

            def do_GET(self):
                if not self._ok_host():
                    return self._send(403, b'{"error":"bad host"}')
                path, _, qs = self.path.partition("?")
                if path == "/" and qs.startswith("t=") and secrets.compare_digest(qs[2:], ui.token):
                    return self._send(302, b"", extra={"Location": "/", "Set-Cookie": "door_local=%s; HttpOnly; SameSite=Strict; Path=/" % ui.token})
                if not self._authed():
                    return self._send(401, b'{"error":"open the link that door-host printed when it started"}')
                if path == "/":
                    n = secrets.token_hex(12)
                    return self._send(200, PAGE.replace("{{N}}", n).encode(), "text/html; charset=utf-8",
                                      {"Content-Security-Policy": "default-src 'none'; script-src 'nonce-%s'; style-src 'nonce-%s'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'" % (n, n)})
                if path == "/api/usage":
                    return self._send(200, json.dumps(usage_report(ui.host), ensure_ascii=False).encode())
                if path == "/api/settings":
                    return self._send(200, json.dumps(settings.view(ui.host.holder.path, ui.host.state_dir), ensure_ascii=False).encode())
                self._send(404, b'{"error":"not found"}')

            def do_POST(self):
                if not self._ok_host() or not self._authed() or self.headers.get("X-Door-Local") != "1":
                    return self._send(403, b'{"error":"forbidden"}')
                try:
                    body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 65536)))
                except (ValueError, TypeError):
                    return self._send(400, b'{"error":"bad body"}')
                if self.path == "/api/pause" and isinstance(body.get("paused"), bool):
                    return self._send(200, json.dumps(ui.host.set_paused(body["paused"])).encode())
                if self.path == "/api/settings":
                    try:
                        out = settings.apply(ui.host.holder.path, ui.host.state_dir, body)
                    except settings.SettingsError as e:
                        return self._send(400, json.dumps({"error": str(e)}).encode())
                    ui.host.holder.refresh()
                    ui.host.audit.write("settings_changed", detail={"op": str(body.get("op"))})
                    return self._send(200, json.dumps(out, ensure_ascii=False).encode())
                if self.path == "/api/restart":
                    if os.environ.get("DOOR_SUPERVISED") != "1":
                        return self._send(400, json.dumps({"message": "Door is not running as a background service here, so restart door-host yourself."}).encode())
                    threading.Timer(0.5, lambda: os._exit(0)).start()       # the background service starts it again with the new settings
                    return self._send(200, json.dumps({"message": "Restarting… this page reloads in a few seconds."}).encode())
                if self.path == "/api/decide":
                    out = ui.host.decide_action(str(body.get("request", "")), str(body.get("action", "")), str(body.get("decision", "")))
                    return self._send(200 if out["ok"] else 400, json.dumps(out).encode())
                self._send(404, b'{"error":"not found"}')

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d/?t=%s" % (self.port, self.token)

    def start(self):
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.1), daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown(); self.httpd.server_close()
