'use strict';
(function(){
  const wsUrl = (location.protocol === 'https:') ? 'wss://' + location.host + '/ws' : 'ws://' + location.host + '/ws';
  let ws;
  let running = false;
  const transcript = document.getElementById('transcript');
  const pendingDiv = document.getElementById('pending');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('sendBtn');
  const newlineBtn = document.getElementById('newlineBtn');
  const abortBtn = document.getElementById('abortBtn');
  const status = document.getElementById('status');

  function setRunning(v){ running = !!v; input.disabled = running; sendBtn.disabled = running; status.textContent = running ? 'agent running' : 'idle'; }

  function addTranscript(evt){
    const el = document.createElement('div');
    el.className = 'evt';
    const kind = document.createElement('span'); kind.className='kind'; kind.textContent = evt.kind || evt.type || 'evt';
    el.appendChild(kind);
    const content = document.createElement('span');
    if(evt.kind === 'user_text'){
      content.textContent = evt.text;
    } else if(evt.kind === 'assistant_text'){
      content.textContent = evt.text;
    } else if(evt.kind === 'tool_call'){
      content.textContent = `${evt.name} ${JSON.stringify(evt.args || {})}`;
    } else if(evt.kind === 'approval_pending'){
      content.textContent = `${evt.tool_key} pending (call_id=${evt.call_id})`;
    } else if(evt.kind === 'function_call_output'){
      try{ content.textContent = JSON.stringify(JSON.parse(evt.output), null, 0); }catch(e){ content.textContent = String(evt.output); }
    } else if(evt.kind === 'status'){
      content.textContent = evt.msg || JSON.stringify(evt);
    } else if(evt.kind === 'approval_decision'){
      content.textContent = `${evt.call_id} -> ${evt.decision || evt.allowed}`;
    } else if(evt.kind === 'aborted'){
      content.textContent = '[aborted]';
    } else {
      content.textContent = JSON.stringify(evt);
    }
    el.appendChild(content);
    transcript.appendChild(el);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function addPending(item){
    // item: {call_id, tool_key, args_json}
    const id = item.call_id;
    const el = document.createElement('div');
    el.className = 'pending-item';
    el.id = 'pending-'+id;
    const title = document.createElement('div'); title.textContent = item.tool_key; el.appendChild(title);
    const meta = document.createElement('div'); meta.className='meta';
    let argsStr = '';
    try { argsStr = item.args_json ? JSON.stringify(JSON.parse(item.args_json)) : ''; } catch(e) { argsStr = String(item.args_json || ''); }
    meta.textContent = `call_id=${id} args=${argsStr}`; el.appendChild(meta);
    const btns = document.createElement('div'); btns.style.marginTop='6px';
    const a = document.createElement('button'); a.textContent='Allow'; a.onclick = ()=>{ ws.send(JSON.stringify({type:'approve', call_id:id})); removePending(id); };
    const d = document.createElement('button'); d.textContent='Deny'; d.style.marginLeft='8px'; d.onclick = ()=>{ ws.send(JSON.stringify({type:'deny', call_id:id})); removePending(id); };
    btns.appendChild(a); btns.appendChild(d); el.appendChild(btns);
    pendingDiv.appendChild(el);
  }

  function removePending(call_id){ const el = document.getElementById('pending-'+call_id); if(el) el.remove(); }

  function handleServer(msg){
    // v1 uses 'type'; v0 used 'kind'. Normalize to k.
    const k = msg.kind || msg.type;

    // Always show core events in transcript for debugging
    if (k === 'user_text' || k === 'assistant_text' || k === 'tool_call' || k === 'function_call_output' || k === 'approval_pending' || k === 'approval_decision' || k === 'run_status' || k === 'error' || k === 'accepted' || k === 'welcome' || k === 'snapshot') {
      addTranscript({ kind: k, ...msg });
    }

    if (k === 'approval_pending') {
      addPending(msg);
      setRunning(true);
    }

    if (k === 'approval_decision') {
      // If we tracked call_id, remove its pending entry
      if (msg.call_id) removePending(msg.call_id);
    }

    if (k === 'function_call_output') {
      // Tool finished; remove pending for that call if present
      if (msg.call_id) removePending(msg.call_id);
    }

    if (k === 'run_status') {
      const st = msg.run_state && msg.run_state.status;
      if (st === 'running' || st === 'awaiting_approval') setRunning(true);
      if (st === 'finished' || st === 'error' || st === 'aborting') setRunning(false);
    }

    if (k === 'error') {
      // Surface errors; do not block UI
      setRunning(false);
      console.error('server error', msg);
    }
  }

  function connect(){
    ws = new WebSocket(wsUrl);
    ws.addEventListener('open', ()=>{ console.log('ws open'); });
    ws.addEventListener('message', (ev)=>{
      try{
        const env = JSON.parse(ev.data);
        const msg = (env && typeof env === 'object' && 'payload' in env) ? env.payload : env;
        handleServer(msg);
      }catch(e){ console.error('bad msg', ev.data); }
    });
    ws.addEventListener('close', ()=>{ console.log('ws closed'); setTimeout(connect, 1000); });
  }

  sendBtn.onclick = ()=>{ const v = input.value.trim(); if(!v) return; ws.send(JSON.stringify({type:'send', text:v})); setRunning(true); };
  newlineBtn.onclick = ()=>{ const pos = input.selectionStart || 0; input.value = input.value.slice(0,pos) + '\n' + input.value.slice(pos); input.focus(); };
  abortBtn.onclick = ()=>{ ws.send(JSON.stringify({type:'abort'})); };

  input.addEventListener('keydown', (e)=>{
    if((e.ctrlKey || e.metaKey) && e.key === 'Enter'){
      e.preventDefault(); sendBtn.click();
    } else if(e.shiftKey && e.key === 'Enter'){
      // default inserts newline in textarea; do nothing special
    }
  });

  connect();
})();
