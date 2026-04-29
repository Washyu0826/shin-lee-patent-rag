// ─── State ───
let token = localStorage.getItem('token') || '';
let chatHistory = JSON.parse(localStorage.getItem('chatHistory') || '[]');
let lang = localStorage.getItem('lang') || 'en';
let msgIdCounter = 0;
const i18n = {
  en:{nav_chat:'Chat',nav_patents:'Patents',nav_compare:'Compare',nav_admin:'Admin',upload_title:'Upload',upload_hint:'Drop PDF/XML here',files_title:'Files',stats_title:'Stats',patent_browser:'Patent Browser',compare_title:'Patent Comparison',admin_title:'Admin Dashboard',
       welcome_title:'Patent RAG Chatbot',welcome_body:'Ask in English or Chinese. Citations link back to the source page.',
       placeholder_q:'Ask about patents…',btn_send:'Send',btn_logout:'Logout',btn_export:'Export',btn_compare:'Compare',btn_run:'Run',
       label_funnel:'Retrieval funnel',label_all_files:'All files',
       col_chunks:'Chunks',col_docs:'Docs',col_queries:'Queries',col_latency:'Avg Latency'},
  zh:{nav_chat:'聊天',nav_patents:'專利瀏覽',nav_compare:'比較',nav_admin:'管理',upload_title:'上傳',upload_hint:'拖放 PDF/XML',files_title:'檔案',stats_title:'統計',patent_browser:'專利瀏覽器',compare_title:'專利比較',admin_title:'管理後台',
       welcome_title:'專利 RAG 對話機器人',welcome_body:'可用中英文提問，引用會連回原始頁面。',
       placeholder_q:'輸入專利相關問題…',btn_send:'送出',btn_logout:'登出',btn_export:'匯出',btn_compare:'比較',btn_run:'執行',
       label_funnel:'檢索流程',label_all_files:'全部檔案',
       col_chunks:'片段',col_docs:'文件',col_queries:'查詢',col_latency:'平均延遲'}
};

// ─── Auth ───
if(!token){document.getElementById('loginOverlay').style.display='flex'}
async function doLogin(){
  const u=document.getElementById('loginUser').value,p=document.getElementById('loginPass').value;
  try{
    const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
    if(!r.ok)throw new Error('Invalid');
    const d=await r.json();token=d.token;localStorage.setItem('token',token);
    document.getElementById('loginOverlay').style.display='none';refreshAll();
  }catch{document.getElementById('loginErr').style.display='block';document.getElementById('loginErr').textContent='Invalid credentials'}
}
function logout(){token='';localStorage.removeItem('token');location.reload()}
function authHeaders(){return token?{'Authorization':'Bearer '+token}:{}}

// ─── i18n ───
function setLang(l){
  lang=l;localStorage.setItem('lang',l);
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const k=el.dataset.i18n;
    if(i18n[l]?.[k]) el.textContent=i18n[l][k];
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>{
    const k=el.dataset.i18nPlaceholder;
    if(i18n[l]?.[k]) el.placeholder=i18n[l][k];
  });
  const sel=document.getElementById('langSel');if(sel)sel.value=l;
}
setLang(lang);

// ─── Theme toggle (dark/light) ───
function toggleTheme(){
  const cur=document.documentElement.getAttribute('data-theme')||'light';
  const next=cur==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',next);
  localStorage.setItem('theme',next);
}

// ─── SVG icon library (Lucide-derived, inline for tree-shake-free use) ───
const ICONS = {
  thumbsUp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88z"/></svg>',
  thumbsDown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88z"/></svg>',
  fileEmpty: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  inbox: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
};

// ─── Toast notification ───
function toast(msg, kind){
  // kind: 'success' | 'error' | 'info' | 'warning'
  const t=document.createElement('div');
  t.className='toast toast-'+(kind||'info');
  t.textContent=msg;
  document.body.appendChild(t);
  setTimeout(()=>{t.classList.add('toast-leaving');setTimeout(()=>t.remove(),200)},3500);
}

// ─── Skeleton helpers ───
function skelRows(n, cls){
  cls = cls || 'skel-line';
  return Array.from({length:n}, ()=>`<div class="skel-row"><div class="skeleton skel-line"></div><div class="skeleton skel-pill"></div></div>`).join('');
}
function skelTableRows(n, cols){
  return Array.from({length:n},()=>`<tr>${Array.from({length:cols},()=>'<td><div class="skeleton skel-line"></div></td>').join('')}</tr>`).join('');
}
function emptyState(icon, title, body){
  return `<div class="empty-state">
    <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${icon}</svg>
    <div class="empty-state-title">${esc(title)}</div>
    <div class="empty-state-body">${esc(body)}</div>
  </div>`;
}

// ─── Upload ───
const dz=document.getElementById('dz'),fi=document.getElementById('fi');
dz.addEventListener('click',()=>fi.click());
dz.addEventListener('dragover',e=>{e.preventDefault();dz.style.borderColor='var(--pri)'});
dz.addEventListener('dragleave',()=>dz.style.borderColor='');
dz.addEventListener('drop',e=>{e.preventDefault();dz.style.borderColor='';handleFiles(e.dataTransfer.files)});
fi.addEventListener('change',e=>handleFiles(e.target.files));

async function handleFiles(files){
  const ocr=document.getElementById('ocrSel').value,tag=document.getElementById('tagInput').value;
  const status = document.getElementById('upStatus');
  for(const f of files){
    status.textContent=`Uploading ${f.name}…`;
    const fd=new FormData();fd.append('file',f);
    const isXml=f.name.toLowerCase().endsWith('.xml');
    const url=isXml?`/api/ingest/xml?tag=${encodeURIComponent(tag)}`:`/api/upload?ocr_engine=${encodeURIComponent(ocr)}&tag=${encodeURIComponent(tag)}`;
    try{
      const r=await fetch(url,{method:'POST',body:fd,headers:authHeaders()});
      if(!r.ok){const e=await r.json();throw new Error(e.detail)}
      const d=await r.json();
      status.textContent='';
      const chunks = d.chunks_created || d.chunks;
      toast(`${f.name} → ${chunks} chunks indexed`, 'success');
      addBot(`<b>${esc(f.name)}</b> ingested — ${chunks} chunks`);
      refreshAll();
    }catch(e){
      status.textContent='';
      toast(`Upload failed: ${e.message}`, 'error');
    }
  }
  fi.value='';
}

// ─── Chat (Streaming) ───
document.getElementById('qi').addEventListener('keydown',e=>{if(e.key==='Enter')send()});

// Stage display config — order matters; matches backend pipeline events
const STAGE_ORDER = ['route','hyde','search','threshold','gen'];
const STAGE_LABEL = {
  route:'route',hyde:'HyDE expand',search:'retrieve',threshold:'gate',gen:'generate'
};

function renderStageBar(stages, totalMs){
  // stages: [{stage, status, elapsed_ms, ...}, ...] — pairs of start/done per stage
  const buckets = {};
  STAGE_ORDER.forEach(s=>buckets[s]={start:null,end:null});
  for(const s of stages){
    if(buckets[s.stage]===undefined) continue;
    if(s.status==='start') buckets[s.stage].start = s.elapsed_ms;
    else if(s.status==='done') buckets[s.stage].end = s.elapsed_ms;
  }
  // Backfill: stages with only one event or missing start use neighbours
  let last = 0;
  STAGE_ORDER.forEach(name=>{
    const b = buckets[name];
    if(b.start===null && b.end!==null) b.start = last;
    if(b.start!==null) last = b.start;
    if(b.end!==null) last = b.end;
  });
  const segs = STAGE_ORDER.map(name=>{
    const b = buckets[name];
    const dur = (b.end!=null && b.start!=null) ? Math.max(0, b.end - b.start) : 0;
    return {name, dur};
  }).filter(s=>s.dur>0);
  if(!segs.length) return '';
  const total = segs.reduce((a,b)=>a+b.dur,0) || 1;
  const bar = segs.map(s=>`<div class="seg seg-${s.name}" style="flex-grow:${s.dur}" title="${STAGE_LABEL[s.name]} · ${s.dur}ms"></div>`).join('');
  const legend = segs.map(s=>`<span><i class="seg-${s.name}" style="background:var(--card)"></i>${STAGE_LABEL[s.name]} ${(s.dur/1000).toFixed(s.dur<1000?2:1)}s</span>`).join('');
  // Legend dots reuse seg-* colours via inline override
  const legendFixed = segs.map(s=>{
    const c = {route:'#94a3b8',hyde:'#a78bfa',search:'#60a5fa',threshold:'#fbbf24',gen:'#34d399'}[s.name];
    return `<span><i style="background:${c}"></i>${STAGE_LABEL[s.name]} ${(s.dur/1000).toFixed(s.dur<1000?2:1)}s</span>`;
  }).join('');
  return `<div class="stage-bar"><div class="pb">${bar}</div><div class="legend">${legendFixed}</div></div>`;
}

function detectConfidence(answer){
  // Backend prompt asks LLM to end with "Confidence: HIGH/MEDIUM/LOW"
  const m = /Confidence:\s*(HIGH|MEDIUM|LOW)/i.exec(answer||'');
  return m ? m[1].toUpperCase() : null;
}

async function send(presetQ, opts){
  opts = opts || {};
  if(!token){document.getElementById('loginOverlay').style.display='flex';return}
  const q=(presetQ||document.getElementById('qi').value).trim();if(!q)return;
  addUser(esc(q));if(!presetQ)document.getElementById('qi').value='';
  document.getElementById('sendBtn').disabled=true;
  const t0=performance.now();
  const lid='ld'+Date.now();
  document.getElementById('msgs').insertAdjacentHTML('beforeend',`<div class="msg bot loading" id="${lid}"><div class="av">AI</div><div class="bubble"><div id="${lid}_label">Routing query…</div><div id="${lid}_stage" class="stage-bar"></div></div></div>`);
  scroll();

  const scope=document.getElementById('scopeSel').value;
  let engine = opts.engine || document.getElementById('engineSel')?.value || 'auto';
  let useHyde = (opts.use_hyde !== undefined) ? opts.use_hyde : (document.getElementById('hydeChk')?.checked||false);
  const autoRoute = (engine==='auto');
  if(autoRoute){engine='m3'} // placeholder; backend overrides via auto_route flag
  const body={query:q,top_k:5,stream:true,history:chatHistory.slice(-10),engine,use_hyde:useHyde,auto_route:autoRoute};
  if(scope){if(scope.startsWith('xml:'))body.doc_number_filter=scope.slice(4);else body.filename_filter=scope}

  const liveStages = [];
  const renderLiveStage = (name, status, info)=>{
    const labelEl = document.getElementById(lid+'_label');
    if(!labelEl) return;
    const txt = {
      route: info?.reason ? `Route → engine=${info.engine}, hyde=${info.use_hyde} (${info.reason})` : 'Routing query…',
      hyde: status==='start' ? 'Writing hypothetical answer (HyDE)…' : `HyDE expanded (${info?.expanded_chars||'?'} chars)`,
      search: status==='start' ? `Searching (${info?.engine||engine})…` : `Retrieved ${info?.results||0} candidates`,
      threshold: status==='done' ? `Top score ${info?.top_score?.toFixed?.(3)??info?.top_score} (floor ${info?.min_required})` : '',
      gen: status==='start' ? 'Generating…' : `Generated ${info?.chars||0} chars`,
    }[name] || `${name}: ${status}`;
    if(txt) labelEl.textContent = txt;
  };

  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json',...authHeaders()},body:JSON.stringify(body)});
    if(r.status===429){document.getElementById(lid)?.remove();addBot('Rate limit exceeded. Please wait.');document.getElementById('sendBtn').disabled=false;return}
    if(!r.ok){const e=await r.json();throw new Error(e.detail)}

    const reader=r.body.getReader(),dec=new TextDecoder();
    let buf='', fullAnswer='',sources=[],tokens=0,ttftMs=null,el=null,mid=null;
    let summary={}, lowConfidenceMsg=null;
    while(true){
      const{done,value}=await reader.read();if(done)break;
      buf += dec.decode(value, {stream:true});
      let nl;
      while((nl = buf.indexOf('\n')) >= 0){
        const line = buf.slice(0, nl); buf = buf.slice(nl+1);
        if(!line) continue;
        let d; try{d = JSON.parse(line)}catch{continue}
        if(d.type==='stage'){
          liveStages.push(d);
          renderLiveStage(d.stage, d.status, d);
          // Update partial progress bar live
          const sb=document.getElementById(lid+'_stage');
          if(sb) sb.innerHTML = renderStageBar(liveStages, performance.now()-t0).replace(/^<div class="stage-bar">|<\/div>$/g,'').replace('class="stage-bar"','class=""');
        }
        else if(d.type==='token'){
          if(ttftMs===null){
            ttftMs=Math.round(performance.now()-t0);
            document.getElementById(lid)?.remove();
            mid='m'+msgIdCounter++;
            document.getElementById('msgs').insertAdjacentHTML('beforeend',`<div class="msg bot" id="${mid}"><div class="av">AI</div><div class="bubble"><span id="${mid}_text"></span></div></div>`);
            el=document.getElementById(mid);
          }
          tokens++;fullAnswer+=d.content;
          document.getElementById(mid+'_text').innerHTML=mdRender(fullAnswer);
        }
        else if(d.type==='sources'){sources=d.sources;window._lastSrc=sources}
        else if(d.type==='summary'){summary=d}
        else if(d.type==='done'){
          summary = {...summary, ...d};
          if(d.low_confidence){lowConfidenceMsg = d.answer; fullAnswer = d.answer || fullAnswer}
          chatHistory.push({query:q,answer:fullAnswer});localStorage.setItem('chatHistory',JSON.stringify(chatHistory.slice(-20)));
        }
        else if(d.type==='error'){if(!el){document.getElementById(lid)?.remove();addBot('Error: '+esc(d.message));document.getElementById('sendBtn').disabled=false;return}fullAnswer+='Error: '+d.message}
      }
      scroll();
    }

    // Low-confidence path: backend already wrote a refusal message into 'token' (or done.answer)
    if(!el && lowConfidenceMsg){
      document.getElementById(lid)?.remove();
      mid='m'+msgIdCounter++;
      document.getElementById('msgs').insertAdjacentHTML('beforeend',`<div class="msg bot" id="${mid}"><div class="av">AI</div><div class="bubble"><span id="${mid}_text">${mdRender(lowConfidenceMsg)}</span></div></div>`);
      el=document.getElementById(mid);
      ttftMs = Math.round(performance.now()-t0);
    }

    // Truly empty stream → friendly message
    if(!el){document.getElementById(lid)?.remove();addBot('No response (likely no relevant data — upload a patent first).');document.getElementById('sendBtn').disabled=false;return}

    const totalMs=Math.round(performance.now()-t0);
    const genMs=Math.max(1,totalMs-(ttftMs||totalMs));
    const tps=tokens?Math.round(tokens*1000/genMs):0;

    // ── Confidence badge (B2) ──
    const conf = detectConfidence(fullAnswer) || (summary.low_confidence ? 'LOW' : null);
    if(conf){
      el.classList.add('has-conf-'+conf);
      const bubble = el.querySelector('.bubble');
      const badge = `<span class="conf-badge conf-${conf}">${conf}</span>`;
      // Place badge before the answer text
      bubble.insertAdjacentHTML('afterbegin', badge);
    }

    // ── Routing reason banner ──
    let routeNote = '';
    if(summary.route_reason && summary.route_reason !== 'user-selected'){
      routeNote = `<div class="stage-bar route-info">Auto-routed: <b>engine=${esc(summary.engine)}</b>, hyde=${esc(summary.use_hyde)} — <i>${esc(summary.route_reason)}</i></div>`;
    }

    // ── Real stage progress bar (B3) ──
    const stageHtml = renderStageBar(liveStages, totalMs);

    // ── Sources + meta + feedback ──
    let sh = stageHtml + routeNote;
    if(sources.length){
      sh += '<div class="src-box"><span class="src-toggle" onclick="this.nextElementSibling.classList.toggle(\'open\')">Sources ('+sources.length+') ▾</span><div class="src-list">';
      sources.forEach((s,i)=>{
        const sc=s.rerank_score!==null&&s.rerank_score!==undefined?s.rerank_score.toFixed(3):(s.score!==undefined?s.score.toFixed(3):'-');
        const snip = (s.snippet || s.text || '').replace(/\s+/g,' ').slice(0,200);
        sh += `<div class="src-item" onclick="pvPage(${inlineJson(s.filename)},${asPage(s.page)},${inlineJson(snip)})"><span>[${i+1}] ${esc(s.source)}</span><span style="color:var(--pri)">${esc(sc)}</span></div>`;
      });
      sh+='</div></div>';
    }
    sh+=`<div class="tts-meta">TTFT ${((ttftMs||0)/1000).toFixed(1)}s · gen ${(genMs/1000).toFixed(1)}s @ ${tps} tok/s · ${tokens} tokens · top-rerank ${summary.top_rerank!==undefined?summary.top_rerank:'?'}</div>`;
    // ── Regenerate buttons (B5) ──
    sh+=`<div class="regen-row">Regenerate:
      <button class="regen-btn" onclick="send(${inlineJson(q)},{engine:'baseline',use_hyde:false})">Baseline</button>
      <button class="regen-btn" onclick="send(${inlineJson(q)},{engine:'m3',use_hyde:false})">m3</button>
      <button class="regen-btn" onclick="send(${inlineJson(q)},{engine:'m3',use_hyde:true})">m3+HyDE</button>
      <button class="regen-btn" onclick="send(${inlineJson(q)},{engine:'auto'})">Auto</button>
    </div>`;
    const queryLogId = Number(summary.query_log_id) || 0;
    sh+=`<div class="fb-row"><button class="fb-btn" onclick="fb(this,1,${queryLogId})" aria-label="Helpful">${ICONS.thumbsUp}</button><button class="fb-btn" onclick="fb(this,-1,${queryLogId})" aria-label="Not helpful">${ICONS.thumbsDown}</button><input class="fb-text" placeholder="Feedback…" onkeydown="if(event.key==='Enter')sendFb(this)"></div>`;
    el.querySelector('.bubble').insertAdjacentHTML('beforeend',sh);
  }catch(e){document.getElementById(lid)?.remove();addBot('Error: '+esc(e.message))}
  document.getElementById('sendBtn').disabled=false;loadSuggestions();
}

// ─── Compare ───
async function runCompare(){
  const a=document.getElementById('cmpA').value,b=document.getElementById('cmpB').value;
  if(!a||!b||a===b){document.getElementById('cmpResult').innerHTML='<p style="color:var(--muted)">Pick two different patents.</p>';return}
  document.getElementById('cmpResult').innerHTML='<p style="color:var(--muted)">Comparing…</p>';
  try{
    const r=await fetch('/api/compare',{method:'POST',headers:{'Content-Type':'application/json',...authHeaders()},body:JSON.stringify({doc_a:a,doc_b:b})});
    const d=await r.json();
    let h=`<table class="cmp-table"><thead><tr><th></th><th>${esc(a)}</th><th>${esc(b)}</th></tr></thead><tbody>`;
    for(const sec of ['bibliographic','abstract','claim_1']){
      h+=`<tr><td>${sec}</td><td>${esc(d.comparison[sec].a)}</td><td>${esc(d.comparison[sec].b)}</td></tr>`;
    }
    h+='</tbody></table>';
    document.getElementById('cmpResult').innerHTML=h;
  }catch(e){document.getElementById('cmpResult').innerHTML='Error: '+esc(e.message)}
}
async function refreshCompareSelectors(){
  try{
    const d=await(await fetch('/api/patents',{headers:authHeaders()})).json();
    const opts=d.patents.map(p=>`<option value="${escAttr(p.doc_number)}">${esc(p.doc_number)} — ${esc(p.title?p.title.slice(0,30):'')}</option>`).join('');
    document.getElementById('cmpA').innerHTML=opts;
    document.getElementById('cmpB').innerHTML=opts;
    if(d.patents.length>1)document.getElementById('cmpB').value=d.patents[1].doc_number;
  }catch{}
}

// ─── Query Coach (corpus-aware suggestion panel) ───
async function openCoach(){
  const overlay = document.getElementById('coachOverlay');
  const list = document.getElementById('coachList');
  const statsEl = document.getElementById('coachStats');
  overlay.classList.add('open');
  list.innerHTML = '<div class="cmdk-empty">Analyzing your corpus…</div>';
  statsEl.textContent = 'Loading…';

  try {
    const r = await fetch('/api/coach', {headers: authHeaders()});
    const d = await r.json();
    if(d.empty){
      list.innerHTML = '<div class="cmdk-empty">'+esc(d.message || 'No data yet')+'</div>';
      statsEl.textContent = '';
      return;
    }
    const s = d.stats || {};
    statsEl.textContent = `${s.total_patents||0} patents · ${s.total_chunks||0} chunks · ${s.section_count||0} IPC sections · ${s.applicant_count||0} applicants`;

    let html = '';

    // Section: Recent
    if(d.recent){
      html += `<div class="cmdk-group-label">Recently added</div>`;
      html += coachItem(`📥 ${d.recent.doc_number}${d.recent.title ? ' — '+d.recent.title.slice(0,40) : ''}`, d.recent.suggested_q);
    }

    // Section: Topics by IPC
    if(d.topics?.length){
      html += `<div class="cmdk-group-label">Browse by topic</div>`;
      d.topics.forEach(t=>{
        const label = `🏷 ${t.label} — ${t.count} patents (e.g., ${t.example_doc})`;
        html += coachItem(label, t.suggested_q);
      });
    }

    // Section: Applicants
    if(d.applicants?.length){
      html += `<div class="cmdk-group-label">By applicant</div>`;
      d.applicants.forEach(a=>{
        const label = `🏢 ${a.name} (${a.count} patent${a.count>1?'s':''})`;
        html += coachItem(label, a.suggested_q);
      });
    }

    // Section: Cross-doc
    if(d.cross_doc){
      html += `<div class="cmdk-group-label">Cross-document comparison</div>`;
      html += coachItem(`⚖️ ${d.cross_doc.doc_a} vs ${d.cross_doc.doc_b} — same IPC section`, d.cross_doc.suggested_q);
    }

    // Section: Refusal demo
    if(d.refusal_demo){
      html += `<div class="cmdk-group-label">Test the refusal mechanism</div>`;
      html += coachItem(`🚦 ${d.refusal_demo.label} — ${d.refusal_demo.expected}`, d.refusal_demo.suggested_q, true);
    }

    list.innerHTML = html;
  } catch(e){
    list.innerHTML = '<div class="cmdk-empty" style="color:var(--c-danger)">Error: '+esc(e.message)+'</div>';
    statsEl.textContent = '';
  }
}

function coachItem(label, query, isDemo){
  const cls = isDemo ? 'cmdk-item' : 'cmdk-item';
  return `<div class="${cls}" onclick="useCoachQuery(${inlineJson(query)})">
    <div style="flex:1;min-width:0">
      <div style="font-size:var(--fs-base);font-weight:var(--fw-medium)">${esc(label)}</div>
      <div style="font-size:var(--fs-xs);color:var(--c-text-muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">→ ${esc(query)}</div>
    </div>
  </div>`;
}

function useCoachQuery(q){
  closeCoach();
  document.getElementById('qi').value = q;
  document.getElementById('qi').focus();
  // optionally auto-send: send();
}

function closeCoach(){
  document.getElementById('coachOverlay').classList.remove('open');
}

// ─── Retrieval funnel viewer ───
function showFunnel(){
  const q = document.getElementById('qi').value || 'antibody for treating hemophilia';
  document.getElementById('funnelQ').value = q;
  document.getElementById('funnelModal').classList.add('open');
  runFunnel();
}
function closeFunnel(){document.getElementById('funnelModal').classList.remove('open')}
async function runFunnel(){
  const q = document.getElementById('funnelQ').value.trim();
  if(!q) return;
  const cols = ['fc1','fc2','fc3','fc4'];
  cols.forEach(id=>document.getElementById(id).innerHTML='<div style="color:var(--muted);padding:10px">encoding…</div>');
  try{
    const url = '/api/retrieve_debug?query=' + encodeURIComponent(q) + '&engine=m3&fetch_k=10';
    const r = await fetch(url, {headers: authHeaders()});
    const d = await r.json();
    const fmt = (rows, scKey) => rows.slice(0,8).map(x=>{
      const sc = (scKey && x[scKey]!==undefined) ? x[scKey] : (x.rerank_score ?? x.rrf_score ?? x.score ?? '');
      return `<div class="row"><span class="lbl">${esc(x.source||'')}</span><span class="sc">${esc(typeof sc==='number'?sc.toFixed(4):sc)}</span><div class="sn">${esc(str(x.snippet||'').slice(0,140))}</div></div>`;
    }).join('') || '<div style="color:var(--muted);padding:10px">no hits</div>';
    document.getElementById('fc1').innerHTML = fmt(d.dense_top || [], 'score');
    document.getElementById('fc2').innerHTML = fmt(d.sparse_top || [], 'score');
    document.getElementById('fc3').innerHTML = fmt(d.fused_top || [], 'rrf_score');
    document.getElementById('fc4').innerHTML = fmt(d.reranked_top || [], 'rerank_score');
  }catch(e){
    cols.forEach(id=>document.getElementById(id).innerHTML='<div style="color:var(--red)">'+esc(e.message)+'</div>');
  }
}

// ─── Quick demo questions ───
const QUICK_QS=[
  'List the key claims of patent TW202401234A',
  'Compare TW202401234A and TW202405678B technically',
  'Which IPC classes are covered by the uploaded patents?',
];
function renderQuickQs(){
  const box=document.getElementById('quickQs');if(!box)return;
  box.innerHTML=QUICK_QS.map((q,i)=>`<button class="sug-btn" data-i="${i}">${q}</button>`).join('');
  box.querySelectorAll('button[data-i]').forEach(b=>b.addEventListener('click',()=>send(QUICK_QS[+b.dataset.i])));
}

// ─── Helpers ───
function addUser(h){document.getElementById('msgs').insertAdjacentHTML('beforeend',`<div class="msg user"><div class="av">U</div><div class="bubble">${h}</div></div>`);scroll()}
function addBot(h){document.getElementById('msgs').insertAdjacentHTML('beforeend',`<div class="msg bot"><div class="av">AI</div><div class="bubble">${h}</div></div>`);scroll()}
function scroll(){const m=document.getElementById('msgs');m.scrollTop=m.scrollHeight}
function str(s){return String(s ?? '')}
function esc(s){return str(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')}

// ─── Markdown renderer (escape-first, then apply a small allowlist) ───
// Supports: **bold**, *italic*, `code`, ```block```, > quote, ###/##/# headings,
// - / 1. lists (single level), [text](url) links, [Source N] citations.
function mdRender(text){
  let s = str(text)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  // Code blocks ```...```
  s = s.replace(/```([\s\S]*?)```/g, (_, code) =>
    `<pre class="md-pre"><code>${code.replace(/\n/g,'\n')}</code></pre>`);

  // Headings — must be at line start
  s = s.replace(/^### (.+)$/gm, '<h3 class="md-h3">$1</h3>');
  s = s.replace(/^## (.+)$/gm,  '<h2 class="md-h2">$1</h2>');
  s = s.replace(/^# (.+)$/gm,   '<h1 class="md-h1">$1</h1>');

  // Block-quote
  s = s.replace(/^> (.+)$/gm, '<blockquote class="md-q">$1</blockquote>');

  // Lists — group consecutive list items into one ul/ol
  s = s.replace(/(?:^[-*] .+(?:\n|$))+/gm, m =>
    '<ul class="md-list">' + m.trim().split(/\n/).map(l=>`<li>${l.replace(/^[-*] /,'')}</li>`).join('') + '</ul>');
  s = s.replace(/(?:^\d+\. .+(?:\n|$))+/gm, m =>
    '<ol class="md-list">' + m.trim().split(/\n/).map(l=>`<li>${l.replace(/^\d+\. /,'')}</li>`).join('') + '</ol>');

  // Inline: bold, italic, code, links
  s = s.replace(/\*\*([^\*\n]+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^\*])\*([^\*\n]+?)\*(?!\*)/g, '$1<em>$2</em>');
  s = s.replace(/`([^`\n]+?)`/g, '<code class="md-code">$1</code>');
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  // Citations [Source N] → clickable
  s = s.replace(/\[Source (\d+)\]/g,
    '<span class="cite-ref" onclick="showSrc($1)">[Source $1]</span>');

  // Soft line breaks (don't break inside block elements)
  s = s.replace(/\n(?!<)/g, '<br>');

  return s;
}
function escAttr(s){return str(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function inlineJson(value){return escAttr(JSON.stringify(value ?? ''))}
function asPage(value){const n=Number(value);return Number.isFinite(n)&&n>0?Math.floor(n):1}

// ─── Feedback ───
function fb(btn,rating,queryLogId){
  btn.classList.add('active');
  const input = btn.parentElement.querySelector('.fb-text');
  input.dataset.rating = String(rating);
  input.dataset.queryLogId = String(queryLogId || 0);
  input.style.display='inline';
  input.focus();
}
function sendFb(inp){
  const rating = Number(inp.dataset.rating || 0);
  const queryLogId = Number(inp.dataset.queryLogId || 0);
  if(!queryLogId || !rating){inp.value='';inp.style.display='none';return}
  fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json',...authHeaders()},body:JSON.stringify({query_log_id:queryLogId,rating,comment:inp.value})})
    .then(r=>{if(r.ok)toast('Thanks for the feedback','success');else toast('Could not send feedback','error')})
    .catch(()=>toast('Could not send feedback','error'));
  inp.value='';inp.style.display='none';
}

// ─── PDF Preview (B1: highlight chunk text) ───
function pvPage(fn,pg,snippet){
  document.getElementById('pvPanel').classList.add('open');
  const page = asPage(pg);
  document.getElementById('pvTitle').textContent=`${fn} — Page ${page}`;
  let body = `<img src="${escAttr(`/api/pdf/${encodeURIComponent(fn)}/page/${page}`)}" onclick="this.classList.toggle('zoomed')">`;
  if(snippet && typeof snippet === 'string' && snippet.trim()){
    body = `<div class="pv-snippet"><b>Cited passage</b>${esc(snippet)}</div>` + body;
  }
  document.getElementById('pvBody').innerHTML = body;
  document.getElementById('pvInfo').textContent=`${fn} | Page ${page}`;
}
function closePv(){document.getElementById('pvPanel').classList.remove('open')}
function showSrc(i){const s=window._lastSrc?.[i-1];if(s)pvPage(s.filename,s.page, s.snippet||s.text||'')}

// ─── Export ───
function exportChat(){
  const data=JSON.stringify({exported:new Date().toISOString(),messages:chatHistory},null,2);
  const blob=new Blob([data],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='chat_export.json';a.click();
}

// ─── Suggestions ───
async function loadSuggestions(){
  try{
    const d=await(await fetch('/api/suggestions',{headers:authHeaders()})).json();
    const suggestions = Array.isArray(d.suggestions) ? d.suggestions : [];
    const box = document.getElementById('sugBox');
    box.innerHTML=suggestions.map((s,i)=>`<button class="sug-btn" data-sug="${i}">${esc(s)}</button>`).join('');
    box.querySelectorAll('button[data-sug]').forEach(b=>b.addEventListener('click',()=>{
      document.getElementById('qi').value=suggestions[Number(b.dataset.sug)] || '';
      send();
    }));
  }catch{}
}

// ─── Pages ───
function showPage(p, navEl){
  document.querySelectorAll('.page').forEach(el=>el.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.remove('active'));
  document.getElementById('pg'+p.charAt(0).toUpperCase()+p.slice(1)).classList.add('active');
  (navEl || Array.from(document.querySelectorAll('.nav-item')).find(el=>el.getAttribute('onclick')?.includes(`'${p}'`)))?.classList.add('active');
  if(p==='patents')loadPatents();
  if(p==='admin')loadAdmin();
  if(p==='compare')refreshCompareSelectors();
}

async function loadPatents(){
  const tbody = document.getElementById('patTbody');
  tbody.innerHTML = skelTableRows(5, 5);
  try{
    const d=await(await fetch('/api/patents',{headers:authHeaders()})).json();
    if(!d.patents?.length){
      tbody.innerHTML = `<tr><td colspan="5" style="padding:0">${emptyState(
        '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/>',
        'No patents indexed',
        'Upload XML files or use scripts/fetch_real_patents.py to ingest TIPO data.'
      )}</td></tr>`;
    } else {
      tbody.innerHTML=d.patents.map(p=>`<tr><td>${esc(p.doc_number)}</td><td>${esc(p.title||'')}</td><td>${esc(p.ipc||'')}</td><td>${esc(p.applicant||'')}</td><td>${esc(p.filename)}</td></tr>`).join('');
    }
  }catch(e){
    tbody.innerHTML = `<tr><td colspan="5" style="padding:0">${emptyState(
      '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
      'Could not load patents',
      esc(e.message || 'Network error')
    )}</td></tr>`;
  }
}

async function loadAdmin(){
  const root = document.getElementById('adminContent');
  root.innerHTML = `<div class="stat-grid" style="grid-template-columns:repeat(4,1fr);gap:var(--sp-3);margin-bottom:var(--sp-5)">
    ${Array.from({length:4},()=>'<div class="skel-card"></div>').join('')}
  </div><div class="skel-card" style="height:240px"></div>`;
  try{
    const s=await(await fetch('/api/admin/stats',{headers:authHeaders()})).json();
    let h=`<div class="stat-grid" style="grid-template-columns:repeat(4,1fr);gap:var(--sp-3);margin-bottom:var(--sp-5)">
      <div class="stat-c"><div class="v">${s.total_chunks||0}</div><div class="l">Chunks</div></div>
      <div class="stat-c"><div class="v">${s.total_documents||0}</div><div class="l">Documents</div></div>
      <div class="stat-c"><div class="v">${s.total_queries||0}</div><div class="l">Queries</div></div>
      <div class="stat-c"><div class="v">${s.avg_latency_ms?(s.avg_latency_ms/1000).toFixed(1)+'s':'-'}</div><div class="l">Avg Latency</div></div>
    </div>`;
    if(s.hot_topics?.length){
      h+='<h3 style="font-size:var(--fs-md);font-weight:var(--fw-semibold);color:var(--c-text);margin:var(--sp-5) 0 var(--sp-3)">Hot Topics</h3><table><thead><tr><th>Query</th><th style="width:80px;text-align:right">Count</th></tr></thead><tbody>';
      s.hot_topics.forEach(t=>{h+=`<tr><td>${esc(t.query)}</td><td style="text-align:right;font-variant-numeric:tabular-nums;font-family:ui-monospace,monospace">${esc(t.count)}</td></tr>`});
      h+='</tbody></table>';
    } else {
      h += emptyState(
        '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
        'No queries yet',
        'Send a few questions in the Chat tab and they will show up here.'
      );
    }
    root.innerHTML=h;
  }catch(e){
    root.innerHTML = emptyState(
      '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
      'Could not load stats',
      esc(e.message || 'Network error')
    );
  }
}

// ─── Refresh ───
async function refreshAll(){if(!token)return;refreshStats();refreshFiles();loadSuggestions()}
async function refreshStats(){
  try{
    const d=await(await fetch('/api/stats',{headers:authHeaders()})).json();
    document.getElementById('sC').textContent=d.total_chunks||0;
    document.getElementById('sD').textContent=d.total_documents||0;
    document.getElementById('sQ').textContent=d.total_queries||0;
    document.getElementById('sL').textContent=d.avg_latency_ms?(d.avg_latency_ms/1000).toFixed(1)+'s':'-';
    if(d.rerank_enabled)document.getElementById('bRerank').style.display='inline';
  }catch{}
}
async function refreshFiles(){
  const fileList = document.getElementById('fileList');
  if(fileList && !fileList.children.length){
    fileList.innerHTML = skelRows(3);
  }
  try{
    const d=await(await fetch('/api/files',{headers:authHeaders()})).json();
    const files = d.files.filter(f=>f.filename!=='.gitkeep');
    if(!files.length){
      fileList.innerHTML = emptyState(
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
        'No files yet',
        'Drop a PDF or XML above to get started.'
      );
    } else {
      fileList.innerHTML = files.map(f=>`<div class="file-item" onclick="pvPage(${inlineJson(f.filename)},1)"><span class="nm">${esc(f.filename)}</span><span class="sz">${esc(f.size_kb)}K</span></div>`).join('');
    }
    // Update scope selector — PDFs by filename, XMLs by doc_number (the latter
    // produces a doc_number_filter so claim/abstract/bibliographic chunks all match)
    const sel=document.getElementById('scopeSel');
    const cur=sel.value;
    let opts='<option value="">All files</option>';
    opts+=d.files.filter(f=>f.ext==='.pdf').map(f=>`<option value="${escAttr(f.filename)}">${esc(f.filename)}</option>`).join('');
    try{
      const pp=await(await fetch('/api/patents',{headers:authHeaders()})).json();
      opts+=pp.patents.map(p=>`<option value="xml:${escAttr(p.doc_number)}">XML: ${esc(p.doc_number)}</option>`).join('');
    }catch{}
    sel.innerHTML=opts;sel.value=cur;
  }catch{}
}

// ─── Command palette (Cmd/Ctrl+K) ───
const CMDK = {
  open: false,
  active: 0,
  filtered: [],
};

function cmdkCommands(){
  return [
    { group:'Navigation', label:'Go to Chat',     shortcut:'G C', icon:'<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>', run:()=>showPage('chat') },
    { group:'Navigation', label:'Go to Patents',  shortcut:'G P', icon:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>', run:()=>showPage('patents') },
    { group:'Navigation', label:'Go to Compare',  shortcut:'G M', icon:'<path d="M16 3h5v5"/><path d="M21 3l-7 7"/><path d="M8 21H3v-5"/><path d="M3 21l7-7"/>', run:()=>showPage('compare') },
    { group:'Navigation', label:'Go to Admin',    shortcut:'G A', icon:'<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>', run:()=>showPage('admin') },

    { group:'Engine', label:'Set engine: Auto (route by query)', icon:'<polyline points="20 6 9 17 4 12"/>', run:()=>setEngine('auto') },
    { group:'Engine', label:'Set engine: Baseline (MiniLM)',     icon:'<circle cx="12" cy="12" r="3"/>', run:()=>setEngine('baseline') },
    { group:'Engine', label:'Set engine: SOTA (bge-m3 + RRF)',   icon:'<polygon points="12 2 15 8 22 9 17 14 18 21 12 18 6 21 7 14 2 9 9 8"/>', run:()=>setEngine('m3') },
    { group:'Engine', label:'Toggle HyDE',                       icon:'<path d="M9 11H1l4-4M5 11l-4-4M19 21h-8M19 21V9M19 21l4-4M19 9l4 4"/>', run:()=>toggleHyde() },
    { group:'Engine', label:'Open retrieval funnel',             icon:'<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>', run:()=>showFunnel() },

    { group:'Appearance', label:'Toggle theme (light/dark)', shortcut:'⇧ T', icon:'<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>', run:()=>toggleTheme() },
    { group:'Appearance', label:'Switch language: English',  icon:'<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>', run:()=>setLang('en') },
    { group:'Appearance', label:'Switch language: 繁體中文', icon:'<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>', run:()=>setLang('zh') },

    { group:'Actions', label:'Focus message input',  shortcut:'⌘ L', icon:'<path d="M3 5h18M3 12h18M3 19h18"/>', run:()=>document.getElementById('qi').focus() },
    { group:'Actions', label:'Export chat history',                  icon:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>', run:()=>exportChat() },
    { group:'Actions', label:'Sign out',                             icon:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>', run:()=>logout() },
  ];
}

function setEngine(v){
  const sel=document.getElementById('engineSel');
  if(!sel) return;
  sel.value=v;
  toast(`Engine → ${sel.options[sel.selectedIndex].text}`,'info');
}
function toggleHyde(){
  const cb=document.getElementById('hydeChk');
  if(!cb) return;
  cb.checked=!cb.checked;
  toast(`HyDE ${cb.checked?'enabled':'disabled'}`,'info');
}

function openCmdk(){
  CMDK.open=true; CMDK.active=0;
  const overlay=document.getElementById('cmdkOverlay');
  const input=document.getElementById('cmdkInput');
  overlay.classList.add('open');
  input.value='';
  renderCmdk('');
  setTimeout(()=>input.focus(),20);
}
function closeCmdk(){
  CMDK.open=false;
  document.getElementById('cmdkOverlay').classList.remove('open');
}
function renderCmdk(query){
  const all=cmdkCommands();
  const q=query.trim().toLowerCase();
  const filtered = !q ? all : all.filter(c=>c.label.toLowerCase().includes(q) || c.group.toLowerCase().includes(q));
  CMDK.filtered=filtered;
  if(CMDK.active >= filtered.length) CMDK.active = Math.max(0, filtered.length-1);

  const list=document.getElementById('cmdkList');
  if(!filtered.length){
    list.innerHTML='<div class="cmdk-empty">No commands match "'+esc(query)+'"</div>';
    return;
  }
  let lastGroup=null;
  list.innerHTML = filtered.map((c,i)=>{
    let groupHeader='';
    if(c.group !== lastGroup){
      groupHeader = `<div class="cmdk-group-label">${esc(c.group)}</div>`;
      lastGroup = c.group;
    }
    const sc = c.shortcut ? `<span class="cmdk-shortcut">${c.shortcut.split(' ').map(k=>`<span class="kbd">${esc(k)}</span>`).join('')}</span>` : '';
    return groupHeader +
      `<div class="cmdk-item ${i===CMDK.active?'cmdk-active':''}" data-i="${i}" onclick="cmdkRun(${i})" onmouseenter="cmdkSetActive(${i})">
         <svg class="cmdk-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${c.icon}</svg>
         <span class="cmdk-text">${esc(c.label)}</span>${sc}
       </div>`;
  }).join('');
}
function cmdkSetActive(i){
  CMDK.active=i;
  document.querySelectorAll('#cmdkList .cmdk-item').forEach((el,idx)=>el.classList.toggle('cmdk-active', idx===i));
}
function cmdkRun(i){
  const cmd=CMDK.filtered[i];
  if(!cmd) return;
  closeCmdk();
  setTimeout(()=>cmd.run(),20);
}

document.addEventListener('keydown', e=>{
  // Cmd/Ctrl+K → open palette
  if((e.metaKey||e.ctrlKey) && !e.shiftKey && e.key.toLowerCase()==='k'){
    e.preventDefault();
    if(CMDK.open) closeCmdk(); else openCmdk();
    return;
  }
  // Cmd/Ctrl+L → focus input
  if((e.metaKey||e.ctrlKey) && e.key.toLowerCase()==='l'){
    e.preventDefault();
    document.getElementById('qi')?.focus();
    return;
  }
  // Inside palette: Up/Down/Enter/Esc
  if(CMDK.open){
    if(e.key==='Escape'){ e.preventDefault(); closeCmdk(); }
    else if(e.key==='ArrowDown'){ e.preventDefault(); cmdkSetActive(Math.min(CMDK.filtered.length-1, CMDK.active+1)); ensureCmdkVisible(); }
    else if(e.key==='ArrowUp'){   e.preventDefault(); cmdkSetActive(Math.max(0, CMDK.active-1)); ensureCmdkVisible(); }
    else if(e.key==='Enter'){     e.preventDefault(); cmdkRun(CMDK.active); }
  }
});
function ensureCmdkVisible(){
  const el=document.querySelector('#cmdkList .cmdk-active');
  if(el) el.scrollIntoView({block:'nearest'});
}
document.addEventListener('input', e=>{
  if(e.target?.id === 'cmdkInput') renderCmdk(e.target.value);
});

// Restore chat history
if(chatHistory.length){chatHistory.forEach(h=>{addUser(esc(h.query));addBot(esc(h.answer))})}
renderQuickQs();
if(token)refreshAll();else document.getElementById('loginOverlay').style.display='flex';
setInterval(()=>{if(token)refreshStats()},30000);
