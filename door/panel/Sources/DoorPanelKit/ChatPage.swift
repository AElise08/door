import Foundation

/// The guest's chat page (ChatGPT-style, Door look). All text from the agent or the guest goes in via textContent.
/// Speaks the browser's language (English or Portuguese) and says truthfully how this person is served (auto answers or approval, questions or tasks).
enum ChatPage {
    static let style = #"""
    :root{--bg:#fff;--side:#f7f7f5;--fg:#2f2e2b;--mut:#7b7a75;--line:#ebebe8;--acc:#2383e2;--accfg:#fff;--bub:#f2f1ee;--soft:#e9f2fc;--softfg:#1d5fa3}
    @media(prefers-color-scheme:dark){:root{--bg:#191919;--side:#202020;--fg:#ffffffd9;--mut:#ffffff80;--line:#ffffff1a;--acc:#3b8ef0;--bub:#2a2a2a;--soft:#1f3349;--softfg:#bcd8f7}}
    *{box-sizing:border-box}html,body{height:100%}
    body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;-webkit-font-smoothing:antialiased}
    """#

    static let notice = #"""
    <!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Door</title>
    <style nonce="{{NONCE}}">\#(style) .c{display:grid;place-items:center;height:100%;text-align:center;padding:24px}.c>div{max-width:420px}
    i{width:40px;height:40px;border-radius:11px;background:var(--fg);color:var(--bg);display:inline-grid;place-items:center;font-style:normal;font-weight:700;font-size:20px;margin-bottom:18px}
    h1{font-size:22px;margin:0 0 8px;letter-spacing:-.01em}p{color:var(--mut);margin:0 0 22px}hr{border:0;border-top:1px solid var(--line);margin:0 0 22px}</style></head>
    <body><div class="c"><div><i>D</i>%BODY%</div></div></body></html>
    """#

    static let invalid = notice.replacingOccurrences(of: "%BODY%", with:
        "<h1>This link is not valid</h1><p>It may have expired or been turned off. Ask the person who sent it for a new one.</p><hr>"
        + "<h1>Este link não é válido</h1><p>Ele pode ter vencido ou sido desligado. Peça um novo para quem enviou.</p>")

    static let used = notice.replacingOccurrences(of: "%BODY%", with:
        "<h1>This link was already opened</h1><p>Each link works on one device only. Open it on the device where you first used it, or ask for a new link.</p><hr>"
        + "<h1>Este link já foi aberto</h1><p>Cada link funciona em um aparelho só. Abra no aparelho onde usou da primeira vez, ou peça um link novo.</p>")

    static let html = #"""
    <!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Door</title>
    <style nonce="{{NONCE}}">\#(style)
    .app{display:flex;flex-direction:column;height:100%;max-width:760px;margin:0 auto}
    header{display:flex;align-items:center;gap:10px;padding:14px 18px 10px}
    header i{width:30px;height:30px;border-radius:8px;background:var(--fg);color:var(--bg);display:grid;place-items:center;font-style:normal;font-size:15px;font-weight:700;flex-shrink:0}
    header .t{display:flex;flex-direction:column;line-height:1.25;min-width:0}header b{font-weight:600}header small{color:var(--mut);font-size:12.5px}
    header .st{margin-left:auto;color:var(--mut);font-size:12.5px;white-space:nowrap}
    .tabs{display:flex;gap:2px;padding:0 12px;border-bottom:1px solid var(--line)}
    .tabs button{all:unset;cursor:pointer;color:var(--mut);font-size:14px;padding:8px 12px}
    .tabs button.on{color:var(--fg);box-shadow:inset 0 -2px 0 var(--fg)}
    #log{flex:1;overflow-y:auto;padding:22px 18px 8px}
    .hello{margin:8vh auto 0;max-width:460px;text-align:center}
    .hello h1{font-size:27px;letter-spacing:-.02em;margin:0 0 10px;font-weight:650}
    .hello p{color:var(--mut);margin:0 0 6px}
    .mode{display:inline-flex;gap:6px;flex-wrap:wrap;justify-content:center;margin:12px 0 22px}
    .mode span{font-size:12.5px;padding:3px 10px;border-radius:99px;background:var(--bub);color:var(--mut)}
    .chips{display:flex;flex-direction:column;gap:8px;align-items:stretch}
    .chips button{all:unset;cursor:pointer;text-align:left;border:1px solid var(--line);border-radius:12px;padding:10px 14px;font-size:14.5px;color:var(--fg)}
    .chips button:hover{background:var(--side)}
    .row{display:flex;margin:0 0 14px}.row.guest{justify-content:flex-end}
    .msg{max-width:86%;padding:10px 14px;border-radius:18px;white-space:pre-wrap;word-break:break-word}
    .guest .msg{background:var(--acc);color:var(--accfg);border-bottom-right-radius:6px}
    .agent .msg{background:var(--bub);border-bottom-left-radius:6px}
    .system{justify-content:center}.system .msg{background:none;color:var(--mut);font-size:13px;padding:2px 8px;text-align:center}
    .dots{display:inline-flex;gap:4px;padding:14px 16px}.dots i{width:7px;height:7px;border-radius:50%;background:var(--mut);animation:b 1.2s infinite}
    .dots i:nth-child(2){animation-delay:.15s}.dots i:nth-child(3){animation-delay:.3s}@keyframes b{0%,60%,100%{opacity:.25}30%{opacity:1}}
    form#f{display:flex;gap:10px;align-items:flex-end;padding:8px 18px 6px;background:var(--bg)}
    textarea{flex:1;resize:none;max-height:160px;min-height:48px;padding:13px 16px;border-radius:24px;border:1px solid var(--line);background:var(--side);color:inherit;font:inherit;line-height:1.4}
    textarea:focus{outline:2px solid #2383e244;border-color:var(--acc)}
    #b{width:48px;height:48px;border-radius:50%;border:0;background:var(--acc);color:var(--accfg);cursor:pointer;font-size:19px;flex-shrink:0}
    #b:disabled{opacity:.35;cursor:default}
    .foot{text-align:center;color:var(--mut);font-size:12px;padding:0 18px calc(10px + env(safe-area-inset-bottom))}
    #chatview{display:flex;flex-direction:column;flex:1;min-height:0}#boardview{display:none;flex:1;overflow-y:auto;padding:18px}
    .bform{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px;align-items:center}
    .bform input[type=text]{flex:1;min-width:160px;padding:10px 13px;border-radius:10px;border:1px solid var(--line);background:var(--side);color:inherit;font:inherit}
    .bform label{color:var(--mut);font-size:13px}
    .btn{all:unset;cursor:pointer;border-radius:8px;padding:7px 12px;font-size:13px;background:var(--bub);color:var(--fg)}
    .btn.go{background:var(--acc);color:var(--accfg)}.btn.on{background:var(--soft);color:var(--softfg)}.btn:disabled{opacity:.5;cursor:default}
    .group h4{margin:18px 0 8px;font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--mut);font-weight:600}
    .kc{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:8px;background:var(--bg)}
    .kc b{font-weight:600;word-break:break-word}.kc .nt{color:var(--mut);font-size:13px;white-space:pre-wrap;word-break:break-word;margin-top:2px}
    .kc .r{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;align-items:center}
    .tg{font-size:12px;padding:2px 9px;border-radius:99px;background:var(--bub);color:var(--mut)}.tg.ok{background:#1f7a4d22;color:#1f7a4d}.tg.bad{background:#b91c1c1f;color:#c0392b}
    .kc summary{cursor:pointer;color:var(--mut);font-size:12.5px;margin-top:8px}
    .kc pre{white-space:pre-wrap;word-break:break-word;font:12px ui-monospace,Menlo,monospace;background:var(--side);padding:8px;border-radius:6px;margin:8px 0 0}
    .empty{color:var(--mut);text-align:center;margin-top:40px}
    </style></head><body><div class="app">
    <header><i>D</i><div class="t"><b id="who">Door</b><small id="sub"></small></div><span class="st" id="state"></span></header>
    <nav class="tabs"><button id="tab-chat" class="on"></button><button id="tab-board"></button></nav>
    <div id="chatview">
      <div id="log"><div class="hello" id="hello"><h1 id="h1"></h1><p id="h2"></p><div class="mode" id="mode"></div><div class="chips" id="chips"></div></div></div>
      <form id="f"><textarea id="t" rows="1" maxlength="1600" autofocus></textarea><button id="b" aria-label="Send">&#10148;</button></form>
      <div class="foot" id="foot"></div>
    </div>
    <div id="boardview">
      <form class="bform" id="bf"><input type="text" id="bt" maxlength="120" required>
        <label><input type="checkbox" id="bu"> <span id="lu"></span></label><label><input type="checkbox" id="bi"> <span id="li"></span></label><button class="btn go" id="badd"></button></form>
      <div id="bl"></div>
    </div>
    </div>
    <script nonce="{{NONCE}}">
    const PT = /^pt/i.test(navigator.language || '');
    const L = PT ? {
      chat:'Conversa', board:'Quadro', h1:'Pergunte o que quiser', h2:'Eu respondo a partir do próprio projeto, não da internet.',
      auto:'Respostas na hora', each:'Cada pergunta é aprovada antes', ask:'Só perguntas', act:'Perguntas e tarefas',
      chips:['Do que se trata este projeto?','Como eu começo a usar?','Quais são as partes principais?'],
      ph:'Escreva uma mensagem', footAuto:'As respostas vêm do projeto e podem levar alguns segundos.', footEach:'Uma pessoa aprova cada pergunta, então a resposta pode demorar.',
      waitingOwner:'esperando aprovação', thinking:'respondendo…', closed:'link encerrado', sendFail:'Não consegui enviar',
      todo:'A fazer', doing:'Em andamento', review:'Precisa de revisão', done:'Feito', urgent:'Urgente', important:'Importante', add:'Adicionar',
      bt:'O que precisa ser feito?', empty:'Nada aqui ainda. Adicione o que você precisa acima.', run:'Pedir para o agente fazer', remove:'Remover', proof:'O que foi conferido',
      verd:{verified:'Conferido', checks_passed:'Verificações ok', failed_checks:'Verificações falharam', unverified:'Não confirmado', no_changes:'Nada mudou', incomplete:'Incompleto'},
      cannot:'Não foi possível fazer isso'
    } : {
      chat:'Chat', board:'Board', h1:'Ask anything', h2:'I answer from the project itself, not from the internet.',
      auto:'Instant answers', each:'Each question is approved first', ask:'Questions only', act:'Questions and tasks',
      chips:['What is this project about?','How do I get started?','What are the main parts?'],
      ph:'Write a message', footAuto:'Answers come from the project and can take a few seconds.', footEach:'A person approves each question, so answers can take a while.',
      waitingOwner:'waiting for approval', thinking:'answering…', closed:'link closed', sendFail:'Could not send',
      todo:'To do', doing:'Being done', review:'Needs a look', done:'Done', urgent:'Urgent', important:'Important', add:'Add',
      bt:'What needs to be done?', empty:'Nothing here yet. Add what you need above.', run:'Ask the agent to do this', remove:'Remove', proof:'What was checked',
      verd:{verified:'Verified', checks_passed:'Checks passed', failed_checks:'Checks failed', unverified:'Not verified', no_changes:'No changes', incomplete:'Incomplete'},
      cannot:'Could not do that'
    };
    document.documentElement.lang = PT ? 'pt' : 'en';
    const token = location.pathname.split('/')[2];
    const $ = id => document.getElementById(id);
    const log = $('log'), t = $('t'), b = $('b');
    let last = 0, waiting = false, auto = true;
    function mk(tag, cls, text){ const e = document.createElement(tag); if(cls) e.className = cls; if(text !== undefined) e.textContent = text; return e; }
    $('tab-chat').textContent = L.chat; $('tab-board').textContent = L.board; $('h1').textContent = L.h1; $('h2').textContent = L.h2;
    t.placeholder = L.ph; $('bt').placeholder = L.bt; $('lu').textContent = L.urgent; $('li').textContent = L.important; $('badd').textContent = L.add;
    L.chips.forEach(q => { const c = mk('button','',q); c.onclick = () => { t.value = q; send(); }; $('chips').appendChild(c); });
    function setMode(i){
      auto = !!i.auto; const m = $('mode'); m.textContent = '';
      m.appendChild(mk('span','', auto ? L.auto : L.each)); m.appendChild(mk('span','', i.tasks ? L.act : L.ask));
      $('foot').textContent = auto ? L.footAuto : L.footEach;
      if(i.name) $('sub').textContent = i.name;
    }
    setMode({auto:true, tasks:false});
    function add(m){
      $('hello') && $('hello').remove();
      const row = mk('div','row ' + m.role); row.appendChild(mk('div','msg', m.text));
      log.insertBefore(row, $('typing'));
    }
    function typing(on){
      let d = $('typing');
      if(on && !d){ d = mk('div','row agent'); d.id = 'typing'; const x = mk('div','msg dots'); for(let i=0;i<3;i++) x.appendChild(mk('i')); d.appendChild(x); log.appendChild(d); }
      if(!on && d) d.remove();
    }
    function scroll(){ log.scrollTop = log.scrollHeight; }
    async function poll(){
      try{
        const r = await fetch('/chat/'+token+'/messages?after='+last);
        if(r.status === 403 || r.status === 404){ $('state').textContent = L.closed; waiting = false; typing(false); return; }
        const d = await r.json(); let got = false;
        (d.messages||[]).forEach(m => { if(m.id > last){ last = m.id; add(m); got = true; if(m.role === 'agent') waiting = false; } });
        typing(waiting); if(got) scroll();
        $('state').textContent = waiting ? (auto ? L.thinking : L.waitingOwner) : '';
      }catch(e){}
    }
    async function send(){
      const text = t.value.trim(); if(!text) return;
      b.disabled = true;
      const r = await fetch('/chat/'+token+'/send', {method:'POST', headers:{'Content-Type':'application/json','X-Door-Chat':'1'}, body: JSON.stringify({text})});
      if(r.ok){ t.value = ''; t.style.height = 'auto'; waiting = true; await poll(); }
      else { const e = await r.json().catch(()=>({})); alert(e.error || L.sendFail); }
      b.disabled = false; t.focus();
    }
    $('f').onsubmit = e => { e.preventDefault(); send(); };
    t.addEventListener('keydown', e => { if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); } });
    t.addEventListener('input', () => { t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 160) + 'px'; });
    function info(){ fetch('/chat/'+token+'/info').then(r => r.json()).then(setMode).catch(()=>{}); }
    info(); setInterval(info, 30000);
    // ---- board ----
    const GROUPS = [['todo',L.todo],['doing',L.doing],['review',L.review],['done',L.done]];
    const VCLS = {verified:'ok', checks_passed:'ok'};
    let tab = 'chat';
    async function card(body){
      const r = await fetch('/chat/'+token+'/card', {method:'POST', headers:{'Content-Type':'application/json','X-Door-Chat':'1'}, body: JSON.stringify(body)});
      if(!r.ok){ const e = await r.json().catch(()=>({})); alert(e.error || L.cannot); }
      await loadBoard(); return r.ok;
    }
    async function loadBoard(){
      let d; try { d = await (await fetch('/chat/'+token+'/board')).json(); } catch(e){ return; }
      const box = $('bl'); box.textContent = ''; const cards = d.cards || [];
      if(!cards.length){ box.appendChild(mk('div','empty',L.empty)); return; }
      GROUPS.forEach(([key,label]) => { const mine = cards.filter(c => c.column === key); if(!mine.length) return;
        const g = mk('div','group'); g.appendChild(mk('h4','',label + ' · ' + mine.length));
        mine.forEach(c => { const k = mk('div','kc'); k.appendChild(mk('b','',c.title)); if(c.note) k.appendChild(mk('div','nt',c.note));
          const r = mk('div','r'); const open = c.column !== 'done';
          [['urgent',L.urgent],['important',L.important]].forEach(([f,l]) => { const x = mk('button', 'btn' + (c[f] ? ' on' : ''), l); x.disabled = !open;
            x.onclick = () => card({op:'update', card_id:c.id, [f]:!c[f]}); r.appendChild(x); });
          if(L.verd[c.verdict]) r.appendChild(mk('span','tg '+(VCLS[c.verdict]||'bad'), L.verd[c.verdict]));
          if(c.column === 'todo'){ const go = mk('button','btn go',L.run); go.onclick = async () => { if(await card({op:'run', card_id:c.id})) setTab('chat'); }; r.appendChild(go);
            const del = mk('button','btn',L.remove); del.onclick = () => card({op:'delete', card_id:c.id}); r.appendChild(del); }
          k.appendChild(r);
          if(c.proof){ const p = document.createElement('details'); p.appendChild(mk('summary','',L.proof)); p.appendChild(mk('pre','',c.proof)); k.appendChild(p); }
          g.appendChild(k); }); box.appendChild(g); });
    }
    function setTab(x){ tab = x; $('chatview').style.display = x === 'chat' ? 'flex' : 'none'; $('boardview').style.display = x === 'board' ? 'block' : 'none';
      $('tab-chat').className = x === 'chat' ? 'on' : ''; $('tab-board').className = x === 'board' ? 'on' : ''; if(x === 'board') loadBoard(); }
    $('tab-chat').onclick = () => setTab('chat'); $('tab-board').onclick = () => setTab('board');
    $('bf').onsubmit = async e => { e.preventDefault(); if(await card({op:'add', title:$('bt').value, urgent:$('bu').checked, important:$('bi').checked})){ $('bt').value = ''; $('bu').checked = $('bi').checked = false; } };
    setInterval(() => { if(tab === 'board') loadBoard(); }, 4000);
    poll(); setInterval(poll, 2000);
    </script></body></html>
    """#
}
