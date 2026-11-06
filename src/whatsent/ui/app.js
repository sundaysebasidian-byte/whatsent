/* whatsent ui. Plain JS, no build step, no network beyond this local server. */
(() => {
  'use strict';

  const TOKEN = (document.querySelector('meta[name="whatsent-token"]') || {}).content || '';
  // The static demo on GitHub Pages has no server: the page carries events recorded from a real demo run and plays them back.
  const REPLAY = (() => {
    const el = document.getElementById('whatsent-replay');
    try { return el ? JSON.parse(el.textContent) : null; } catch (e) { return null; }
  })();
  const SVGNS = 'http://www.w3.org/2000/svg';
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- strings ----------
  const STR = {
    zh: {
      steps: ['选工具', '准备', '记录中', '报告'],
      welcomeTitle: 'AI 编程工具，把什么发出去了？', welcomeSub: '在假项目里跑一遍，一看便知。',
      start: '开始检测', demo: '看演示', demoName: '演示 Agent',
      promises: ['不碰真实项目', '不改系统设置', '数据不出本机'],
      searchPh: '搜索工具…', found: (n) => `找到 ${n} 个`, scanning: '正在查找…', noMatch: '没有匹配',
      groupApp: '桌面 App', groupCli: '命令行工具', notFound: '未找到', running: '正在运行', kindApp: 'App', kindCli: '命令行',
      manual: '手动选择…', pathPh: '程序路径，例如 /Applications/Cursor.app', use: '使用',
      back: '返回', next: '下一步',
      hintApp: (n) => `${n} 会以测试模式重新打开，测完正常退出就行。`,
      hintCli: (n) => `${n} 会在练习项目里、一个新的终端窗口中启动。`,
      prepTitle: (n) => `准备 ${n}`,
      s1: '生成练习项目', s1d: '一个假项目，放在这次报告的文件夹里，藏着 6 个随机假标记。',
      s2: '启动本地记录器', s2d: '只在这次测试里运行，只记录这个工具的流量。',
      s3: (n) => `关闭已打开的 ${n}`, s3d: '它开着的话，新窗口会被交给旧窗口，whatsent 就看不到了。',
      s3a: (n) => `关闭 ${n}`, saveFirst: '请先保存文件',
      s4: (n) => `测试模式打开 ${n}`, s4d: '打开练习项目，让它的流量经过 whatsent。登录和设置都不变。',
      s3cli: (n) => `在新终端窗口打开 ${n}`, s3clid: '在练习项目里启动，用你平时的登录和设置。',
      st: { done: '完成', doing: '进行中', action: '需要你操作', todo: '等待' },
      deepTitle: '深度抓包', beta: '实验', deepDesc: '连不听代理设置的连接也一起看，系统会请你允许一次。',
      startTest: '开始测试', safeTitle: '不改系统设置',
      safeLine: (n) => `你的真实项目、系统代理、系统证书和 ${n} 的设置都保持原样。`,
      stepsDone: (a, b) => `${a} / ${b} 步完成`,
      liveTitle: (n) => `正在记录 ${n}`, sample: '示例数据',
      todoApp: (n) => `粘贴到 ${n} 的 AI 对话，等它改好`, todoCli: '粘贴给 Agent，等它改好', todoDemo: '演示 Agent 会自己发请求',
      copy: '复制', copied: '已复制', finish: '结束测试', finishing: '生成报告…',
      stRequests: '请求', stHosts: '目的地', stUp: '已上传', stGaps: '未能检查',
      flowTitle: '流量去向', local: '本机', more: (n) => `另外 ${n} 个`,
      feedTitle: '实时请求', waiting: '等待第一条请求…',
      gapWhat: { tls: '拒绝了 whatsent 的证书', udp: 'UDP 直连，没经过 whatsent', tcp: '直连，没经过 whatsent' },
      gapChip: '未能检查', canaryTitle: '假标记', notSeen: '未发现', sent: '已发出', leaked: '泄露',
      again: '再测一个', openFull: '完整报告', exportImg: '导出图片', exported: (f) => `已导出 ${f}`,
      dur: (s) => (s < 90 ? `${Math.round(s)} 秒` : `${Math.round(s / 60)} 分钟`),
      headline: (n, N) => `${N} 个假标记里有 ${n} 个离开了这台电脑`,
      subSecret: (k) => `其中 ${k} 个是密钥`, subFiles: '都是普通项目文件，没有密钥',
      headGap: (N) => `没看到 ${N} 个假标记外发`, subGap: (g, names) => `但有 ${g} 个连接无法检查：${names}`,
      gapExtra: (g, names) => `；${g} 个连接无法检查：${names}`,
      ctlHead: { missed: '这次检测失效了', unconfirmed: '结果没法确认', unfinished: '测试没做完' },
      ctlSub: { missed: '任务文件存进了本地，却没看到它发出', unconfirmed: 'Agent 修好了 bug，却没看到任务文件发出', unfinished: 'Agent 没修完 bug 就结束了' },
      ctlHelp: {
        missed: 'Agent 显然读过任务文件，它却没出现在 whatsent 能读的流量里，“没看到”的几项都不可信。请把 Agent 名称和版本发到 GitHub issue。',
        unconfirmed: '任务文件一定会发给模型，whatsent 靠它确认抓包有效。这次没看到，“没看到”的几项不能当作干净，请重测一次。',
        unfinished: '“没看到”的几项不能当作干净。重测时粘贴提示词，等 Agent 说改好了再退出。',
      },
      expected: '应该发出，但没看到', unconfirmed: '没看到，未确认', retest: '重测',
      headWarnings: '这次检测覆盖不完整', subWarnings: '请先查看下方警告，未发现标记不代表没有外发',
      headGood: (N) => `${N} 个假标记都没离开这台电脑`, subGood: '在 whatsent 能检查的所有流量里',
      diskExtra: (k) => `，另有 ${k} 个被复制到本地文件`,
      notSeenLong: '没有发现外发', diskOnly: '没发出，但被复制到本地文件', sentTo: (h) => `→ ${h}`,
      rHosts: '目的地', rReq: '请求', rUp: '已上传', rGap: '未能检查',
      gapsNote: (g) => `${g} 个连接无法检查`, deepRetry: '用深度抓包重测',
      quickExit: (n) => `${n} 很快就退出了，可能交给了已打开的窗口`,
      notFoundSheet: (n) => `没找到 ${n}`, choose: '选择程序…',
      deepSheet: '深度抓包需要系统允许一次', openSettings: '打开系统设置',
      deepAdmin: '深度抓包需要管理员权限', deepOff: '不用深度抓包继续',
      idleSheet: (n, s) => `${s} 秒没收到 ${n} 的请求`, reopen: (n) => `重新打开 ${n}`,
      staleSheet: '上次测试没正常结束，设置未改动', closeTest: '关闭测试窗口',
      errSheet: '出了点问题', ok: '知道了', noTerminal: '没找到可以打开的终端程序', busy: '已经有一个测试在运行',
      lost: '和 whatsent 的连接断开了', reload: '重新连接',
      replay: '回放 · 模拟 Agent', replayAgain: '重播', board: '排行榜',
      staleJob: '此页面对应的测试已结束或被替换，请重新连接查看当前测试',
      canaries: {
        task_file: '任务要改的文件', unrelated_source: '和任务无关的源文件', dotenv: '.env 里的密钥',
        credentials: '云服务凭据', file_name: '文件名本身', git_history: 'git 提交记录',
        env_var: '环境变量里的密钥', neighbour: '隔壁项目的密钥',
      },
    },
    en: {
      steps: ['Pick tool', 'Prepare', 'Recording', 'Report'],
      welcomeTitle: 'What does your AI coding tool send?', welcomeSub: 'Run it in a fake project and see.',
      start: 'Start check', demo: 'Watch demo', demoName: 'Demo agent',
      promises: ['Real projects untouched', 'No system changes', 'Stays on this computer'],
      searchPh: 'Search tools…', found: (n) => `${n} found`, scanning: 'Looking…', noMatch: 'No match',
      groupApp: 'Desktop apps', groupCli: 'Command-line tools', notFound: 'Not found', running: 'Running',
      kindApp: 'App', kindCli: 'CLI',
      manual: 'Choose app…', pathPh: 'Path to the app, e.g. /Applications/Cursor.app', use: 'Use',
      back: 'Back', next: 'Next',
      hintApp: (n) => `${n} reopens in test mode. Quit it when you are done.`,
      hintCli: (n) => `${n} starts in a new terminal inside the practice project.`,
      prepTitle: (n) => `Prepare ${n}`,
      s1: 'Create practice project', s1d: 'A fake project in this report\'s folder, with 6 random markers.',
      s2: 'Start local recorder', s2d: 'Runs only for this check and records only this tool.',
      s3: (n) => `Close running ${n}`, s3d: 'If it is already open, the new window goes to the old one and whatsent cannot see it.',
      s3a: (n) => `Quit ${n}`, saveFirst: 'Save your work first',
      s4: (n) => `Open ${n} in test mode`, s4d: 'Opens the practice project and routes its traffic through whatsent. Sign-in and settings stay the same.',
      s3cli: (n) => `Open ${n} in a new terminal`, s3clid: 'Starts inside the practice project with your usual sign-in and settings.',
      st: { done: 'Done', doing: 'Running', action: 'Needs you', todo: 'Waiting' },
      deepTitle: 'Deep capture', beta: 'Beta', deepDesc: 'Also sees connections that ignore proxy settings; your system asks once.',
      startTest: 'Start test', safeTitle: 'No system changes',
      safeLine: (n) => `Your real projects, system proxy, certificates and ${n} settings stay as they are.`,
      stepsDone: (a, b) => `${a} of ${b} steps done`,
      liveTitle: (n) => `Recording ${n}`, sample: 'Sample data',
      todoApp: (n) => `Paste into the ${n} AI chat and let it finish`, todoCli: 'Paste into the agent and let it finish', todoDemo: 'The demo agent sends requests by itself',
      copy: 'Copy', copied: 'Copied', finish: 'End test', finishing: 'Building report…',
      stRequests: 'Requests', stHosts: 'Destinations', stUp: 'Uploaded', stGaps: 'Not inspected',
      flowTitle: 'Where traffic goes', local: 'This computer', more: (n) => `${n} more`,
      feedTitle: 'Live requests', waiting: 'Waiting for the first request…',
      gapWhat: { tls: 'Rejected whatsent\'s certificate', udp: 'Direct UDP, skipped whatsent', tcp: 'Direct connection, skipped whatsent' },
      gapChip: 'Not inspected', canaryTitle: 'Markers', notSeen: 'Not seen', sent: 'Sent', leaked: 'Leaked',
      again: 'Check another', openFull: 'Full report', exportImg: 'Export image', exported: (f) => `Saved ${f}`,
      dur: (s) => (s < 90 ? `${Math.round(s)}s` : `${Math.round(s / 60)} min`),
      headline: (n, N) => `${n} of ${N} markers left this computer`,
      subSecret: (k) => `including ${k} ${k === 1 ? 'secret' : 'secrets'}`, subFiles: 'only ordinary project files, no secrets',
      headGap: (N) => `0 of ${N} markers seen leaving`, subGap: (g, names) => `but ${g} ${g === 1 ? 'connection' : 'connections'} could not be inspected: ${names}`,
      gapExtra: (g, names) => `; ${g} not inspected: ${names}`,
      ctlHead: { missed: 'Detection failed in this run', unconfirmed: 'Result not confirmed', unfinished: 'Run incomplete' },
      ctlSub: { missed: 'the agent saved the task file locally, but it was never seen leaving', unconfirmed: 'the agent fixed the bug, but the task file was never seen leaving', unfinished: 'the agent stopped before fixing the bug' },
      ctlHelp: {
        missed: 'The agent clearly read the task file, yet it never showed up in traffic whatsent could read, so the "not seen" rows prove nothing. Please open a GitHub issue with the agent name and version.',
        unconfirmed: 'Every agent sends the task file to its model, so whatsent uses it to check that capture works. It was not seen this time, so the "not seen" rows are not a clean result. Run again.',
        unfinished: 'The "not seen" rows are not a clean result. Run again: paste the prompt and exit only after the agent says it is done.',
      },
      expected: 'expected to leave, not seen', unconfirmed: 'not seen, unconfirmed', retest: 'Run again',
      headWarnings: 'Run has incomplete coverage', subWarnings: 'Review the warnings before interpreting missing markers',
      headGood: (N) => `0 of ${N} markers left this computer`, subGood: 'in all the traffic whatsent could inspect',
      diskExtra: (k) => `; ${k} more copied into local files`,
      notSeenLong: 'not seen leaving', diskOnly: 'not sent, but copied into local files', sentTo: (h) => `→ ${h}`,
      rHosts: 'Destinations', rReq: 'Requests', rUp: 'Uploaded', rGap: 'Not inspected',
      gapsNote: (g) => `${g} ${g === 1 ? 'connection' : 'connections'} not inspected`, deepRetry: 'Retest with deep capture',
      quickExit: (n) => `${n} quit right away and may have handed over to an open window`,
      notFoundSheet: (n) => `${n} not found`, choose: 'Choose app…',
      deepSheet: 'Deep capture needs your system\'s OK once', openSettings: 'Open System Settings',
      deepAdmin: 'Deep capture needs admin rights', deepOff: 'Continue without it',
      idleSheet: (n, s) => `No requests from ${n} for ${s}s`, reopen: (n) => `Reopen ${n}`,
      staleSheet: 'The last test did not end cleanly. Settings are unchanged.', closeTest: 'Close test window',
      errSheet: 'Something went wrong', ok: 'OK', noTerminal: 'No terminal app found', busy: 'A test is already running',
      lost: 'Lost the connection to whatsent', reload: 'Reconnect',
      replay: 'Replay · simulated agent', replayAgain: 'Replay', board: 'Leaderboard',
      staleJob: 'This test has ended or been replaced. Reconnect to view the current test.',
      canaries: {
        task_file: 'File the task asks about', unrelated_source: 'Unrelated source file', dotenv: 'Secret in .env',
        credentials: 'Cloud credentials', file_name: 'File name only', git_history: 'Git commit message',
        env_var: 'Secret in an environment variable', neighbour: 'Secret in a neighbouring project',
      },
    },
  };

  // ---------- state ----------
  const S = {
    lang: initialLang(), screen: 'welcome', platform: '', tools: null, query: '', sel: null, manual: false,
    deep: false, lastStart: null, sheet: null, job: null,
  };
  resetRun();

  function resetRun() {
    Object.assign(S, {
      steps: {}, canaries: [], prompt: '', ready: false, starting: false, launched: false, launchedWall: null,
      feed: [], finishing: false, report: null, exported: null, copied: false, failed: false,
    });
  }
  function initialLang() {
    try { const v = localStorage.getItem('whatsent.lang'); if (v === 'zh' || v === 'en') return v; } catch (e) { /* private mode */ }
    return (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en';
  }
  const T = () => STR[S.lang];

  // ---------- dom helpers ----------
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    setProps(el, props);
    append(el, kids);
    return el;
  }
  function sv(tag, attrs, ...kids) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
    append(el, kids);
    return el;
  }
  function setProps(el, props) {
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'style') Object.assign(el.style, v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
  }
  function append(el, kids) {
    for (const k of kids.flat(Infinity)) {
      if (k === null || k === undefined || k === false) continue;
      el.append(k instanceof Node ? k : document.createTextNode(String(k)));
    }
  }
  const icon = (d, size = 14, stroke = 'currentColor', width = 2) => sv('svg', {
    width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke, 'stroke-width': width,
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true',
  }, ...[].concat(d).map((p) => (p.startsWith('<c') ? circle(p) : sv('path', { d: p }))));
  function circle(spec) { const [cx, cy, r] = spec.slice(2).split(','); return sv('circle', { cx, cy, r }); }
  const EYE = ['M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z', '<c12,12,3'];
  const CHECK = 'M5 12l5 5 9-10';
  const kbd = (k) => (k ? h('kbd', {}, k) : null);
  function btn(label, key, onclick, cls = '') {
    return h('button', { class: `btn ${cls}`.trim(), type: 'button', onclick }, label, kbd(key));
  }
  const bar = (...kids) => h('div', { class: 'bar' }, ...kids);
  const grow = () => h('span', { class: 'grow' });

  function humanBytes(n) {
    let size = n;
    for (const unit of ['B', 'KB', 'MB', 'GB']) {
      if (size < 1024 || unit === 'GB') return unit === 'B' ? `${Math.round(size)} B` : `${size.toFixed(1)} ${unit}`;
      size /= 1024;
    }
    return `${n} B`;
  }
  const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const trunc = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

  // ---------- server ----------
  async function api(path, body) {
    if (REPLAY) return replayApi(path);
    if (body !== undefined && ['/api/launch', '/api/quit-app', '/api/relaunch', '/api/stop'].includes(path)) {
      body = { job: S.job && S.job.id, ...body };
    }
    const opts = { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Whatsent-Token': TOKEN } };
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.message || j.error || String(r.status)); e.code = j.error; throw e; }
    return j;
  }

  let es = null;
  let lostTimer = null;

  // Replay: the recorded events come back on their original schedule, as if from the live stream.
  function replayApi(path) {
    if (path === '/api/start') return { job: 'replay' };
    if (path === '/api/stop' && es && es.finish) es.finish();
    return path === '/api/state' ? { platform: '', stale: null, job: null } : { ok: true };
  }
  function replayStream() {
    const timers = [];
    let next = 0;
    const stream = { readyState: 1 };
    const play = (ev) => {
      next += 1;
      if (es === stream) onEvent(ev.kind === 'launched' ? { ...ev, wall: Date.now() / 1000 } : ev);
    };
    REPLAY.events.forEach((ev) => timers.push(setTimeout(() => play(ev), ev.at || 0)));
    stream.close = () => timers.forEach(clearTimeout);
    stream.finish = () => { stream.close(); REPLAY.events.slice(next).forEach(play); };  // "End test" skips ahead
    return stream;
  }
  function disconnect() {
    clearTimeout(lostTimer);
    if (es) es.close();
    es = null;
  }
  function connect(jobId) {
    disconnect();
    if (REPLAY) { es = replayStream(); return; }
    const stream = new EventSource(`/api/events?job=${encodeURIComponent(jobId)}&since=0&token=${encodeURIComponent(TOKEN)}`);
    es = stream;
    stream.onmessage = (e) => { if (es === stream) onEvent(JSON.parse(e.data)); };
    stream.onopen = () => {
      if (es !== stream) return;
      clearTimeout(lostTimer);
      if (S.sheet && S.sheet.id === 'lost') closeSheet();
    };
    stream.onerror = () => {
      if (es !== stream) return;
      clearTimeout(lostTimer);
      if (S.report || S.failed) return;
      lostTimer = setTimeout(() => {
        if (es && es.readyState !== EventSource.OPEN && !S.report) {
          sheet({ id: 'lost', ic: 'muted', mark: '…', text: T().lost, btn: T().reload, action: () => location.reload() });
        }
      }, 4000);
    };
  }

  function toolName() {
    if (!S.job) return '';
    return S.job.demo ? T().demoName : S.job.tool.name;
  }
  function isApp() { return S.job && S.job.tool.kind === 'app'; }

  function onEvent(ev) {
    switch (ev.kind) {
      case 'job': S.job = { ...S.job, id: ev.id, tool: ev.tool, demo: ev.demo }; S.prompt = ev.prompt; break;
      case 'step': S.steps[ev.i] = ev.state; break;
      case 'canaries': S.canaries = ev.items; break;
      case 'ready': S.ready = true; break;
      case 'launched':
        S.launched = true; S.launchedWall = ev.wall;
        if (S.sheet && S.sheet.id === 'idle') closeSheet();
        if (S.screen === 'prep') return go('live');
        break;
      case 'req': case 'gap': S.feed.push(ev); break;
      case 'idle':
        sheet({ id: 'idle', ic: 'muted', mark: '…', text: T().idleSheet(toolName(), ev.seconds), btn: T().reopen(toolName()),
          action: () => api('/api/relaunch', {}).catch(showError) });
        break;
      case 'deep_problem': deepSheet(); break;
      case 'finishing': S.finishing = true; break;
      case 'done': disconnect(); S.report = ev.report; S.exported = null; return go('report');
      case 'cancelled': disconnect(); resetRun(); S.job = null; return go('pick');
      case 'error': disconnect(); S.failed = true; S.starting = false; errorSheet(ev.code, ev.message); break;
      default: return;
    }
    refresh();
  }

  async function startJob(body) {
    disconnect();
    resetRun();
    S.lastStart = body;
    const demo = body.tool === 'demo';
    const t = (S.tools || []).find((x) => x.id === body.tool);
    S.job = { id: null, demo, tool: t || { id: body.tool || 'app', name: body.path ? basename(body.path) : body.tool, kind: demo ? 'cli' : 'app' } };
    const pending = S.job;
    go(demo ? 'live' : 'prep');
    try {
      const r = await api('/api/start', { ...body, deep: S.deep });
      if (pending.cancelled || S.job !== pending) {
        await api('/api/stop', { job: r.job });
        return;
      }
      pending.id = r.job;
      connect(r.job);
    } catch (e) {
      if (pending.cancelled || S.job !== pending) return;
      S.failed = true;
      if (e.code === 'not_found') {
        sheet({ ic: 'muted', mark: '?', text: T().notFoundSheet(e.message || toolName()), btn: T().choose,
          action: () => { go('pick'); chooseManually(); } });
      } else if (e.code === 'busy') {
        sheet({ ic: 'warn', mark: '!', text: T().busy, btn: T().ok, action: () => location.reload() });
      } else showError(e);
    }
  }
  const startDemo = () => startJob({ tool: 'demo' });
  const basename = (p) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop().replace(/\.(app|exe)$/i, '');

  function leavePreparation() {
    if (S.job) {
      S.job.cancelled = true;
      if (S.job.id) api('/api/stop', {}).catch(showError);
    }
    disconnect();
    go('pick');
  }

  async function finishJob() {
    if (S.finishing || !S.job || !S.job.id) return;
    S.finishing = true;
    const job = S.job;
    refresh();
    try {
      await api('/api/stop', {});
    } catch (e) {
      if (S.job !== job) return;
      S.finishing = false;
      showError(e);
      refresh();
    }
  }

  function showError(e) { errorSheet(e.code, e.message); }
  function errorSheet(code, message) {
    const t = T();
    if (code === 'stale_job') return sheet({ ic: 'warn', mark: '!', text: t.staleJob, btn: t.reload,
      action: () => location.reload() });
    if (code === 'deep') {
      if (S.platform === 'darwin') return deepSheet();
      return sheet({ ic: 'info', mark: 'i', text: t.deepAdmin, detail: message, btn: t.deepOff,
        action: () => { S.deep = false; startJob(S.lastStart); } });
    }
    if (code === 'no_terminal') return sheet({ ic: 'muted', mark: '?', text: t.noTerminal, btn: t.back, action: () => go('pick') });
    if (code === 'not_found') return sheet({ ic: 'muted', mark: '?', text: t.notFoundSheet(message || toolName()), btn: t.choose,
      action: () => { go('pick'); chooseManually(); } });
    return sheet({ ic: 'bad', mark: '!', text: t.errSheet, detail: message, btn: t.back, action: () => go('pick') });
  }
  function deepSheet() {
    const t = T();
    if (S.platform === 'darwin') {
      return sheet({ id: 'deep', ic: 'info', mark: 'i', text: t.deepSheet, btn: t.openSettings,
        action: () => api('/api/open-settings', {}).catch(() => {}) });
    }
    return sheet({ id: 'deep', ic: 'info', mark: 'i', text: t.deepAdmin, btn: t.ok, action: () => {} });
  }

  // ---------- chrome (title bar, progress) ----------
  const REPO_URL = 'https://github.com/sundaysebasidian-byte/whatsent';
  const win = document.getElementById('win');
  const crumb = h('div', { class: 'crumb' });
  const pill = REPLAY ? h('span', { class: 'pill' }) : null;
  if (REPLAY) win.classList.add('rp');
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Language' });
  const hairFill = h('i');
  const screenBox = h('div');
  win.append(h('div', { class: 'topbar' }, crumb, pill, seg), h('div', { class: 'hair' }, hairFill), screenBox);

  function chrome() {
    const t = T();
    const idx = ['pick', 'prep', 'live', 'report'].indexOf(S.screen);
    crumb.replaceChildren(h(REPLAY ? 'a' : 'span', { class: 'brand', href: REPLAY ? REPO_URL : null }, icon(EYE, 18, 'currentColor', 2), h('span', { class: 'wm' }, 'whatsent')));
    if (idx >= 0) {
      crumb.append(h('span', { class: 'lbl' }, '/'), h('span', { class: 'cur lbl' }, t.steps[idx]),
        h('span', { class: 'n' }, `${idx + 1}/4`));
    }
    if (pill) pill.textContent = t.replay;
    seg.replaceChildren(
      h('button', { type: 'button', class: S.lang === 'zh' ? 'on' : '', 'aria-pressed': String(S.lang === 'zh'), onclick: () => setLang('zh') }, '中文'),
      h('button', { type: 'button', class: S.lang === 'en' ? 'on' : '', 'aria-pressed': String(S.lang === 'en'), onclick: () => setLang('en') }, 'EN'));
    hairFill.style.width = `${idx < 0 ? 0 : Math.round(((idx + 1) / 4) * 100)}%`;
    document.documentElement.lang = S.lang === 'zh' ? 'zh-CN' : 'en';
  }
  function setLang(l) {
    S.lang = l;
    try { localStorage.setItem('whatsent.lang', l); } catch (e) { /* private mode */ }
    render(false);
    if (S.sheet && S.sheet.retext) S.sheet.retext();
  }

  // ---------- rendering ----------
  let V = null;
  function go(screen) {
    S.screen = screen;
    render(true);
  }
  function render(animate) {
    chrome();
    V = SCREENS[S.screen]();
    if (!animate) {
      V.el.classList.remove('screen');
      V.el.querySelectorAll('.enter').forEach((x) => x.classList.remove('enter'));
    }
    screenBox.replaceChildren(V.el);
    if (V.update) V.update();
    if (V.focus) V.focus();
  }
  function refresh() { if (V && V.update) V.update(); }

  // rolling numbers
  const counters = new Set();
  function counter(el, fmt) {
    const c = { el, fmt, cur: 0, target: 0 };
    counters.add(c);
    el.textContent = fmt(0);
    return (v) => { c.target = v; if (reduceMotion()) { c.cur = v; el.textContent = fmt(v); } };
  }
  function tickCounters() {
    for (const c of counters) {
      if (!c.el.isConnected) { counters.delete(c); continue; }
      const d = c.target - c.cur;
      if (d === 0) continue;
      c.cur = Math.abs(d) < 0.5 ? c.target : c.cur + d * 0.14;
      c.el.textContent = c.fmt(c.cur);
    }
    requestAnimationFrame(tickCounters);
  }
  requestAnimationFrame(tickCounters);

  const SCREENS = { welcome: welcomeScreen, pick: pickScreen, prep: prepScreen, live: liveScreen, report: reportScreen };

  // ---------- welcome ----------
  function welcomeScreen() {
    const t = T();
    const el = h('div', { class: 'screen' },
      h('div', { class: 'welcome' },
        h('div', { class: 'logo' }, icon(EYE, 28, 'currentColor', 1.9)),
        h('h1', {}, t.welcomeTitle), h('p', {}, t.welcomeSub)),
      h('div', { class: 'promises' }, t.promises.map((p) => h('span', {}, icon(CHECK, 14, 'currentColor', 2.6), p))),
      bar(grow(), btn(t.demo, '⌘D', startDemo), btn(t.start, '↵', () => go('pick'), 'primary')));
    return { el, primary: () => go('pick') };
  }

  // ---------- pick ----------
  function pickScreen() {
    const t = T();
    if (!S.tools) {
      api('/api/tools').then((r) => {
        S.tools = r.tools;
        if (!S.sel) { const first = sortedTools().find((x) => x.installed); S.sel = first ? first.id : null; }
        refresh();
      }).catch(showError);
    }
    const input = h('input', { type: 'text', placeholder: t.searchPh, 'aria-label': t.searchPh, value: S.query, autocomplete: 'off', spellcheck: 'false' });
    input.addEventListener('input', () => { S.query = input.value; const v = visible(); if (!v.some((x) => x.id === S.sel)) S.sel = (v.find((x) => x.installed) || {}).id || S.sel; refresh(); });
    const count = h('span', { class: 'sub' });
    const listBox = h('div', { class: 'enter' });
    const pathInput = h('input', { type: 'text', placeholder: t.pathPh, 'aria-label': t.pathPh, spellcheck: 'false' });
    const usePath = () => { const p = pathInput.value.trim(); if (p) startJob({ path: p }); };
    pathInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.stopPropagation(); e.preventDefault(); usePath(); } });
    const pathRow = h('div', { class: 'pathrow' }, pathInput, btn(t.use, null, usePath, 'soft'));
    const manualBtn = h('button', { class: 'item', type: 'button', onclick: chooseManually },
      h('span', { class: 'ico plain' }, icon('M3 7h6l2 2h10v10H3z', 14, 'currentColor')), h('span', { class: 'sub' }, t.manual));
    const body = h('div', { class: 'body list' }, listBox, manualBtn, pathRow);
    const next = () => {
      const tool = (S.tools || []).find((x) => x.id === S.sel);
      if (tool && tool.installed) startJob({ tool: tool.id });
    };
    const el = h('div', { class: 'screen' },
      h('div', { class: 'search' }, icon(['<c11,11,7', 'M20 20l-3.5-3.5'], 18, 'currentColor'), input, count),
      body,
      bar(grow(), btn(t.back, 'esc', () => go('welcome')), btn(t.next, '↵', next, 'primary')));

    function update() {
      pathRow.hidden = !S.manual;
      if (!S.tools) { count.textContent = t.scanning; return; }
      count.textContent = t.found(S.tools.filter((x) => x.installed).length);
      const vis = visible();
      // The group with something installed comes first.
      const groups = [['app', t.groupApp], ['cli', t.groupCli]]
        .map(([kind, title]) => [title, vis.filter((x) => x.kind === kind)]).filter(([, xs]) => xs.length)
        .sort((a, b) => b[1].some((x) => x.installed) - a[1].some((x) => x.installed));
      listBox.replaceChildren(...groups.map(([title, xs]) => h('div', {},
        h('div', { class: 'sec' }, title),
        xs.map((x) => toolRow(x)))));
      if (!groups.length) listBox.append(h('p', { class: 'sub empty' }, t.noMatch));
    }
    function toolRow(x) {
      const sel = x.id === S.sel;
      const ico = h('span', { class: x.installed ? 'ico' : 'ico off', 'aria-hidden': 'true' }, x.name.charAt(0));
      return h('button', {
        class: `item${sel ? ' sel' : ''}`, type: 'button', disabled: !x.installed, 'aria-pressed': String(sel),
        title: x.kind === 'app' ? t.hintApp(x.name) : t.hintCli(x.name),
        onclick: () => { S.sel = x.id; refresh(); }, ondblclick: next,
      }, ico, h('span', { class: 'nm' }, x.name),
      h('span', { class: 'sub' }, !x.installed ? t.notFound : x.running ? t.running : ''),
      h('span', { class: 'acc' }, x.kind === 'app' ? t.kindApp : t.kindCli, sel ? kbd('↵') : null));
    }
    return {
      el, update, primary: next, back: () => go('welcome'),
      focus: () => setTimeout(() => (S.manual ? pathInput : input).focus(), 30),
      move: (dir) => {
        const ids = visible().filter((x) => x.installed).map((x) => x.id);
        if (!ids.length) return;
        const i = ids.indexOf(S.sel);
        S.sel = ids[(i + dir + ids.length) % ids.length];
        refresh();
      },
    };
  }
  function sortedTools() {
    const order = (x) => (x.kind === 'app' ? 0 : 2) + (x.installed ? 0 : 1);
    return (S.tools || []).slice().sort((a, b) => order(a) - order(b));
  }
  function visible() {
    const q = S.query.trim().toLowerCase();
    return sortedTools().filter((x) => !q || x.name.toLowerCase().includes(q) || x.id.includes(q));
  }
  async function chooseManually() {
    if (S.platform === 'darwin') {
      try {
        const r = await api('/api/pick', {});
        if (r.path) startJob({ path: r.path });
      } catch (e) { showError(e); }
      return;
    }
    S.manual = true;
    if (S.screen === 'pick') render(false);
  }

  // ---------- prepare ----------
  function stepDefs() {
    const t = T();
    const n = toolName();
    return isApp()
      ? [[t.s1, t.s1d], [t.s2, t.s2d], [t.s3(n), t.s3d, true], [t.s4(n), t.s4d]]
      : [[t.s1, t.s1d], [t.s2, t.s2d], [t.s3cli(n), t.s3clid]];
  }
  function prepScreen() {
    const t = T();
    const title = h('h1');
    const list = h('div', { class: 'enter' });
    const sw = h('input', { class: 'sw', type: 'checkbox', 'aria-label': t.deepTitle });
    sw.checked = S.deep;
    sw.addEventListener('change', () => { S.deep = sw.checked; });
    const deepRow = h('label', { class: 'item deep', title: t.deepDesc },
      h('span', { class: 'grow nm' }, `${t.deepTitle} `, h('span', { class: 'tag todo' }, t.beta)), sw);
    const count = h('span', { class: 'mono sub' });
    const startBtn = btn(t.startTest, '↵', launch, 'primary');
    const safe = h('span', { class: 'sub safe grow' },
      icon('M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z', 14, 'currentColor'), t.safeTitle);
    const el = h('div', { class: 'screen' },
      h('div', { class: 'head' }, title),
      h('div', { class: 'body' }, list, deepRow),
      bar(safe, count, btn(t.back, 'esc', back), startBtn));
    let rows = [];
    let kindShown = null;

    function launch() {
      if (!S.ready || S.starting || S.failed) return;
      S.starting = true;
      refresh();
      api('/api/launch', { deep: S.deep }).catch((e) => { S.starting = false; showError(e); refresh(); });
    }
    function back() {
      leavePreparation();
    }
    function update() {
      const defs = stepDefs();
      const n = toolName();
      title.textContent = t.prepTitle(n);
      safe.title = t.safeLine(n);
      if (kindShown !== defs.length) {  // the tool kind arrives with the first event
        kindShown = defs.length;
        rows = defs.map((d) => {
          const st = h('span', { class: 'status todo' });
          const name = h('span', { class: 'nm' }, d[0]);
          const tag = h('span', { class: 'tag todo' });
          const act = h('div', { class: 'do screen' }, btn(t.s3a(n), null, () => api('/api/quit-app', {}).catch(showError), 'primary big'),
            h('span', { class: 'sub' }, t.saveFirst));
          const row = h('div', { class: 'item static step', title: d[1] }, st,
            h('div', { class: 'grow' }, h('div', { class: 't' }, name, tag), act));
          return { row, st, tag, act, name };
        });
        list.replaceChildren(...rows.map((r) => r.row));
      }
      let done = 0;
      rows.forEach((r, i) => {
        let state = S.steps[i] || 'todo';
        if (i === rows.length - 1 && S.starting && state === 'todo') state = 'doing';
        if (state === 'done') done += 1;
        r.name.textContent = defs[i][0];
        r.row.className = `item static step ${state}`;
        r.st.className = `status ${state}`;
        r.st.replaceChildren(state === 'done' ? icon(CHECK, 11, 'currentColor', 3.5) : state === 'action' ? '!' : '');
        r.tag.className = `tag ${state}`;
        r.tag.textContent = t.st[state];
        r.act.hidden = state !== 'action';
      });
      count.textContent = t.stepsDone(done, rows.length);
      startBtn.disabled = !S.ready || S.starting || S.failed;
      sw.disabled = S.starting;
    }
    return { el, update, primary: launch, back };
  }

  // ---------- live ----------
  function liveScreen() {
    const t = T();
    const rec = h('span', { class: 'rec' });
    const title = h('h1');
    const elapsed = h('span', { class: 'mono elapsed' }, '00:00');
    const sample = h('span', { class: 'chip' }, t.sample);
    const todo = h('div', { class: 'sub' });
    const promptCode = h('code');
    const copyBtn = btn(t.copy, '⌘C', copyPrompt, 'soft');
    const promptCard = h('div', { class: 'card prompt' }, h('div', {}, todo, promptCode), copyBtn);
    const alertBox = h('div', { role: 'alert' });
    title.tabIndex = -1;
    const metrics = [t.stRequests, t.stHosts, t.stUp, t.stGaps].map((label) => {
      const b = h('b');
      return { box: h('div', { class: 'metric' }, b, h('span', {}, label)), b };
    });
    const setReq = counter(metrics[0].b, (v) => String(Math.round(v)));
    const setHosts = counter(metrics[1].b, (v) => String(Math.round(v)));
    const setUp = counter(metrics[2].b, (v) => humanBytes(v));
    const setGaps = counter(metrics[3].b, (v) => String(Math.round(v)));
    const flow = makeFlow(t);
    const feed = h('div', { class: 'feed' });
    const feedEmpty = h('p', { class: 'sub empty' }, t.waiting);
    const canBox = h('div');
    const finishBtn = btn(t.finish, '↵', finish, 'primary');
    const el = h('div', { class: 'screen' },
      h('div', { class: 'head' }, rec, title, elapsed, sample),
      h('div', { class: 'body stack' },
        promptCard, alertBox,
        h('div', { class: 'card metrics' }, metrics.map((m) => m.box)),
        h('div', { class: 'card flowcard' }, h('div', { class: 'sec' }, t.flowTitle), flow.svg),
        h('div', { class: 'cols' },
          h('div', { class: 'card feedcard' }, h('div', { class: 'sec' }, t.feedTitle), feed, feedEmpty),
          h('div', { class: 'card cancard' }, h('div', { class: 'sec' }, t.canaryTitle), canBox))),
      bar(grow(), finishBtn));
    let shown = 0;
    let lastAlert = '';

    function finish() {
      return finishJob();
    }
    function copyPrompt() {
      const text = S.prompt;
      const done = () => { S.copied = true; copyBtn.firstChild.textContent = t.copied; };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => {});
    }
    function update() {
      const n = toolName();
      title.textContent = t.liveTitle(n);
      sample.hidden = REPLAY || !(S.job && S.job.demo);
      promptCard.hidden = !S.prompt || (S.job && S.job.demo);
      todo.textContent = isApp() ? t.todoApp(n) : t.todoCli;
      promptCode.textContent = S.prompt;
      rec.className = S.finishing ? 'rec off' : 'rec';
      finishBtn.firstChild.textContent = S.finishing ? t.finishing : t.finish;
      finishBtn.disabled = S.finishing || !S.launched;

      const byId = Object.fromEntries(S.canaries.map((c) => [c.id, c]));
      const sentTo = {};
      const hosts = new Map();
      let reqs = 0; let up = 0; let gaps = 0;
      for (const ev of S.feed) {
        if (ev.kind === 'gap') {
          gaps += 1;
          hosts.set(`gap:${ev.host}`, { key: `gap:${ev.host}`, label: ev.host, bytes: 0, gap: true });
          continue;
        }
        reqs += 1; up += ev.bytes;
        const hst = hosts.get(ev.host) || { key: ev.host, label: ev.host, bytes: 0, secret: false, file: false };
        hst.bytes += ev.bytes;
        for (const id of ev.canaries) {
          if (!sentTo[id]) sentTo[id] = ev.host;
          if (byId[id] && byId[id].sensitive) hst.secret = true; else hst.file = true;
        }
        hosts.set(ev.host, hst);
      }
      setReq(reqs); setHosts([...hosts.values()].filter((x) => !x.gap).length); setUp(up); setGaps(gaps);
      metrics[3].box.className = gaps ? 'metric warn' : 'metric';

      for (; shown < S.feed.length; shown += 1) feed.append(feedRow(S.feed[shown], byId, t));
      while (feed.children.length > 200) feed.firstChild.remove();
      if (shown) feed.scrollTop = feed.scrollHeight;
      feedEmpty.hidden = shown > 0;

      const secrets = Object.entries(sentTo).filter(([id]) => byId[id] && byId[id].sensitive);
      const alertText = secrets.slice(0, 2).map(([id, host]) => `${canaryLabel(byId[id])} → ${host}`).join(S.lang === 'zh' ? '，' : ', ');
      if (alertText !== lastAlert) {
        lastAlert = alertText;
        alertBox.replaceChildren(alertText ? h('div', { class: 'alert' },
          icon(['M12 3l10 18H2z', 'M12 10v5', 'M12 18h.01'], 16, 'currentColor', 2.2), alertText) : '');
      }
      canBox.replaceChildren(...S.canaries.map((c) => {
        const sent = sentTo[c.id];
        const cls = sent ? (c.sensitive ? 'secret' : 'file') : '';
        return h('div', { class: `cn ${cls}`, title: sent || '' }, h('span', { class: 'd' }),
          h('span', {}, h('span', { class: 'l' }, canaryLabel(c)), h('code', {}, c.id === 'file_name' ? 'notes/…' : c.file)),
          h('span', { class: 's' }, sent ? (c.sensitive ? t.leaked : t.sent) : t.notSeen));
      }));
      flow.update([...hosts.values()]);
      tickElapsed();
    }
    function tickElapsed() {
      if (S.launchedWall && !S.finishing) elapsed.textContent = mmss(Math.max(0, Date.now() / 1000 - S.launchedWall));
    }
    return { el, update, primary: finish, tick: tickElapsed, copy: copyPrompt };
  }
  function canaryLabel(c) { return (c && T().canaries[c.id]) || (c && c.short) || ''; }
  function feedRow(ev, byId, t) {
    if (ev.kind === 'gap') {
      return h('div', { class: 'frow gap' }, h('span', { class: 'mono tm' }, mmss(ev.t)),
        h('span', { class: 'what' }, h('code', { class: 'host' }, ev.host), h('span', { class: 'sub' }, t.gapWhat[ev.why] || t.gapWhat.tcp)),
        h('span', { class: 'chip' }, t.gapChip), h('span', { class: 'mono sz' }, '–'));
    }
    const ids = ev.canaries.filter((id) => byId[id]);
    const secret = ids.some((id) => byId[id].sensitive);
    const first = ids.find((id) => byId[id].sensitive) || ids[0];
    return h('div', { class: `frow${secret ? ' leak' : ''}` }, h('span', { class: 'mono tm' }, mmss(ev.t)),
      h('span', { class: 'what' }, h('code', { class: 'host' }, ev.host),
        h('span', { class: 'sub mono' }, trunc(`${ev.method} ${ev.path}`, 80))),
      first ? h('span', { class: `chip ${secret ? 'bad' : 'warn'}` }, canaryLabel(byId[first]) + (ids.length > 1 ? ` +${ids.length - 1}` : '')) : null,
      h('span', { class: 'mono sz' }, humanBytes(ev.bytes)));
  }

  // Flow diagram: this computer on the left, destinations on the right, thin lines with
  // small dots travelling along them. Groups are kept by host so updates do not flash.
  function makeFlow(t) {
    const MAX = 5;
    const svg = sv('svg', { class: 'flow', role: 'img', 'aria-label': t.flowTitle });
    const groups = sv('g');
    const lc = sv('circle', { class: 'node', r: 22 });
    const lp = sv('circle', { class: 'pupil', r: 5 });
    const l1 = sv('text', { class: 't1', y: 42, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 600 }, t.local);
    const l2 = sv('text', { class: 'h', y: 58, 'text-anchor': 'middle', 'font-size': 10.5 }, '127.0.0.1');
    const local = sv('g', {}, lc, lp, l1, l2);
    svg.append(groups, local);
    const byKey = new Map();
    let last = [];
    let narrow = null;
    const isNarrow = () => !!svg.parentNode && svg.parentNode.clientWidth < 520;
    function update(hosts) {
      last = hosts;
      narrow = isNarrow();
      const W = narrow ? 360 : 730;               // phones get a tighter drawing, so the text stays readable
      const lx = narrow ? 44 : 120; const ex = narrow ? 176 : 496; const limit = narrow ? 22 : 26;
      let list = hosts.slice().sort((a, b) => (a.gap - b.gap) || (b.bytes - a.bytes));
      if (list.length > MAX) {
        const rest = list.slice(MAX - 1);
        list = list.slice(0, MAX - 1);
        list.push({ key: '__more', label: t.more(rest.length), bytes: rest.reduce((s, x) => s + x.bytes, 0),
          secret: rest.some((x) => x.secret), file: rest.some((x) => x.file) });
      }
      const n = list.length;
      const spacing = 66;
      const H = Math.max(170, (n - 1) * spacing + 110);  // the diagram grows with the destinations
      const cy = H / 2;
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      local.setAttribute('transform', `translate(${lx} ${cy - 16})`);
      const keep = new Set();
      list.forEach((x, i) => {
        keep.add(x.key);
        const ly = cy - 16;
        const y = Math.round(ly + (i - (n - 1) / 2) * spacing);
        const d = `M${lx + 22} ${ly} C ${lx + 180} ${ly}, ${ex - 136} ${y}, ${ex} ${y}`;
        const state = x.secret ? 'secret' : x.gap ? 'gap' : x.file ? 'file' : '';
        let g = byKey.get(x.key);
        if (!g) {
          g = { el: sv('g') };
          g.path = sv('path', { class: 'ln' });
          g.dots = [];
          if (!x.gap && !reduceMotion()) {
            for (const begin of ['0s', '-1.1s']) {
              const motion = sv('animateMotion', { dur: '2.2s', repeatCount: 'indefinite', begin, calcMode: 'spline',
                keyTimes: '0;1', keyPoints: '0;1', keySplines: '.45 .05 .55 .95' });
              const fade = sv('animate', { attributeName: 'opacity', values: '0;1;1;0', keyTimes: '0;.1;.9;1', dur: '2.2s',
                repeatCount: 'indefinite', begin });
              const dot = sv('circle', { r: 2.4, class: 'pt' }, motion, fade);
              g.dots.push({ dot, motion });
            }
          }
          g.end = sv('circle', { class: 'end', r: 3.5 });
          g.t1 = sv('text', { class: 'h t1', 'font-size': 12 });
          g.t2 = sv('text', { class: 't2', 'font-size': 11 });
          g.title = sv('title');
          g.el.append(g.title, g.path, ...g.dots.map((p) => p.dot), g.end, g.t1, g.t2);
          groups.append(g.el);
          byKey.set(x.key, g);
        }
        g.el.setAttribute('class', `hg ${state}`.trim());
        if (g.d !== d) {
          g.d = d;
          g.path.setAttribute('d', d);
          g.dots.forEach((p) => p.motion.setAttribute('path', d));
        }
        g.end.setAttribute('cx', ex + 4); g.end.setAttribute('cy', y);
        g.t1.setAttribute('x', ex + 18); g.t1.setAttribute('y', y - 2);
        g.t1.textContent = trunc(x.label, limit);
        g.title.textContent = x.label;
        g.t2.setAttribute('x', ex + 18); g.t2.setAttribute('y', y + 13);
        g.t2.textContent = x.gap ? t.gapChip : humanBytes(x.bytes);
      });
      for (const [key, g] of byKey) if (!keep.has(key)) { g.el.remove(); byKey.delete(key); }
    }
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        if (!svg.isConnected) ro.disconnect();
        else if (isNarrow() !== narrow) update(last);
      });
      ro.observe(win);
    }
    return { svg, update };
  }

  // ---------- report ----------
  function controlStatus(r) { return (r.control && r.control.status) || 'ok'; }
  function verdict(r, t) {
    const tt = r.totals;
    const diskSecrets = r.canaries.filter((c) => c.sensitive && c.on_disk && !c.sent_to.length).length;
    const extra = diskSecrets ? t.diskExtra(diskSecrets) : '';
    const gapX = tt.not_inspected ? t.gapExtra(tt.not_inspected, r.gap_names || '') : '';
    const ctl = controlStatus(r);
    if (tt.leaked_sensitive) return ['bad', t.headline(tt.leaked, tt.canaries), t.subSecret(tt.leaked_sensitive) + extra];
    if (ctl !== 'ok') return ['unknown', t.ctlHead[ctl], t.ctlSub[ctl] + gapX];
    if (r.warnings.length) return ['unknown', t.headWarnings, t.subWarnings];
    if (tt.leaked) return ['warn', t.headline(tt.leaked, tt.canaries), t.subFiles + extra + gapX];
    if (tt.not_inspected) return ['warn', t.headGap(tt.canaries), t.subGap(tt.not_inspected, r.gap_names || '') + extra];
    return ['good', t.headGood(tt.canaries), t.subGood + extra];
  }
  function checkRows(r, t) {
    const ctl = controlStatus(r);
    const row = (cls, mark, c, where) => ({ cls, mark, label: canaryLabel(c), where });
    return r.canaries.map((c) => {
      if (c.id === 'task_file' && ctl !== 'ok' && !c.sent_to.length) return row('unk', '?', c, t.expected);
      if (c.sent_to.length) return row(c.sensitive ? 'secret' : 'file', c.sensitive ? '✕' : '→', c, t.sentTo(c.sent_to.join(', ')));
      if (c.on_disk) return row(c.sensitive ? 'secret' : 'file', '!', c, t.diskOnly);
      if (ctl !== 'ok' || r.warnings.length || r.totals.not_inspected) return row('unk', '–', c, t.unconfirmed);
      return row('ok', '✓', c, t.notSeenLong);
    });
  }
  function reportMeta(r, t) { return `${String(r.started_at).replace('T', ' ').slice(0, 16)} · ${t.dur(r.duration_s)}`; }
  function reportName(r) { return S.job && S.job.demo ? T().demoName : r.agent; }

  function reportScreen() {
    const t = T();
    const r = S.report;
    const [tone, headline, subline] = verdict(r, t);
    const toastBox = h('div');
    const notices = [];
    if (r.warnings.some((w) => w.includes('exited after'))) notices.push(h('div', { class: 'notice' }, h('span', {}, t.quickExit(reportName(r)))));
    for (const warning of r.warnings.filter((w) => !w.includes('exited after'))) {
      notices.push(h('div', { class: 'notice' }, h('span', {}, warning)));
    }
    if (controlStatus(r) !== 'ok') {
      const retry = S.lastStart && !(S.job && S.job.demo) ? btn(t.retest, null, () => startJob(S.lastStart), 'soft') : null;
      notices.push(h('div', { class: 'notice' }, h('span', {}, t.ctlHelp[controlStatus(r)]), retry));
    }
    if (r.totals.not_inspected && r.capture === 'env' && !(S.job && S.job.demo) && S.lastStart) {
      notices.push(h('div', { class: 'notice' }, h('span', {}, t.gapsNote(r.totals.not_inspected)),
        btn(t.deepRetry, null, () => { S.deep = true; startJob(S.lastStart); }, 'soft')));
    }
    const stats = [[t.rHosts, r.totals.hosts, String], [t.rReq, r.totals.requests, String],
      [t.rUp, r.totals.bytes_out, humanBytes], [t.rGap, r.totals.not_inspected, String]];
    const statEls = stats.map(([label, v, fmt]) => {
      const b = h('b');
      counter(b, (x) => (fmt === String ? String(Math.round(x)) : fmt(x)))(v);
      return h('div', {}, b, h('span', {}, label));
    });
    const title = h('h2', { tabindex: '-1' }, headline);
    const card = h('div', { class: `hero ${tone}` },
      h('div', { class: 'agent' }, reportName(r), r.sample && !REPLAY ? h('span', { class: 'chip' }, t.sample) : null,
        h('span', { class: 'meta' }, reportMeta(r, t))),
      title, h('p', {}, subline),
      h('ul', { class: 'checks enter' }, checkRows(r, t).map((c) => h('li', { class: c.cls }, h('b', { 'aria-hidden': 'true' }, c.mark),
        h('div', {}, c.label, h('small', {}, c.where))))),
      h('div', { class: 'stats' }, statEls));
    const openFull = () => window.open(REPLAY ? r.url : `${r.url}?token=${encodeURIComponent(TOKEN)}`, '_blank', 'noopener');
    const exportImg = () => {
      const file = `whatsent-${(reportName(r) || 'report').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'report'}.png`;
      drawCard(r, t, tone, headline, subline).toBlob((blob) => {
        const a = h('a', { href: URL.createObjectURL(blob), download: file });
        document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
        const toast = h('div', { class: 'toast', role: 'status' }, icon(CHECK, 15, 'currentColor', 2.6), t.exported(file));
        toastBox.replaceChildren(toast);
        setTimeout(() => toast.remove(), 4000);
      }, 'image/png');
    };
    const again = () => { S.report = null; if (REPLAY) return startDemo(); S.job = null; S.deep = false; return go('pick'); };
    const el = h('div', { class: 'screen' },
      h('div', { class: 'rpt stack' }, toastBox, notices, card),
      bar(grow(), btn(REPLAY ? t.replayAgain : t.again, null, again),
        REPLAY ? h('a', { class: 'btn', href: '../' }, t.board) : null,
        btn(t.openFull, '⌘O', openFull), btn(t.exportImg, '⌘E', exportImg, 'primary')));
    return { el, primary: exportImg, exportImg, openFull, focus: () => title.focus({ preventScroll: true }) };
  }

  // The share card as a PNG, drawn directly on a canvas (no page screenshot, works offline).
  // It takes its colours from the page's own tokens, so it matches light or dark mode.
  function drawCard(r, t, tone, headline, subline) {
    const W = 1000; const P = 48; const scale = 2;
    const cs = getComputedStyle(document.documentElement);
    const v = (name) => cs.getPropertyValue(name).trim();
    const sans = getComputedStyle(document.body).fontFamily;
    const mono = v('--mono');
    const k = { bad: 'red', warn: 'amber', good: 'green', unknown: 'grey' }[tone];
    const ink = v('--ink'); const ink2 = v('--ink-2');
    const kinds = { ok: 'green', file: 'amber', unk: 'grey', secret: 'red' };
    const checks = checkRows(r, t);
    const canvas = document.createElement('canvas');
    let ctx = canvas.getContext('2d');
    const layout = (draw) => {
      let y = P;
      const text = (s, x, yy, font, color, align = 'left', spacing = '0px') => {
        if (!draw) return;
        ctx.font = font; ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = 'alphabetic';
        if ('letterSpacing' in ctx) ctx.letterSpacing = spacing;
        ctx.fillText(s, x, yy);
      };
      const wrap = (s, font, maxW) => {
        ctx.font = font;
        if ('letterSpacing' in ctx) ctx.letterSpacing = '-1.7px';
        const lines = []; let line = '';
        for (const ch of s.split(/(\s+)/).flatMap((w) => (/[　-鿿]/.test(w) ? [...w] : [w]))) {
          if (ctx.measureText(line + ch).width > maxW && line.trim()) { lines.push(line.trim()); line = ch.trimStart(); } else line += ch;
        }
        if (line.trim()) lines.push(line.trim());
        return lines;
      };
      if (draw) {
        const H = canvas.height / scale;
        rrect(ctx, 0, 0, W, H, 28); ctx.fillStyle = v('--win') || v('--bg'); ctx.fill();
        rrect(ctx, 0.5, 0.5, W - 1, H - 1, 28); ctx.fillStyle = v(`--${k}-bg`); ctx.fill();
        ctx.strokeStyle = v(`--${k}-line`); ctx.lineWidth = 1; ctx.stroke();
        rrect(ctx, P, y, 36, 36, 10); ctx.fillStyle = ink; ctx.fill();
        ctx.strokeStyle = v('--bg'); ctx.lineWidth = 2.4; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
        ctx.beginPath(); ctx.moveTo(P + 7, y + 18); ctx.quadraticCurveTo(P + 18, y + 5, P + 29, y + 18);
        ctx.quadraticCurveTo(P + 18, y + 31, P + 7, y + 18); ctx.stroke();
        ctx.beginPath(); ctx.arc(P + 18, y + 18, 4, 0, Math.PI * 2); ctx.stroke();
      }
      text('whatsent', P + 48, y + 25, `650 22px ${sans}`, ink);
      text(reportMeta(r, t), W - P, y + 25, `400 18px ${mono}`, ink2, 'right');
      y += 36 + 44;
      if (draw) { ctx.beginPath(); ctx.arc(P + 5, y - 7, 5, 0, Math.PI * 2); ctx.fillStyle = v(`--${k}`); ctx.fill(); }
      text(reportName(r) + (r.sample ? `  ·  ${t.sample}` : ''), P + 20, y, `600 22px ${sans}`, ink);
      y += 14;
      const hFont = `700 52px ${sans}`;
      for (const line of wrap(headline, hFont, W - 2 * P)) { y += 58; text(line, P, y, hFont, ink, 'left', '-1.7px'); }
      y += 40;
      text(subline, P, y, `500 24px ${sans}`, v(`--${k}-ink`));
      y += 32;
      const colW = (W - 2 * P - 12) / 2; const boxH = 76;
      checks.forEach((c, i) => {
        const x = P + (i % 2) * (colW + 12); const yy = y + Math.floor(i / 2) * (boxH + 10);
        if (!draw) return;
        const q = kinds[c.cls];
        rrect(ctx, x, yy, colW, boxH, 14); ctx.fillStyle = v('--raised'); ctx.fill();
        if (c.cls === 'secret') { ctx.fillStyle = v('--red-bg'); ctx.fill(); }
        ctx.strokeStyle = c.cls === 'secret' ? v('--red-line') : v('--line'); ctx.lineWidth = 1; ctx.stroke();
        ctx.beginPath(); ctx.arc(x + 32, yy + boxH / 2, 13, 0, Math.PI * 2);
        ctx.fillStyle = c.cls === 'secret' ? v('--red') : v(`--${q}-bg`); ctx.fill();
        text(c.mark, x + 32, yy + boxH / 2 + 6, `700 16px ${sans}`, c.cls === 'secret' ? v('--on-red') : v(`--${q}-ink`), 'center');
        text(trunc(c.label, 30), x + 58, yy + 33, `600 19px ${sans}`, ink);
        text(trunc(c.where, 40), x + 58, yy + 58, `400 15px ${mono}`, ink2);
      });
      y += Math.ceil(checks.length / 2) * (boxH + 10) + 22;
      if (draw) { ctx.fillStyle = v(`--${k}-line`); ctx.fillRect(P, y, W - 2 * P, 1); }
      y += 52;
      const stats = [[r.totals.hosts, t.rHosts], [r.totals.requests, t.rReq], [humanBytes(r.totals.bytes_out), t.rUp], [r.totals.not_inspected, t.rGap]];
      let x = P;
      for (const [val, label] of stats) {
        ctx.font = `650 34px ${sans}`;
        const w = Math.max(ctx.measureText(String(val)).width, (ctx.font = `400 16px ${sans}`, ctx.measureText(label).width));
        text(String(val), x, y, `650 34px ${sans}`, ink);
        text(label, x, y + 26, `400 16px ${sans}`, ink2);
        x += w + 56;
      }
      y += 26 + 44;
      text('github.com/sundaysebasidian-byte/whatsent', W - P, y - 8, `400 14px ${mono}`, ink2, 'right');
      return y;
    };
    const height = layout(false) + 8;
    canvas.width = W * scale; canvas.height = height * scale;
    ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    layout(true);
    return canvas;
  }
  function rrect(ctx, x, y, w, hh, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + hh, r); ctx.arcTo(x + w, y + hh, x, y + hh, r);
    ctx.arcTo(x, y + hh, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  // ---------- sheets (one sentence, one button) ----------
  const sheetRoot = document.getElementById('sheet-root');
  function sheet(spec) {
    S.sheet = spec;
    const b = h('button', { class: 'btn primary', type: 'button', onclick: () => { closeSheet(); spec.action(); } }, spec.btn);
    const bg = h('div', { class: 'sheet-bg', onclick: (e) => { if (e.target === bg) closeSheet(); } },
      h('div', { class: 'sheet', role: 'alertdialog', 'aria-modal': 'true', 'aria-label': spec.text },
        h('span', { class: `ic ${spec.ic}`, 'aria-hidden': 'true' }, spec.mark),
        h('p', {}, spec.text), spec.detail ? h('small', { title: spec.detail }, spec.detail) : null, b));
    sheetRoot.replaceChildren(bg);
    setTimeout(() => b.focus(), 30);
  }
  function closeSheet() { S.sheet = null; sheetRoot.replaceChildren(); }

  // ---------- keyboard ----------
  document.addEventListener('keydown', (e) => {
    if (S.sheet) { if (e.key === 'Escape') closeSheet(); return; }
    const mod = e.metaKey || e.ctrlKey;
    const k = e.key.toLowerCase();
    if (mod && k === 'd' && S.screen === 'welcome') { e.preventDefault(); startDemo(); return; }
    if (mod && k === 'e' && S.screen === 'report') { e.preventDefault(); V.exportImg(); return; }
    if (mod && k === 'o' && S.screen === 'report') { e.preventDefault(); V.openFull(); return; }
    if (mod && k === 'c' && S.screen === 'live' && !String(window.getSelection())) { e.preventDefault(); V.copy(); return; }
    if (mod || e.altKey) return;
    const tag = document.activeElement && document.activeElement.tagName;
    if (e.key === 'Enter') {
      if (tag === 'BUTTON' || tag === 'A' || tag === 'LABEL' || (tag === 'INPUT' && document.activeElement.type === 'checkbox')) return;
      if (V.primary) { e.preventDefault(); V.primary(); }
    } else if (e.key === 'Escape') {
      if (V.back) { e.preventDefault(); V.back(); }
    } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && V.move) {
      e.preventDefault(); V.move(e.key === 'ArrowDown' ? 1 : -1);
    }
  });
  setInterval(() => { if (V && V.tick) V.tick(); }, 1000);

  // ---------- start ----------
  async function init() {
    render(true);
    if (REPLAY) { S.platform = ''; startDemo(); return; }
    try {
      const st = await api('/api/state');
      S.platform = st.platform;
      if (st.stale) {
        sheet({ ic: 'ok', mark: '✓', text: T().staleSheet, btn: T().closeTest, action: () => api('/api/stale/close', {}).catch(showError) });
      }
      const job = st.job;
      if (job && !['cancelled', 'failed'].includes(job.state) && (job.active || job.state === 'done')) {
        S.job = { id: job.id, tool: job.tool, demo: job.demo };
        S.screen = job.demo ? 'live' : 'prep';
        render(true);
        connect(job.id);  // replays this run's events, so a reload lands where the run is
      }
    } catch (e) { showError(e); }
  }
  init();
})();
