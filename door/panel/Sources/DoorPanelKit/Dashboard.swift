import Foundation

/// Panel HTML. Everything that comes from the agent (including guest text) is inserted with textContent only.
enum Dashboard {
    static func login(error: String?) -> String {
        let err = error.map { "<p class=\"err\">\($0)</p>" } ?? ""
        return """
        <!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Door</title><style nonce="{{NONCE}}">        :root{--bg:#fff;--side:#f7f7f5;--fg:#37352f;--mut:#787774;--line:#e9e9e7;--hover:#efefed;--acc:#2383e2;--accfg:#fff;--quote:#37352f;
        --gray:#e3e2e0;--grayfg:#32302c;--green:#dbeddb;--greenfg:#1c3829;--yellow:#fdecc8;--yellowfg:#402c1b;--red:#ffe2dd;--redfg:#5d1715;--blue:#d3e5ef;--bluefg:#183347}
        @media(prefers-color-scheme:dark){:root{--bg:#191919;--side:#202020;--fg:#ffffffcf;--mut:#ffffff71;--line:#ffffff18;--hover:#ffffff10;--acc:#2f81f7;
        --gray:#454b4e;--grayfg:#ffffffcf;--green:#2b4a3a;--greenfg:#cfeedd;--yellow:#5a4a2a;--yellowfg:#f5deb0;--red:#5a2f2c;--redfg:#ffd6d1;--blue:#28456c;--bluefg:#d3e5ff}}

        *{box-sizing:border-box}body{background:var(--bg);color:var(--fg);font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0}
        form{width:min(340px,88vw)}h1{font-size:30px;font-weight:700;margin:0 0 4px;letter-spacing:-.02em}p.s{color:var(--mut);margin:0 0 22px}
        input,button{width:100%;padding:8px 10px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:inherit;font:inherit}
        input:focus{outline:2px solid #2383e255;border-color:var(--acc)}
        button{background:var(--acc);color:var(--accfg);border:0;margin-top:10px;font-weight:500;cursor:pointer}button:hover{filter:brightness(.95)}.err{color:#eb5757;margin:0 0 10px}
        </style></head><body><form method="post" action="/login"><h1>Door</h1><p class="s">Sign in with your owner token.</p>\(err)
        <input type="password" name="token" placeholder="Owner token" autocomplete="current-password" autofocus><button>Continue</button></form></body></html>
        """
    }

    static let html = #"""
    <!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Door</title><style nonce="{{NONCE}}">
    :root{--bg:#fff;--side:#f7f7f5;--fg:#37352f;--mut:#787774;--line:#e9e9e7;--hover:#efefed;--acc:#2383e2;--accfg:#fff;--quote:#37352f;
      --gray:#e3e2e0;--grayfg:#32302c;--green:#dbeddb;--greenfg:#1c3829;--yellow:#fdecc8;--yellowfg:#402c1b;--red:#ffe2dd;--redfg:#5d1715;--blue:#d3e5ef;--bluefg:#183347}
    @media(prefers-color-scheme:dark){:root{--bg:#191919;--side:#202020;--fg:#ffffffcf;--mut:#ffffff71;--line:#ffffff18;--hover:#ffffff10;--acc:#2f81f7;
      --gray:#454b4e;--grayfg:#ffffffcf;--green:#2b4a3a;--greenfg:#cfeedd;--yellow:#5a4a2a;--yellowfg:#f5deb0;--red:#5a2f2c;--redfg:#ffd6d1;--blue:#28456c;--bluefg:#d3e5ff}}

    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;-webkit-font-smoothing:antialiased}
    .app{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}aside,main{min-width:0}
    aside{background:var(--side);border-right:1px solid var(--line);padding:12px 8px;display:flex;flex-direction:column;gap:2px;position:sticky;top:0;height:100vh}
    .ws{display:flex;align-items:center;gap:8px;padding:6px 10px 14px;font-weight:600;font-size:15px}
    .ws i{width:22px;height:22px;border-radius:5px;background:var(--fg);color:var(--bg);display:grid;place-items:center;font-style:normal;font-size:13px;font-weight:700}
    nav button{all:unset;box-sizing:border-box;display:flex;align-items:center;gap:8px;width:100%;padding:5px 10px;border-radius:5px;color:var(--mut);cursor:pointer;font-size:14px}
    nav button:hover{background:var(--hover)}nav button.on{background:var(--hover);color:var(--fg);font-weight:500}nav .n{margin-left:auto;font-size:12px;color:var(--mut)}
    .grow{flex:1}.status{padding:8px 10px;color:var(--mut);font-size:12px;display:flex;align-items:center;gap:7px}
    .dot{width:8px;height:8px;border-radius:50%;background:#4dab9a}.dot.warn{background:#ffa344}.dot.bad{background:#eb5757}
    .side-btn{all:unset;box-sizing:border-box;padding:5px 10px;border-radius:5px;color:var(--mut);cursor:pointer;font-size:13px;display:block;width:100%}.side-btn:hover{background:var(--hover);color:var(--fg)}
    main{padding:56px 28px 120px;max-width:820px;width:100%;margin:0 auto}
    h1{font-size:30px;line-height:1.2;font-weight:700;letter-spacing:-.02em;margin:0 0 6px}
    .sub{color:var(--mut);margin:0 0 20px}
    .callout{display:flex;flex-direction:column;gap:2px;background:var(--side);border-radius:8px;padding:12px 14px;margin:0 0 22px;color:var(--fg);font-size:13.5px}.callout span{color:var(--mut)}
    .callout b{font-weight:600}
    .view{display:none}.view.on{display:block}
    .item{padding:14px 6px;border-bottom:1px solid var(--line);border-radius:4px}
    .item:hover{background:var(--hover)}
    .who{display:flex;align-items:center;gap:10px;margin-bottom:8px}
    .av{width:24px;height:24px;border-radius:50%;background:var(--gray);color:var(--grayfg);display:grid;place-items:center;font-size:11px;font-weight:600;flex-shrink:0}
    .who b{font-weight:600}.mut{color:var(--mut);font-size:12.5px}
    blockquote{margin:0 0 10px;padding:2px 0 2px 14px;border-left:3px solid var(--quote);font-size:15px;white-space:pre-wrap;word-break:break-word;max-height:240px;overflow:auto}
    .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
    button.b{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:4px 11px;font:inherit;font-size:13px;cursor:pointer;box-shadow:0 1px 1px #0000000a}
    button.b:hover{background:var(--hover)}button.go{background:var(--acc);color:var(--accfg);border-color:transparent}button.go:hover{filter:brightness(.95);background:var(--acc)}
    button.no{color:#eb5757}button:disabled{opacity:.5;cursor:default}
    .tag{display:inline-block;padding:0 7px;border-radius:4px;font-size:12px;line-height:20px;background:var(--gray);color:var(--grayfg)}
    .tag.ok{background:var(--green);color:var(--greenfg)}.tag.warn{background:var(--yellow);color:var(--yellowfg)}.tag.bad{background:var(--red);color:var(--redfg)}.tag.info{background:var(--blue);color:var(--bluefg)}
    input{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:5px 8px;font:inherit;min-width:0}input:focus{outline:2px solid #2383e255;border-color:var(--acc)}
    .empty{color:var(--mut);padding:14px 6px}
    .big{font-size:40px;font-weight:700;letter-spacing:-.02em;line-height:1.1}.big span{font-size:16px;color:var(--mut);font-weight:400}
    .bar{height:6px;background:var(--gray);border-radius:99px;overflow:hidden;margin:14px 0 8px}.bar i{display:block;height:100%;background:#4dab9a}
    h2{font-size:16px;font-weight:600;margin:30px 0 8px}
    td.nowrap{white-space:nowrap;color:var(--mut);font-size:13px}td.req{max-width:420px}
    table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{color:var(--mut);font-weight:400;font-size:12.5px}
    .add{margin-top:18px;padding:12px;border:1px dashed var(--line);border-radius:6px}
    main.wide{max-width:1240px}
    .bhead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 18px}
    .seg{display:inline-flex;background:var(--side);border-radius:7px;padding:2px}.seg button{all:unset;cursor:pointer;padding:4px 12px;border-radius:5px;font-size:13px;color:var(--mut)}
    .seg button.on{background:var(--bg);color:var(--fg);box-shadow:0 1px 2px #0000001a}
    .cols4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:start}
    .col,.quad{background:var(--side);border-radius:10px;padding:10px 8px 6px}
    .col h3,.quad h3{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:600;margin:2px 6px 10px;color:var(--fg)}
    .col h3 .cnt,.quad h3 .cnt{color:var(--mut);font-weight:400}.col h3 i{width:8px;height:8px;border-radius:50%;flex-shrink:0}
    .c-todo i{background:#9b9a97}.c-doing i{background:#2383e2}.c-review i{background:#d9730d}.c-done i{background:#0f7b6c}
    .quad .qsub{color:var(--mut);font-size:12px;margin:-8px 6px 10px}
    .col.over,.quad.over{outline:2px dashed var(--acc);outline-offset:-2px}
    .kcard{position:relative;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 34px 9px 11px;margin-bottom:8px;cursor:grab;box-shadow:0 1px 2px #0000000d}
    .kcard:hover{border-color:#d3d1cb}.kcard.done b{color:var(--mut);text-decoration:line-through;text-decoration-color:#0000002e}
    .kcard b{display:block;font-weight:500;font-size:14px;line-height:1.4;word-break:break-word}
    .kcard .note{color:var(--mut);font-size:12.5px;margin-top:3px;word-break:break-word;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
    .kcard .meta{display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin-top:7px}.kcard .meta:empty{display:none}
    .kcard .meta .by{display:inline-flex;align-items:center;gap:5px;color:var(--mut);font-size:12px}
    .kcard .meta .by .av{width:18px;height:18px;font-size:9.5px}
    .pill{font-size:11.5px;line-height:19px;padding:0 7px;border-radius:4px}.pill.u{background:var(--red);color:var(--redfg)}.pill.i{background:var(--yellow);color:var(--yellowfg)}
    .kmenu{position:absolute;top:6px;right:6px}.kmenu>button{all:unset;cursor:pointer;width:22px;height:22px;border-radius:5px;display:grid;place-items:center;color:var(--mut);font-size:15px;line-height:1;opacity:0}
    .kcard:hover .kmenu>button,.kmenu.open>button{opacity:1}.kmenu>button:hover{background:var(--hover)}
    @media(hover:none){.kmenu>button{opacity:1}}
    .kmenu .pop{display:none;position:absolute;right:0;top:26px;z-index:5;min-width:190px;background:var(--bg);border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px #0000001f;padding:4px}
    .kmenu.open .pop{display:block}.pop button{all:unset;box-sizing:border-box;display:block;width:100%;padding:6px 10px;border-radius:5px;font-size:13px;cursor:pointer}
    .pop button:hover{background:var(--hover)}.pop .sep{height:1px;background:var(--line);margin:4px 2px}.pop .lbl{font-size:11px;color:var(--mut);padding:4px 10px 2px}.pop button.no{color:#eb5757}
    .kcard details summary{cursor:pointer;color:var(--mut);font-size:12px;margin-top:6px}
    .kcard pre{background:var(--side);padding:6px 8px;border-radius:5px;font-size:11.5px;white-space:pre-wrap;word-break:break-word;margin:6px 0 0;max-height:220px;overflow:auto}
    .addc{all:unset;box-sizing:border-box;display:block;width:100%;cursor:pointer;color:var(--mut);font-size:13px;padding:6px 8px;border-radius:6px}.addc:hover{background:var(--hover);color:var(--fg)}
    .addf{margin-bottom:8px}.addf input{width:100%;padding:8px 10px;border-radius:8px}
    .addf .row{margin-top:6px;gap:6px}
    .bempty{color:var(--mut);font-size:12.5px;padding:4px 8px 10px}
    .mx{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start}@media(max-width:760px){.mx{grid-template-columns:1fr}.cols4{grid-template-columns:1fr}}
    .stale{display:none;background:var(--yellow);color:var(--yellowfg);border-radius:5px;padding:6px 10px;margin-bottom:14px;font-size:13px}
    @media(max-width:760px){.app{grid-template-columns:minmax(0,1fr);grid-template-rows:auto 1fr;align-content:start}aside{align-content:flex-start;gap:4px}aside{position:static;height:auto;flex-direction:row;flex-wrap:wrap;align-items:center;padding:8px;border-right:0;border-bottom:1px solid var(--line)}
      .ws{padding:4px 8px}nav{display:flex;flex-wrap:nowrap;overflow-x:auto;order:3;width:100%;scrollbar-width:none}nav button{width:auto;flex-shrink:0}
      #plan{display:none}table{font-size:13px}td.req{max-width:none}.grow{display:none}main{padding:24px 16px 80px}h1{font-size:28px}.status{order:2;margin-left:auto}.side-btn{width:auto}}
    </style></head><body><div class="app">
    <aside><div class="ws"><i>D</i><span id="wsname">Door</span></div>
      <nav><button data-v="queue" class="on">Approvals<span class="n" id="n-queue"></span></button><button data-v="board">Board<span class="n" id="n-board"></span></button><button data-v="held">Held replies<span class="n" id="n-held"></span></button>
        <button data-v="guests">Guests<span class="n" id="n-guests"></span></button><button data-v="cost">Cost</button><button data-v="hist">History</button></nav>
      <div class="grow"></div>
      <div class="status"><span id="macdot" class="dot"></span><span id="mac">Mac…</span></div><div class="status" id="proj" title="Change projects, model and permissions in Door on this computer, on your Mac"></div><div class="status" id="plan"></div>
      <button class="side-btn" id="pause"></button><form method="post" action="/logout" style="margin:0"><button class="side-btn">Sign out</button></form></aside>
    <main><div class="stale" id="stale">Showing stale data: the agent has not reported recently.</div>
      <h1 id="title"></h1><p class="sub" id="subtitle"></p>
      <section class="view on" id="v-queue"><div id="setup"></div><div id="actions"></div>
        <div class="item" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap"><div style="flex:1;min-width:220px"><b>Answer without asking me</b>
          <div class="mut" id="approval-hint"></div></div><button class="b" id="approval-toggle"></button></div>
        <div id="queue"></div></section>
      <section class="view" id="v-board">
        <div class="bhead"><div class="seg"><button id="mode-cols" class="on">Columns</button><button id="mode-matrix">Priority</button></div>
          <span class="mut" id="bhint">Drag cards between columns, or use ⋯ on a card.</span></div>
        <div id="board"></div></section>
      <section class="view" id="v-held"><div id="held"></div></section>
      <section class="view" id="v-guests">
        <div class="callout"><b id="scope-a">Questions.</b><span id="scope-b">Guests read a copy of your code. They cannot change anything in your project.</span></div>
        <div class="item" style="background:var(--side);border-radius:8px;border:0;margin-bottom:18px">
          <b>Give someone access</b>
          <div class="mut" style="margin:4px 0 12px">Send them a link and they chat with your agent in the browser. No app, no phone number. It opens on one device only, expires, and you can turn it off.</div>
          <form id="weblink" class="row"><input name="display_name" placeholder="Their name" style="width:170px"><input name="days" type="number" min="1" max="90" value="30" style="width:64px" title="days of access"><span class="mut">days</span><button class="b go">Create link</button></form>
          <div id="newlink" style="margin-top:10px"></div>
          <div class="mut" style="margin-top:12px">Prefer texting? Message your Door number: <b>Door Link Ana</b> (sends you a link) or <b>Door Invite Ana</b> (gives you a code to forward).</div>
        </div>
        <div id="access"></div>
        <h2 style="margin-top:6px">Open links</h2><div id="links"></div>
        <h2>People with access</h2><div id="guests"></div>
        <details style="margin-top:22px"><summary class="mut" style="cursor:pointer">More ways to add someone</summary>
          <div style="margin-top:12px"><b>Invite code</b>
            <div class="mut" style="margin:4px 0 8px">They text <b>Door Join: CODE</b> to your Door number (also inside a group chat) and they are in.</div>
            <form id="invite" class="row"><input name="display_name" placeholder="Name (optional)" style="width:150px"><input name="days" type="number" min="1" max="90" value="30" style="width:64px" title="days of access once joined"><span class="mut">days</span><button class="b go">Create code</button></form>
            <div id="invites" style="margin-top:12px"></div></div>
          <form id="add" class="add"><div class="mut" style="margin-bottom:8px">Add a phone number yourself. Only people on this list can text the agent.</div>
            <div class="row"><input name="display_name" placeholder="Name" style="width:130px"><input name="phone" placeholder="+15551234567" required style="width:160px">
            <input name="days" type="number" min="1" max="90" value="30" style="width:64px" title="days of access"><span class="mut">days</span><button class="b go">Add guest</button></div></form>
        </details>
      </section>
      <section class="view" id="v-cost"><div id="cost"></div></section>
      <section class="view" id="v-hist"><div id="hist"></div></section>
    </main></div>
    <script nonce="{{NONCE}}">
    const $ = id => document.getElementById(id);
    function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!==undefined&&text!==null) e.textContent=String(text); return e; }
    function clear(n){ while(n.firstChild) n.removeChild(n.firstChild); }
    function when(t){ return t ? new Date(t*1000).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}) : ''; }
    function days(n){ return n + (n === 1 ? ' day' : ' days'); }
    function initials(n){ return (n||'?').replace(/[^\p{L}\p{N} ]/gu,'').split(' ').filter(Boolean).slice(0,2).map(x=>x[0].toUpperCase()).join('') || '?'; }
    const TITLES = {queue:['Approvals','Questions waiting for your decision. By default people are answered without waiting for you.'], board:['Board','What people asked for, what is being done, and what still needs a look. Tasks show proof of what was really done.'], held:['Held replies','Replies the safety filter stopped. Nothing was sent to the guest yet.'],
      guests:['Guests','Who can talk to your agent, by chat link or by text message.'], cost:['Cost','What the model has cost this month, on your own API key.'], hist:['History','Every request and what happened to it.']};
    const STATE = {waitingApproval:['waiting for you','warn'], queued:['queued','info'], running:['answering','info'], completed:['answered','ok'], failed:['failed','bad'], canceled:['canceled','']};
    const REASON = {denied_owner:'you denied it', denied_rules:'blocked by rules', expired:'expired without a decision', budget:'budget exhausted', timeout:'took too long',
      sandbox_error:'error while answering', out_of_scope:'declined: outside the allowed topics', rejected_host:'Mac refused', guest_canceled:'guest canceled', owner_canceled:'you canceled'};
    let view = 'queue', boardMode = 'cols', lastState = {};
    function show(v){ view = v; document.querySelectorAll('.view').forEach(s => s.classList.toggle('on', s.id === 'v-'+v));
      document.querySelectorAll('nav button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
      document.querySelector('main').classList.toggle('wide', v === 'board');
      $('title').textContent = TITLES[v][0]; $('subtitle').textContent = TITLES[v][1]; try{ history.replaceState(null,'','#'+v); }catch(e){} }
    document.querySelectorAll('nav button').forEach(b => b.onclick = () => show(b.dataset.v));
    async function send(cmd){
      const r = await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json','X-Door-Panel':'1'},body:JSON.stringify(cmd)});
      if(r.status===401) location.reload();
      if(!r.ok) alert('Command refused ('+r.status+')');
      load();
    }
    function btn(label, cls, cmd, confirmText){
      const b = el('button','b '+cls, label);
      b.onclick = () => { if(confirmText && !confirm(confirmText)) return; b.disabled = true; send(cmd); };
      return b;
    }
    function who(name, sub){ const w = el('div','who'); w.appendChild(el('div','av',initials(name))); const t = el('div'); t.appendChild(el('b','',name)); t.appendChild(el('div','mut',sub)); w.appendChild(t); return w; }
    let wantApproval = null;
    let render = function(st){
      $('wsname').textContent = st.tenant || 'Door';
      const s = st.snapshot || {}, mac = s.mac || {};
      $('mac').textContent = mac.paused ? 'Mac paused' : (mac.online === false ? 'Mac offline' : 'Mac online');
      $('macdot').className = 'dot ' + (mac.paused ? 'warn' : mac.online === false ? 'bad' : '');
      const billed = s.plan && s.plan.active_until && s.plan.active_until < Date.now()/1000 + 365*86400;
      $('plan').textContent = !s.plan ? '' : s.plan.status !== 'active' ? 'Plan ' + s.plan.status
        : billed ? 'Plan active until ' + new Date(s.plan.active_until*1000).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}) : '';
      $('proj').textContent = (s.projects||[]).length ? (s.projects.join(', ') + (s.engine ? ' · ' + s.engine.split(' · ').pop() : '')) : '';
      $('stale').style.display = st.stale ? 'block' : 'none';
      const p = $('pause'); p.textContent = mac.paused ? 'Resume agent' : 'Pause agent';
      p.onclick = () => send({type: mac.paused ? 'resume' : 'pause'});

      $('scope-a').textContent = s.act_enabled ? 'Questions and tasks.' : 'Questions only.';
      $('scope-b').textContent = s.act_enabled
        ? 'Guests ask about a copy of your code. People you give tasks to can ask for changes: they happen on a throwaway copy, risky steps wait for your OK, and nothing is marked Done without proof.'
        : 'Guests read a copy of your code. They cannot change anything in your project.';
      const shown = s.approval || 'each';
      if (wantApproval && wantApproval === shown) wantApproval = null;          // the Mac has caught up
      const saving = !!wantApproval, autoOn = (wantApproval || shown) === 'auto';
      $('approval-toggle').textContent = saving ? 'Saving…' : (autoOn ? 'On: turn off' : 'Off: turn on');
      $('approval-toggle').className = 'b ' + (autoOn ? 'go' : '');
      $('approval-toggle').disabled = saving;
      $('approval-toggle').onclick = () => { wantApproval = autoOn ? 'each' : 'auto'; render(lastState); send({type:'set_approval', mode: wantApproval}); setTimeout(() => { wantApproval = null; render(lastState); }, 60000); };
      $('approval-hint').textContent = autoOn ? 'Questions from people you let in are answered right away, within their daily limits and your budget. Turn off to approve every question yourself.'
                                              : 'Every question waits here for your OK before anything is answered.';
      lastState = st;
      const su = $('setup'); clear(su); const sp = s.setup || {};
      if(sp.activated === false || sp.paired === false){
        const b = el('div','item'); b.style.background = 'var(--side)';
        b.appendChild(el('b','','Finish setting up'));
        if(!sp.activated) b.appendChild(el('div','mut','1. Text this to your Door number from your phone: Door Activate: ' + (sp.activation_code || '(a new code appears here shortly)')));
        else b.appendChild(el('div','mut','1. Your phone is connected. ✓'));
        b.appendChild(el('div','mut', sp.paired ? '2. Your computer is connected. ✓' : '2. On your computer run: door-host pair, then text the code it prints to your Door number as: Door Pair: <code>'));
        su.appendChild(b);
      }
      const ac = $('actions'); clear(ac); const acts = s.actions || [];
      acts.forEach(a => {
        const d = el('div','item'); d.appendChild(who(a.guest||'?', 'a running task needs your OK for one step'));
        d.appendChild(el('blockquote','', a.summary));
        const row = el('div','row');
        row.appendChild(btn('Allow this step','go',{type:'action_allow',request_id:a.request_id,action_id:a.action_id}));
        row.appendChild(btn('Refuse','no',{type:'action_deny',request_id:a.request_id,action_id:a.action_id}));
        d.appendChild(row); ac.appendChild(d);
      });
      const q = $('queue'); clear(q); const qs = s.queue||[]; $('n-queue').textContent = (qs.length + acts.length) || '';
      qs.forEach(r => {
        const d = el('div','item');
        d.appendChild(who(r.guest||'?', 'asked "' + (r.agent||'') + '" · request ' + (r.used_today ?? '?') + ' of ' + (r.limit_today ?? '?') + ' allowed today · expires ' + when(r.deadline_at)));
        d.appendChild(el('blockquote','', r.text));
        const row = el('div','row');
        row.appendChild(btn('Approve','go',{type:'approve',request_id:r.request_id,text_hash:r.text_hash}));
        row.appendChild(btn('Deny','no',{type:'deny',request_id:r.request_id,text_hash:r.text_hash}));
        d.appendChild(row); q.appendChild(d);
      });
      if(!q.firstChild) q.appendChild(el('div','empty','Nothing is waiting for you.'));

      const h = $('held'); clear(h); const hs0 = s.held||[]; $('n-held').textContent = hs0.length || '';
      hs0.forEach(r => {
        const d = el('div','item'); d.appendChild(who(r.guest||'?', 'reply held by the filter')); d.appendChild(el('blockquote','', r.held_text));
        const row = el('div','row');
        row.appendChild(btn('Send anyway','go',{type:'release',request_id:r.request_id},'Send this reply to the guest?'));
        row.appendChild(btn('Discard','no',{type:'discard',request_id:r.request_id}));
        d.appendChild(row); h.appendChild(d);
      });
      if(!h.firstChild) h.appendChild(el('div','empty','No held replies.'));

      const c = $('cost'); clear(c); const co = s.cost || {};
      const pct = Math.min(100, Math.round(co.pct || 0));
      const lvl = pct >= 100 ? 'bad' : pct >= 80 ? 'warn' : 'ok';
      const big = el('div','big', (co.currency||'USD') + ' ' + (co.month_spent||0).toFixed(2)); big.appendChild(el('span','', '  of ' + (co.budget||0).toFixed(2) + ' budget')); c.appendChild(big);
      const bar = el('div','bar'); const i = el('i'); i.style.width = pct + '%'; i.style.background = {ok:'#4dab9a',warn:'#ffa344',bad:'#eb5757'}[lvl]; bar.appendChild(i); c.appendChild(bar);
      const sr = el('div','row'); sr.appendChild(el('span','tag '+lvl, pct + '% used' + (pct>=100?' · stopped':''))); sr.appendChild(el('span','mut','Alerts at 50%, 80% and 100%. At 100% new requests are denied.')); c.appendChild(sr);
      c.appendChild(el('h2','','By guest'));
      const t = el('table'); const hr = el('tr'); ['Guest','Tokens','Cost'].forEach(x => hr.appendChild(el('th','',x))); t.appendChild(hr);
      (s.usage_by_guest||[]).forEach(u => { const tr = el('tr'); [u.guest, (u.tokens||0).toLocaleString('en-US'), (u.cost||0).toFixed(2)].forEach(x => tr.appendChild(el('td','',x))); t.appendChild(tr); });
      c.appendChild(t);

      const ax = $('access'); clear(ax); const reqs = s.access_requests||[]; $('n-guests').textContent = reqs.length || '';
      reqs.forEach(r => {
        const d = el('div','item'); d.appendChild(who(r.name || r.phone, r.phone + ' asked for access · ' + when(r.at)));
        const row = el('div','row');
        row.appendChild(btn('Let in','go',{type:'allow_access',phone:r.phone}));
        row.appendChild(btn('Ignore','no',{type:'ignore_access',phone:r.phone}));
        d.appendChild(row); ax.appendChild(d);
      });
      const lk = $('links'); clear(lk); if(!(st.links||[]).some(x => !x.revoked)) lk.appendChild(el('div','empty','No open links.'));
      (st.links||[]).filter(x => !x.revoked).forEach(x => {
        const row = el('div','row'); row.style.marginBottom = '6px';
        row.appendChild(el('span','tag ' + (x.opened ? 'ok' : 'info'), x.opened ? 'in use' : 'not opened yet'));
        row.appendChild(el('span','', x.name || 'Unnamed link'));
        row.appendChild(el('span','mut', 'valid until ' + when(x.expires) + ' · ' + days(x.days) + ' of access' + (x.last_seen ? ' · last seen ' + when(x.last_seen) : '')));
        row.appendChild(btn('Turn off','no',{type:'revoke_link',link_id:x.id},'Turn off this link? The person will lose access.'));
        lk.appendChild(row);
      });
      const iv = $('invites'); clear(iv);
      (s.invites||[]).forEach(i => {
        const row = el('div','row'); row.style.marginBottom = '6px';
        const code = el('code','', i.code); code.style.cssText = 'font:600 15px ui-monospace,Menlo,monospace;letter-spacing:.08em;background:var(--side);padding:3px 8px;border-radius:5px';
        row.appendChild(code);
        row.appendChild(el('span','mut', (i.name ? i.name + ' · ' : '') + 'valid until ' + when(i.expires_at) + ' · ' + days(i.days) + ' of access'));
        row.appendChild(btn('Copy','',{type:'__copy'}));
        row.lastChild.onclick = () => { try { navigator.clipboard.writeText('Door Join: ' + i.code); } catch(e){} };
        row.appendChild(btn('Revoke','no',{type:'revoke_invite',code:i.code}));
        iv.appendChild(row);
      });
      if(!iv.firstChild) iv.appendChild(el('div','mut','No open invites.'));
      const g = $('guests'); clear(g);
      (s.guests||[]).forEach(u => {
        const d = el('div','item'); d.appendChild(who(u.name || u.phone, u.phone + ' · access until ' + when(u.expires_at)));
        const row = el('div','row'); row.appendChild(el('span','tag '+(u.status==='active'?'ok':'warn'), u.status));
        if(s.act_enabled){
          const act = u.level === 'act';
          row.appendChild(el('span','tag '+(act?'info':''), act ? 'can run tasks' : 'questions only'));
          row.appendChild(btn(act ? 'Questions only' : 'Allow tasks','',{type:'guest_level',guest_id:u.guest_id,level: act ? 'ask' : 'act'},
            act ? null : 'Let '+(u.name||u.phone)+' have tasks done on your computer? Work happens in a throwaway copy of the project and risky steps ask you first, but only do this for people you trust.'));
        }
        const mode = u.approval || 'default';
        row.appendChild(el('span','tag '+(mode==='each'?'warn':''), mode==='each' ? 'asks my OK' : mode==='auto' ? 'auto-answer' : 'default'));
        row.appendChild(btn(mode==='each' ? 'Auto-answer' : 'Ask my OK','',{type:'guest_approval',guest_id:u.guest_id,mode: mode==='each' ? 'auto' : 'each'}));
        if(mode!=='default') row.appendChild(btn('Use default','',{type:'guest_approval',guest_id:u.guest_id,mode:'default'}));
        if(u.status==='active') row.appendChild(btn('Suspend','',{type:'suspend',guest_id:u.guest_id}));
        else if(u.status==='suspended') row.appendChild(btn('Reactivate','',{type:'reactivate',guest_id:u.guest_id}));
        if(u.status!=='revoked') row.appendChild(btn('Revoke','no',{type:'revoke',guest_id:u.guest_id},'Revoke access for '+(u.name||u.phone)+'?'));
        d.appendChild(row); g.appendChild(d);
      });
      if(!g.firstChild) g.appendChild(el('div','empty','No guests yet.'));

      const hs = $('hist'); clear(hs); const ht = el('table'); const hh = el('tr');
      ['When','Who','Request','Result'].forEach(x => hh.appendChild(el('th','',x))); ht.appendChild(hh);
      (s.history||[]).forEach(r => { const tr = el('tr'); const sv = STATE[r.state] || [r.state,''];
        const td = el('td'); td.appendChild(el('span','tag '+sv[1], sv[0])); if(r.reason) td.appendChild(el('span','mut','  '+(REASON[r.reason]||r.reason)));
        const V = {verified:['verified in files','ok'], partly:['partly verified','warn'], unverified:['not verified','bad']};
        if(V[r.verification]){ td.appendChild(document.createTextNode(' ')); const vt = el('span','tag '+V[r.verification][1], V[r.verification][0]);
          if((r.files||[]).length) vt.title = 'Checked in: ' + r.files.join(', '); td.appendChild(vt); }
        [when(r.updated_at), r.guest].forEach(x => tr.appendChild(el('td','nowrap',x)));
        const rq = el('td','req'); if(r.kind === 'task') rq.appendChild(el('span','tag info','task')); rq.appendChild(document.createTextNode((r.kind === 'task' ? ' ' : '') + (r.text || '')));
        tr.appendChild(rq); tr.appendChild(td); ht.appendChild(tr); });
      if(!(s.history||[]).length) hs.appendChild(el('div','empty','Nothing yet. Share a link from Guests, or text your Door number.'));
      hs.appendChild(ht);
    };
    async function load(){
      try{ const r = await fetch('/api/state'); if(r.status===401){ location.reload(); return; } render(await r.json()); }catch(e){}
    }
    $('weblink').onsubmit = async e => {
      e.preventDefault(); const f = new FormData(e.target);
      const r = await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json','X-Door-Panel':'1'},
        body:JSON.stringify({type:'web_link', display_name:f.get('display_name'), days:parseInt(f.get('days'),10)||30})});
      if(!r.ok){ alert('Could not create the link ('+r.status+')'); return; }
      const j = await r.json(), url = location.origin + j.path, box = $('newlink'); clear(box);
      box.appendChild(el('div','mut','Copy it now. For safety it is shown only once.'));
      const row = el('div','row'); const inp = el('input'); inp.value = url; inp.readOnly = true; inp.style.cssText = 'flex:1;min-width:220px';
      inp.onfocus = () => inp.select(); row.appendChild(inp);
      const cp = el('button','b go','Copy'); cp.onclick = () => { inp.select(); try { navigator.clipboard.writeText(url); cp.textContent = 'Copied'; } catch(x){} }; row.appendChild(cp);
      box.appendChild(row); e.target.reset(); load();
    };
    $('invite').onsubmit = e => {
      e.preventDefault(); const f = new FormData(e.target);
      send({type:'invite', display_name:f.get('display_name'), days:parseInt(f.get('days'),10)||30}); e.target.reset();
    };
    $('add').onsubmit = e => {
      e.preventDefault(); const f = new FormData(e.target);
      send({type:'add_guest', phone:f.get('phone'), display_name:f.get('display_name'), days:parseInt(f.get('days'),10)||30}); e.target.reset();
    };
    const initialView = (location.hash || '').slice(1);          // what the address asked for, before anything rewrites it
    show(initialView in TITLES ? initialView : 'board');
    const COLS = [['todo','To do'],['doing','Doing'],['review','Review'],['done','Done']];
    const VERDICT = {opened:['Opened on your screen','ok'], open_unconfirmed:['Opened, not confirmed','warn'], verified:['Verified','ok'], checks_passed:['Checks passed','ok'], failed_checks:['Checks failed','bad'], unverified:['Not verified','warn'],
                     no_changes:['No changes','warn'], incomplete:['Incomplete','bad'], canceled:['Canceled','']};
    function ownerName(c, st){
      if(c.owner === 'owner' || ((st.snapshot||{}).owner_keys||[]).includes(c.owner)) return 'You';
      const l = (st.links||[]).find(x => x.id === c.owner); if(l) return l.name || 'Chat link';
      const g = ((st.snapshot||{}).guests||[]).find(x => 'g_' + x.guest_id === c.owner); return g ? (g.name || g.phone) : 'Guest';
    }
    function kcard(c, st){
      const k = el('div','kcard' + (c.column === 'done' ? ' done' : '')); k.draggable = true; k.dataset.id = c.id;
      k.ondragstart = e => { e.dataTransfer.setData('text/plain', c.id); };
      k.appendChild(el('b','',c.title)); if(c.note && c.note !== c.title) k.appendChild(el('div','note',c.note));
      const meta = el('div','meta');
      if(c.urgent) meta.appendChild(el('span','pill u','Urgent'));
      if(c.important) meta.appendChild(el('span','pill i','Important'));
      if(VERDICT[c.verdict]) meta.appendChild(el('span','tag '+VERDICT[c.verdict][1], VERDICT[c.verdict][0]));
      const who = ownerName(c, st);
      if(who && who !== 'You'){ const by = el('span','by'); by.appendChild(el('span','av',initials(who))); by.appendChild(document.createTextNode(who)); meta.appendChild(by); }
      k.appendChild(meta);
      if(c.proof){ const d = document.createElement('details'); d.appendChild(el('summary','','What was checked')); d.appendChild(el('pre','',c.proof)); k.appendChild(d); }
      // the ⋯ menu: everything you can do with a card, without buttons cluttering every card
      const m = el('div','kmenu'), mb = el('button','','⋯'); mb.title = 'Card actions'; mb.setAttribute('aria-label','Card actions');
      const pop = el('div','pop');
      mb.onclick = e => { e.stopPropagation(); const was = m.classList.contains('open'); closeMenus(); if(!was) m.classList.add('open'); };
      const item = (label, cmd, cls, confirmText) => { const x = el('button', cls || '', label);
        x.onclick = e => { e.stopPropagation(); if(confirmText && !confirm(confirmText)) return; closeMenus(); send(cmd); }; pop.appendChild(x); };
      pop.appendChild(el('div','lbl','Move to'));
      COLS.filter(([key]) => key !== c.column).forEach(([key,label]) => item(label, {type:'card_move',card_id:c.id,column:key}));
      pop.appendChild(el('div','sep'));
      item(c.urgent ? 'Not urgent' : 'Mark urgent', {type:'card_update',card_id:c.id,urgent:!c.urgent});
      item(c.important ? 'Not important' : 'Mark important', {type:'card_update',card_id:c.id,important:!c.important});
      pop.appendChild(el('div','sep'));
      item('Delete', {type:'card_delete',card_id:c.id}, 'no', 'Delete this card?');
      m.appendChild(mb); m.appendChild(pop); k.appendChild(m);
      return k;
    }
    function closeMenus(){ document.querySelectorAll('.kmenu.open').forEach(x => x.classList.remove('open')); }
    document.addEventListener('click', closeMenus);
    function addCard(col, extra){
      const wrap = el('div'); const open = el('button','addc','+ Add a card');
      open.onclick = () => { clear(wrap); const f = el('form','addf'); const i = el('input'); i.placeholder = 'What needs to be done?'; i.maxLength = 120; i.required = true;
        const r = el('div','row'); const ok = el('button','b go','Add'); const no = el('button','b','Cancel'); no.type = 'button';
        no.onclick = () => { clear(wrap); wrap.appendChild(open); };
        f.onsubmit = e => { e.preventDefault(); const t = i.value.trim(); if(!t) return; send(Object.assign({type:'card_add', title:t, column:col}, extra || {})); i.value = ''; i.focus(); };
        i.onkeydown = e => { if(e.key === 'Escape') no.onclick(); };
        r.appendChild(ok); r.appendChild(no); f.appendChild(i); f.appendChild(r); wrap.appendChild(f); i.focus(); };
      wrap.appendChild(open); return wrap;
    }
    function dropZone(zone, onDrop){
      zone.ondragover = e => { e.preventDefault(); zone.classList.add('over'); };
      zone.ondragleave = () => zone.classList.remove('over');
      zone.ondrop = e => { e.preventDefault(); zone.classList.remove('over'); onDrop(e.dataTransfer.getData('text/plain')); };
    }
    let boardSig = '';
    function renderBoard(st, force){
      const all = st.cards || [], b = $('board');
      const cards = all.filter(c => c.verdict !== 'canceled');                // canceled requests leave the board; finished ones stay in Done
      $('n-board').textContent = cards.filter(c => c.column === 'review').length || '';
      $('mode-cols').className = boardMode === 'cols' ? 'on' : ''; $('mode-matrix').className = boardMode === 'matrix' ? 'on' : '';
      // do not rebuild under the owner's hands: an open menu or a card being typed would vanish every 3 seconds
      const sig = boardMode + JSON.stringify(all) + JSON.stringify((st.links||[]).map(l => [l.id, l.name]));
      const busy = document.querySelector('.kmenu.open') || (document.activeElement && b.contains(document.activeElement) && document.activeElement.tagName === 'INPUT');
      if(!force && (sig === boardSig || busy)) return;
      boardSig = sig; clear(b);
      if(boardMode === 'cols'){
        $('bhint').textContent = 'Drag cards between columns, or use ⋯ on a card.';
        const g = el('div','cols4');
        COLS.forEach(([key,label]) => { const col = el('div','col'); const mine = cards.filter(c => c.column === key);
          const h = el('h3','c-' + key); h.appendChild(el('i')); h.appendChild(document.createTextNode(label)); h.appendChild(el('span','cnt', String(mine.length))); col.appendChild(h);
          mine.forEach(c => col.appendChild(kcard(c, st)));
          if(!mine.length && key !== 'todo') col.appendChild(el('div','bempty', key === 'done' ? 'Finished work shows up here, with proof.' : 'Nothing here.'));
          if(key === 'todo') col.appendChild(addCard('todo'));
          dropZone(col, id => { if(id) send({type:'card_move',card_id:id,column:key}); }); g.appendChild(col); });
        b.appendChild(g);
        const gone = all.length - cards.length;
        if(gone){ const x = el('div','mut', gone + ' canceled card(s) hidden. '); const clr = el('a','', 'Delete them'); clr.href = '#';
          clr.onclick = e => { e.preventDefault(); if(confirm('Delete the canceled cards?')) all.filter(c => c.verdict === 'canceled').forEach(c => send({type:'card_delete', card_id:c.id})); };
          x.appendChild(clr); x.style.marginTop = '14px'; b.appendChild(x); }
      } else {
        $('bhint').textContent = 'Open cards by urgency and importance. Drag a card to change its priority.';
        const Q = [['Do first','Urgent and important',true,true],['Schedule','Important, not urgent',false,true],['Quick wins','Urgent, not important',true,false],['Later','Neither',false,false]];
        const g = el('div','mx');
        Q.forEach(([name,sub,u,i]) => { const q = el('div','quad'); const mine = cards.filter(c => c.column !== 'done' && !!c.urgent === u && !!c.important === i);
          const h = el('h3'); h.appendChild(document.createTextNode(name)); h.appendChild(el('span','cnt', String(mine.length))); q.appendChild(h); q.appendChild(el('div','qsub',sub));
          mine.forEach(c => q.appendChild(kcard(c, st)));
          q.appendChild(addCard('todo', {urgent:u, important:i}));
          dropZone(q, id => { if(id) send({type:'card_update',card_id:id,urgent:u,important:i}); }); g.appendChild(q); });
        b.appendChild(g);
        const done = cards.filter(c => c.column === 'done').length; if(done) b.appendChild(el('div','mut', done + ' finished card(s) are in Done; they leave the priority view once finished.'));
      }
    }
    $('mode-cols').onclick = () => { boardMode = 'cols'; renderBoard(lastState, true); };
    $('mode-matrix').onclick = () => { boardMode = 'matrix'; renderBoard(lastState, true); };
    const _render = render; render = st => { _render(st); renderBoard(st); };
    let first = true;
    const _render2 = render; render = st => { _render2(st);
      if(first){ first = false; const s = st.snapshot || {}; const want = initialView;
        show(TITLES[want] ? want : ((s.queue||[]).length || (s.actions||[]).length) ? 'queue' : 'board'); } };
    load(); setInterval(load, 3000);
    </script></body></html>
    """#
}
