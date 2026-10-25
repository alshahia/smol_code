(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (value) => String(value).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const icon = (name, size = 14) => '<svg width="' + size + '" height="' + size + '" aria-hidden="true"><use href="#i-' + name + '"/></svg>';

  const RUNS = {
    run_7f3a: {
      id: 'run_7f3a', short: '7f3a', project: 'orbit-api',
      objective: 'Stop duplicate webhook deliveries',
      tier: 'restricted', model: 'claude-sonnet-4', elapsed: '04:12', cost: '$0.38',
      status: 'awaiting', statusText: 'Awaiting approval', started: '09:41:02',
      tools: 5, approvals: 1, changesCount: 1,
      gate: {
        title: 'One change is waiting for your signature.',
        sub: 'src/billing/webhook.py · +24 −3 · sha 9d07aa · restricted image a91c4e',
        approved: false, rejected: false
      },
      consoleText: '',
      trace: [
        { time: '09:41:02', kind: 'run.started', title: 'Run started in the <code>restricted</code> sandbox', meta: 'image a91c4e · workspace ~/work/orbit-api' },
        { time: '09:41:03', kind: 'plan.ready', title: 'Planned four steps', meta: 'inspect · reproduce · patch · verify', details: { label: 'plan', code: '1  read src/billing/webhook.py\n2  reproduce a duplicate delivery\n3  add an idempotency guard\n4  run tests/billing/test_webhook.py' } },
        { time: '09:41:08', kind: 'read_file', title: 'Read <code>src/billing/webhook.py</code>', meta: '148 lines · 4.2 KB', details: { label: 'first 8 lines', code: 'import hashlib\nimport json\nimport time\n\nfrom fastapi import Request, Response\nfrom billing.audit import audit\n\n_DELIVERY_KEYS = Store("webhook.delivery")' } },
        { time: '09:41:19', kind: 'search', title: 'Found the duplicate path', meta: '3 matches for "delivery" · src/billing/webhook.py', details: { label: 'matches', code: '42:  if event["type"] == "invoice.paid":\n43:      _send_receipt(event)\n67:  def _send_receipt(event: dict) -> None:' } },
        { time: '09:41:31', kind: 'code', title: 'Wrote an idempotency guard', meta: 'python · 14 lines', details: { label: 'sandbox execution', code: 'def _delivery_key(event: dict) -> str:\n    payload = json.dumps(event, sort_keys=True)\n    return hashlib.sha256(payload.encode()).hexdigest()\n\n# guard before side effects\nkey = _delivery_key(event)\nif _already_delivered(key):\n    return Response(status_code=200)' } },
        { time: '09:41:44', kind: 'test', title: 'Ran the webhook test file', meta: 'pytest -q tests/billing/test_webhook.py · 12 passed in 1.82s', ok: true, details: { label: 'pytest output', code: '................                                                        [100%]\n12 passed in 1.82s' } },
        { time: '09:41:52', kind: 'lint', title: 'ruff check passed', meta: 'no findings in 1 changed file', ok: true },
        { time: '09:42:07', kind: 'diff.proposed', title: 'Proposed one file change', meta: 'src/billing/webhook.py · +24 −3 · sha 9d07aa', details: { label: 'diff summary', code: 'src/billing/webhook.py | 27 +++++++++++++++++++++++----\n1 file changed, 24 insertions(+), 3 deletions(-)' } },
        { time: '09:42:07', kind: 'approval.requested', gate: true },
        { time: '09:42:11', kind: 'sandbox.held', title: 'Sandbox held at the gate', meta: 'no commands have run since 09:42:11', current: true, sub: true }
      ],
      consoleHtml: ''
    },
    run_2b9c: {
      id: 'run_2b9c', short: '2b9c', project: 'orbit-api',
      objective: 'Drop 12 legacy snapshot files',
      tier: 'elevated', model: 'claude-opus-4', elapsed: '06:48', cost: '$0.91',
      status: 'running', statusText: 'Running', started: '09:35:24',
      tools: 4, approvals: 0, changesCount: 0,
      gate: null,
      consoleText: '09:35:24  run.started   elevated image 02b7f1\n09:35:31  read_file     src/session/store.py  312 lines\n09:35:52  search        "snapshot" in tests/  8 matches\n09:36:18  code          removal plan for 12 files\n09:36:44  pytest        tests/session/test_store.py  19 passed\n09:37:02  running       validating migration note\n',
      trace: [
        { time: '09:35:24', kind: 'run.started', title: 'Run started in the <code>elevated</code> sandbox', meta: 'image 02b7f1 · workspace ~/work/orbit-api · 2 extra paths' },
        { time: '09:35:31', kind: 'read_file', title: 'Read <code>src/session/store.py</code>', meta: '312 lines · 9.1 KB' },
        { time: '09:35:52', kind: 'search', title: 'Found the snapshot footprint', meta: '8 matches in tests/session · 12 files referenced', details: { label: 'plan', code: 'inspect 12 legacy snapshots\nverify no runtime references\nremove fixtures and migration note' } },
        { time: '09:36:18', kind: 'code', title: 'Prepared the removal plan', meta: '12 files · tests still reference 3' },
        { time: '09:36:44', kind: 'test', title: 'Ran the session store tests', meta: 'pytest -q tests/session/test_store.py · 19 passed in 2.10s', ok: true },
        { time: '09:37:02', kind: 'sandbox.exec', title: 'Checking migration notes', meta: 'no commands outside the workspace', current: true, sub: true }
      ],
      consoleHtml: ''
    },
    run_6d1e: {
      id: 'run_6d1e', short: '6d1e', project: 'orbit-api',
      objective: 'Fix flaky billing snapshot test',
      tier: 'restricted', model: 'claude-sonnet-4', elapsed: '02:03', cost: '$0.14',
      status: 'done', statusText: 'Done', started: '08:52:10',
      tools: 3, approvals: 0, changesCount: 0,
      gate: null,
      consoleText: '08:52:10  run.started   restricted image a91c4e\n08:52:21  pytest        tests/billing/test_snapshot.py  1 failed\n08:52:49  code          pinned the clock fixture\n08:53:04  pytest        tests/billing/test_snapshot.py  1 passed\n08:53:13  done          no diff required\n',
      trace: [
        { time: '08:52:10', kind: 'run.started', title: 'Run started in the <code>restricted</code> sandbox', meta: 'image a91c4e · workspace ~/work/orbit-api' },
        { time: '08:52:21', kind: 'test', title: 'Reproduced the flaky snapshot test', meta: '1 failed in 0.74s', error: true },
        { time: '08:52:49', kind: 'code', title: 'Pinned the clock fixture', meta: 'tests/billing/conftest.py · 2 lines' },
        { time: '08:53:04', kind: 'test', title: 'Test passes with the fixture', meta: '1 passed in 0.63s', ok: true },
        { time: '08:53:13', kind: 'run.completed', title: 'Run completed', meta: 'no diff · 1 test fixed · $0.14 spent', ok: true }
      ],
      consoleHtml: ''
    },
    run_04aa: {
      id: 'run_04aa', short: '04aa', project: 'orbit-api',
      objective: 'Migrate the audit chain to v2 with rotation',
      tier: 'full_access', model: 'claude-opus-4', elapsed: '00:00', cost: '$0.00',
      status: 'queued', statusText: 'Queued · #1', started: '—',
      tools: 0, approvals: 0, changesCount: 0,
      gate: null, consoleText: 'Waiting for a runner. No commands have run.\n',
      trace: []
    },
    run_9c31: {
      id: 'run_9c31', short: '9c31', project: 'orbit-api',
      objective: 'Document the tier policy matrix',
      tier: 'restricted', model: 'claude-sonnet-4', elapsed: '01:12', cost: '$0.02',
      status: 'returned', statusText: 'Returned', started: '09:21:44',
      tools: 2, approvals: 0, changesCount: 0,
      gate: null,
      consoleText: '09:21:44  run.started   restricted image a91c4e\n09:21:51  read_file     docs/security.md  84 lines\n09:22:08  note          policy matrix already current\n09:22:56  returned      no change proposed\n',
      trace: [
        { time: '09:21:44', kind: 'run.started', title: 'Run started in the <code>restricted</code> sandbox', meta: 'image a91c4e · workspace ~/work/orbit-api' },
        { time: '09:21:51', kind: 'read_file', title: 'Read <code>docs/security.md</code>', meta: '84 lines · 3.7 KB' },
        { time: '09:22:08', kind: 'note', title: 'The policy matrix is already current', meta: 'no safe change to propose' },
        { time: '09:22:56', kind: 'returned', title: 'Returned without a diff', meta: 'run_9c31 · $0.02 spent', bad: true }
      ],
      consoleHtml: ''
    }
  };

  const overlayKinds = ['sessions', 'launch', 'palette', 'audit', 'usage', 'context', 'project', 'help'];
  const views = ['trace', 'changes', 'console', 'files', 'queue'];
  const state = {
    currentRun: 'run_7f3a',
    view: 'trace',
    sessionFilter: 'all',
    sessionQuery: '',
    paletteIndex: 0,
    auditSeq: 1204,
    auditEntries: [
      { seq: 1204, action: 'approval.requested', detail: 'sha 9d07aa · src/billing/webhook.py', actor: 'run_7f3a', time: '09:42:07' },
      { seq: 1203, action: 'diff.proposed', detail: '+24 −3 · src/billing/webhook.py', actor: 'run_7f3a', time: '09:42:07' },
      { seq: 1202, action: 'tool.completed', detail: 'pytest · 12 passed', actor: 'run_7f3a', time: '09:41:44' },
      { seq: 1201, action: 'tool.completed', detail: 'ruff · no findings', actor: 'run_7f3a', time: '09:41:52' },
      { seq: 1200, action: 'policy.check', detail: 'restricted · image a91c4e', actor: 'run_7f3a', time: '09:41:02' },
      { seq: 1199, action: 'approval.granted', detail: 'sha 4b21c9 · src/session/store.py', actor: 'you', time: '09:14:38' }
    ],
    drainOn: false,
    lastFocus: null
  };

  const el = {
    app: $('[data-app]'),
    railRuns: $('#rail-runs'),
    queueBadge: $('#queue-badge'),
    railChain: $('#rail-chain'),
    needsBtn: $('#needs-btn'),
    needsCount: $('#needs-count'),
    needsLabel: $('#needs-label'),
    statusPill: $('#status-pill'),
    crumbRun: $('#crumb-run'),
    objective: $('#objective'),
    tierTag: $('#tier-tag'),
    model: $('#model'),
    workspace: $('#workspace'),
    elapsed: $('#elapsed'),
    cost: $('#cost'),
    traceList: $('#trace-list'),
    traceCount: $('#trace-count'),
    changesCount: $('#changes-count'),
    sumEvents: $('#sum-events'),
    sumTools: $('#sum-tools'),
    sumApprovals: $('#sum-approvals'),
    sumStarted: $('#sum-started'),
    nowLine: $('#now-line'),
    gateDock: $('#gate-dock'),
    gateTitle: $('#gate-title'),
    gateSub: $('#gate-sub'),
    gateApprove: $('#gate-approve'),
    gateHold: $('#gate-hold'),
    gateReject: $('#gate-reject'),
    gateNote: $('#gate-note'),
    runShell: $('#run-shell'),
    viewQueue: $('#view-queue'),
    stageBody: $('#stage-body'),
    composerInput: $('#composer-input'),
    composerTier: $('#composer-tier'),
    composerModel: $('#composer-model'),
    sessions: $('#sessions'),
    launch: $('#launch'),
    palette: $('#palette'),
    drawer: $('#drawer'),
    scrim: $('#scrim'),
    sessionList: $('#session-list'),
    sessionSearch: $('#session-search'),
    sessionFilters: $('#session-filters'),
    launchTask: $('#launch-task'),
    launchModel: $('#launch-model'),
    tierNote: $('#tier-note'),
    toast: $('#toast'),
    paletteSearch: $('#palette-search'),
    paletteList: $('#palette-list'),
    drawerTitle: $('#drawer-title'),
    drawerSub: $('#drawer-sub'),
    drawerBody: $('#drawer-body'),
    consoleBox: $('#view-console .console-box'),
    consoleSub: $('#view-console .console-head p')
  };

  const defaultConsoleHtml = el.consoleBox ? el.consoleBox.innerHTML : '';
  let toastTimer = null;
  let selectedTier = 'restricted';

  const tierNotes = {
    restricted: '<b>Restricted is the default.</b> The run can read and write only inside ~/work/orbit-api. A tier change never happens mid-run.',
    elevated: '<b>Elevated is opt-in.</b> Adds the named extra paths and allowlisted hosts for this run only. Every extra mount is listed in the trace.',
    full_access: '<b>Full access is explicit and audited.</b> Broader host reach for specialist work. The gate still applies to every proposed diff.'
  };

  const runList = () => Object.values(RUNS);

  function toast(message) {
    if (!el.toast) return;
    el.toast.innerHTML = message;
    el.toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.toast.classList.remove('show'), 3400);
  }

  function statusClass(run) {
    return run.status;
  }

  function updateNeeds() {
    const awaiting = runList().filter((run) => run.status === 'awaiting').length;
    el.needsCount.textContent = String(awaiting);
    el.needsLabel.textContent = awaiting ? 'needs you' : 'clear';
    el.needsBtn.classList.toggle('is-clear', awaiting === 0);
    const dot = el.needsBtn.querySelector('.dot');
    if (dot) dot.style.background = awaiting ? 'var(--amber-bright)' : '#5e6d66';
  }

  function renderRail() {
    el.railRuns.innerHTML = runList().map((run) => {
      const active = run.id === state.currentRun;
      return '<button class="run-chip' + (active ? ' is-active' : '') + '" type="button" data-run="' + run.id + '" data-status="' + statusClass(run) + '" data-tip="' + esc(run.id + ' · ' + run.objective) + '" aria-label="' + esc(run.id + ' · ' + run.objective + ' · ' + run.statusText) + '" aria-pressed="' + (active ? 'true' : 'false') + '">' +
        '<span class="chip-id">' + run.short + '</span><span class="chip-dot"></span></button>';
    }).join('');
    el.queueBadge.textContent = state.drainOn ? '0' : '1';
    el.queueBadge.hidden = state.drainOn;
    el.railChain.textContent = state.auditSeq >= 1000 ? (state.auditSeq / 1000).toFixed(1) + 'k' : String(state.auditSeq);
    updateNeeds();
  }

  function traceSummary(run) {
    el.sumEvents.textContent = run.trace.length;
    el.sumTools.textContent = run.tools;
    el.sumApprovals.textContent = run.approvals;
    el.sumStarted.textContent = run.started === '—' ? 'not started' : 'started ' + run.started;
    el.traceCount.textContent = run.trace.length;
  }

  function gateRow(run) {
    const gate = run.gate || {};
    if (gate.approved) {
      return '<li class="trace-row gate approved"><time>09:42:40</time><span class="trace-node"><i></i></span><div class="trace-content">' +
        '<div class="trace-kicker"><span class="kind ok">approval.granted</span><span class="mono">09:42:40</span></div>' +
        '<div class="trace-title">Signature recorded · run resumed</div>' +
        '<div class="trace-meta">sha 9d07aa · audit 1,205 · approval bound to this diff</div>' +
        '</div></li>';
    }
    if (gate.rejected) {
      return '<li class="trace-row gate rejected"><time>09:42:40</time><span class="trace-node"><i></i></span><div class="trace-content">' +
        '<div class="trace-kicker"><span class="kind bad">approval.rejected</span><span class="mono">hold</span></div>' +
        '<div class="trace-title">Change rejected · run returned</div>' +
        '<div class="trace-meta">sha 9d07aa · no change released · audit 1,205</div>' +
        '</div></li>';
    }
    return '<li class="trace-row gate"><time>09:42:07</time><span class="trace-node"><i></i></span><div class="trace-content">' +
      '<div class="trace-kicker"><span class="kind gate">approval.requested</span><span class="mono">hold</span></div>' +
      '<div class="trace-title">' + esc(gate.title || 'One change is waiting for your signature.') + '</div>' +
      '<div class="trace-meta">' + esc(gate.sub || '') + '</div>' +
      '<div class="trace-actions"><button class="btn btn-sm btn-primary" type="button" data-view="changes">Review change</button><button class="btn btn-sm" type="button" data-toast="Held. The sandbox stays alive at the gate.">Hold</button></div>' +
      '</div></li>';
  }

  function traceRow(event) {
    if (event.gate) return gateRow(RUNS[state.currentRun]);
    const classes = ['trace-row'];
    if (event.sub) classes.push('sub');
    if (event.current) classes.push('current');
    if (event.error) classes.push('error');
    const detail = event.details ? '<details class="trace-details"><summary>' + esc(event.details.label) + '</summary><pre class="codebox">' + esc(event.details.code) + '</pre></details>' : '';
    const actions = event.kind === 'diff.proposed' && RUNS[state.currentRun].changesCount ? '<div class="trace-actions"><button class="btn btn-sm" type="button" data-view="changes">Open diff</button></div>' : '';
    return '<li class="' + classes.join(' ') + '"><time>' + esc(event.time) + '</time><span class="trace-node"><i></i></span><div class="trace-content">' +
      '<div class="trace-kicker"><span class="kind ' + (event.ok ? 'ok' : event.bad ? 'bad' : '') + '">' + esc(event.kind) + '</span><span class="mono">' + (event.current ? 'now' : '') + '</span></div>' +
      '<div class="trace-title">' + event.title + '</div>' +
      '<div class="trace-meta">' + event.meta + '</div>' + detail + actions + '</div></li>';
  }

  function renderTrace(run) {
    traceSummary(run);
    el.traceList.innerHTML = run.trace.length ? run.trace.map(traceRow).join('') : queuedRow();
    if (el.nowLine) {
      el.nowLine.className = 'now-line';
      if (run.status === 'awaiting') {
        el.nowLine.innerHTML = '<span>waiting on you</span><span class="bar"></span><b>' + run.elapsed + '</b>';
      } else if (run.status === 'running') {
        el.nowLine.classList.add('running');
        el.nowLine.innerHTML = '<span>run in progress</span><span class="bar"></span><b>' + run.elapsed + '</b>';
      } else if (run.status === 'done') {
        el.nowLine.classList.add('done');
        el.nowLine.innerHTML = '<span>run complete · audit ' + state.auditSeq.toLocaleString() + '</span><span class="bar"></span><b>done</b>';
      } else if (run.status === 'queued') {
        el.nowLine.classList.add('queued');
        el.nowLine.innerHTML = '<span>queued · waiting for a slot</span><span class="bar"></span><b>#1</b>';
      } else {
        el.nowLine.classList.add('returned');
        el.nowLine.innerHTML = '<span>returned to you</span><span class="bar"></span><b>no release</b>';
      }
    }
  }

  function queuedRow() {
    return '<li class="trace-queued"><span class="trace-queued-mark">' + icon('queue', 18) + '</span><div><div class="trace-title">Queued behind run_7f3a</div><div class="trace-meta">No sandbox has started. Draining the queue is manual.</div></div></li>';
  }

  function renderGate(run) {
    const gate = run.gate;
    const show = Boolean(gate && !gate.approved && !gate.rejected && run.status === 'awaiting');
    el.gateDock.hidden = !show;
    if (!show) return;
    el.gateDock.classList.remove('approved');
    el.gateTitle.textContent = gate.title;
    el.gateSub.textContent = gate.sub;
    el.gateApprove.textContent = state.view === 'changes' ? 'Approve change' : 'Review change';
    el.gateNote.textContent = 'Approval releases this diff once.';
  }

  function applyRun(id) {
    const run = RUNS[id];
    if (!run) return;
    state.currentRun = id;
    el.crumbRun.textContent = run.id;
    el.statusPill.className = 'status-pill ' + run.status;
    el.statusPill.innerHTML = '<i></i><span id="status-text">' + esc(run.statusText) + '</span>';
    el.objective.textContent = run.objective;
    el.tierTag.textContent = run.tier;
    el.tierTag.dataset.tier = run.tier;
    el.model.textContent = run.model;
    el.elapsed.textContent = run.elapsed;
    el.cost.textContent = run.cost;
    el.changesCount.textContent = run.changesCount || '';
    el.changesCount.hidden = !run.changesCount;
    el.changesCount.classList.toggle('alert', Boolean(run.changesCount));
    const changesBtn = $('[data-view="changes"]');
    if (changesBtn) {
      changesBtn.disabled = !run.changesCount;
      changesBtn.title = run.changesCount ? 'Review the proposed diff' : 'No proposed changes for this run';
    }
    renderTrace(run);
    renderGate(run);
    renderRail();
    renderSessions();
    updateConsole(run);
    if (state.view === 'changes' && !run.changesCount) setView('trace', false);
    document.title = 'smolcode · ' + run.objective;
  }

  function updateConsole(run) {
    if (!el.consoleBox) return;
    if (run.id === 'run_7f3a' && defaultConsoleHtml) {
      el.consoleBox.innerHTML = defaultConsoleHtml;
    } else {
      el.consoleBox.textContent = run.consoleText || 'No console capture for this run yet.';
    }
    if (el.consoleSub) el.consoleSub.textContent = run.id + ' · ' + run.tier + ' image ' + (run.tier === 'restricted' ? 'a91c4e' : run.tier === 'elevated' ? '02b7f1' : '7ce0aa') + ' · read-only capture';
  }

  function setView(view, updateHash = true) {
    const run = RUNS[state.currentRun];
    if (view === 'changes' && !run.changesCount) view = 'trace';
    state.view = view;
    const isQueue = view === 'queue';
    el.runShell.hidden = isQueue;
    el.viewQueue.hidden = !isQueue;
    if (!isQueue) {
      $$('.stage-modes [data-view]').forEach((button) => button.classList.toggle('on', button.dataset.view === view));
      $$('[data-view-panel]').forEach((panel) => {
        const visible = panel.dataset.viewPanel === view;
        panel.hidden = !visible;
        panel.classList.remove('view-enter');
        if (visible) requestAnimationFrame(() => panel.classList.add('view-enter'));
      });
      renderGate(run);
      el.stageBody.scrollTop = 0;
    }
    if (updateHash) history.replaceState(null, '', '#' + view);
  }

  function renderSessions() {
    if (!el.sessionList) return;
    const query = state.sessionQuery.trim().toLowerCase();
    const filter = state.sessionFilter;
    const matches = runList().filter((run) => {
      const filterOk = filter === 'all' || run.status === filter;
      const haystack = (run.id + ' ' + run.objective + ' ' + run.model + ' ' + run.tier).toLowerCase();
      return filterOk && (!query || haystack.includes(query));
    });
    if (!matches.length) {
      el.sessionList.innerHTML = '<div class="palette-empty">No run matches that filter.</div>';
      return;
    }
    el.sessionList.innerHTML = '<div class="session-group">orbit-api · ' + matches.length + ' shown</div>' + matches.map((run) => {
      const active = run.id === state.currentRun;
      const alert = run.status === 'awaiting';
      return '<button class="session-row' + (active ? ' on' : '') + '" type="button" data-run="' + run.id + '" data-status="' + statusClass(run) + '">' +
        '<span class="sdot"></span><span><span class="stitle">' + esc(run.objective) + '</span>' +
        '<span class="smeta"><span>' + run.id + '</span><span>' + run.tier + '</span><span>' + run.model + '</span>' + (alert ? '<span class="alert">needs you</span>' : '') + '</span></span></button>';
    }).join('');
  }

  function openOverlay(kind, remember = true) {
    if (remember) state.lastFocus = document.activeElement;
    closeAllOverlays(false);
    if (kind === 'sessions') {
      renderSessions();
      el.sessions.hidden = false;
      el.scrim.hidden = false;
      el.sessionSearch.value = state.sessionQuery;
      setTimeout(() => el.sessionSearch.focus(), 20);
    } else if (kind === 'launch') {
      el.launch.hidden = false;
      el.scrim.hidden = false;
      setTimeout(() => el.launchTask.focus(), 20);
    } else if (kind === 'palette') {
      el.palette.hidden = false;
      el.scrim.hidden = false;
      el.paletteSearch.value = '';
      state.paletteIndex = 0;
      renderPalette('');
      setTimeout(() => el.paletteSearch.focus(), 20);
    } else {
      renderDrawer(kind);
      el.drawer.hidden = false;
    }
    history.replaceState(null, '', '#' + kind);
  }

  function closeAllOverlays(updateHash = true) {
    [el.sessions, el.launch, el.palette, el.drawer].forEach((node) => { if (node) node.hidden = true; });
    if (el.scrim) el.scrim.hidden = true;
    if (updateHash) history.replaceState(null, '', '#' + state.view);
    if (state.lastFocus && typeof state.lastFocus.focus === 'function') {
      const last = state.lastFocus;
      state.lastFocus = null;
      setTimeout(() => last.focus(), 20);
    }
  }

  function selectRun(id) {
    if (!RUNS[id]) return;
    const wasQueue = state.view === 'queue';
    state.currentRun = id;
    closeAllOverlays(false);
    if (wasQueue) {
      state.view = 'trace';
      setView('trace', true);
    } else {
      applyRun(id);
      if (state.view === 'changes' && !RUNS[id].changesCount) setView('trace', true);
      else history.replaceState(null, '', '#' + state.view);
    }
    applyRun(id);
    toast('<b>' + RUNS[id].id + '</b> · ' + esc(RUNS[id].objective));
  }

  function approveGate() {
    const run = RUNS[state.currentRun];
    if (!run.gate || run.gate.approved || run.gate.rejected) return;
    if (state.view !== 'changes') {
      setView('changes');
      toast('Review the diff, then approve. The gate stays open.');
      return;
    }
    run.gate.approved = true;
    run.status = 'done';
    run.statusText = 'Done';
    run.approvals = 0;
    run.changesCount = 0;
    run.elapsed = '04:41';
    run.trace = run.trace.map((event) => event.current ? Object.assign({}, event, { current: false }) : event);
    run.trace.push({ time: '09:42:40', kind: 'approval.granted', title: 'Signature recorded · run resumed', meta: 'sha 9d07aa · audit 1,205 · approval bound to this diff', ok: true });
    run.trace.push({ time: '09:42:52', kind: 'run.completed', title: 'Run completed', meta: '1 file changed · 12 tests passed · $0.41 spent', ok: true });
    state.auditSeq = 1205;
    state.auditEntries.unshift({ seq: 1205, action: 'approval.granted', detail: 'sha 9d07aa · src/billing/webhook.py', actor: 'you', time: '09:42:40' });
    applyRun(state.currentRun);
    setView('trace', true);
    toast('<b>Approved</b> · run_7f3a resumed · audit 1,205');
  }

  function rejectGate() {
    const run = RUNS[state.currentRun];
    if (!run.gate || run.gate.approved || run.gate.rejected) return;
    run.gate.rejected = true;
    run.status = 'returned';
    run.statusText = 'Returned';
    run.approvals = 0;
    run.changesCount = 0;
    run.trace = run.trace.map((event) => event.current ? Object.assign({}, event, { current: false }) : event);
    run.trace.push({ time: '09:42:40', kind: 'approval.rejected', title: 'Change rejected · run returned', meta: 'sha 9d07aa · no change released · audit 1,205', bad: true });
    state.auditSeq = 1205;
    state.auditEntries.unshift({ seq: 1205, action: 'approval.rejected', detail: 'sha 9d07aa · src/billing/webhook.py', actor: 'you', time: '09:42:40' });
    applyRun(state.currentRun);
    setView('trace', true);
    toast('<b>Rejected</b> · no change released · audit 1,205');
  }

  function renderPalette(query) {
    const q = query.trim().toLowerCase();
    const commands = [
      { group: 'Run', label: 'Open runs', meta: 'All sessions in orbit-api', short: 'S', action: () => openOverlay('sessions') },
      { group: 'Run', label: 'New run', meta: 'Name the outcome, choose a tier', short: 'N', action: () => openOverlay('launch') },
      { group: 'Run', label: 'Review pending change', meta: 'run_7f3a · sha 9d07aa', short: 'A', action: () => setView('changes') },
      { group: 'Run', label: 'Copy run id', meta: 'run_7f3a', short: '⌘⇧C', action: () => copyRunId() },
      { group: 'View', label: 'Open queue', meta: '1 waiting', short: 'Q', action: () => setView('queue') },
      { group: 'View', label: 'Open workspace files', meta: '~/work/orbit-api', short: 'F', action: () => setView('files') },
      { group: 'View', label: 'Open audit chain', meta: state.auditSeq.toLocaleString() + ' entries', short: 'G', action: () => openOverlay('audit') },
      { group: 'View', label: 'Show usage and budget', meta: '$3.84 / $12.00', short: '', action: () => openOverlay('usage') },
      { group: 'System', label: 'Change clearance', meta: 'restricted is the default', short: '', action: () => openOverlay('launch') },
      { group: 'System', label: 'Keyboard shortcuts', meta: 'Every action has a key path', short: '?', action: () => openOverlay('help') }
    ];
    const visible = commands.filter((command) => (command.label + ' ' + command.meta + ' ' + command.group).toLowerCase().includes(q));
    state.paletteCommands = visible;
    if (!visible.length) {
      el.paletteList.innerHTML = '<div class="palette-empty">No command matches “' + esc(query) + '”.</div>';
      return;
    }
    let html = '';
    let lastGroup = '';
    visible.forEach((command, index) => {
      if (command.group !== lastGroup) {
        html += '<div class="palette-group">' + command.group + '</div>';
        lastGroup = command.group;
      }
      html += '<button class="palette-item' + (index === state.paletteIndex ? ' on' : '') + '" type="button" data-cmd-index="' + index + '">' +
        icon('arrow', 13) + '<span>' + esc(command.label) + '</span><span class="short">' + (command.short ? esc(command.short) : '') + '</span></button>';
    });
    el.paletteList.innerHTML = html;
  }

  function executeCommand(command) {
    if (!command) return;
    closeAllOverlays(false);
    command.action();
  }

  function copyRunId() {
    const id = RUNS[state.currentRun].id;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(id).then(() => toast('Copied <b>' + id + '</b>.')).catch(() => toast('Run id: <b>' + id + '</b>'));
    } else {
      toast('Run id: <b>' + id + '</b>');
    }
  }

  function renderDrawer(kind) {
    const run = RUNS[state.currentRun];
    el.drawer.className = 'drawer';
    if (kind === 'audit') {
      el.drawerTitle.textContent = 'Audit chain';
      el.drawerSub.textContent = state.auditSeq.toLocaleString() + ' entries · verified';
      el.drawerBody.innerHTML = '<div class="audit-summary"><div><div class="big">' + state.auditSeq.toLocaleString() + '</div><div class="lbl">entries<br>hash-chained</div></div><span class="ok">' + icon('shield', 14) + 'verified</span></div>' +
        '<div class="chain">' + state.auditEntries.map((entry) => '<div class="chain-row"><span class="seq">' + entry.seq + '</span><span class="what"><b>' + esc(entry.action) + '</b><br>' + esc(entry.detail) + '</span><span class="when">' + entry.time + '</span><span class="hash">sha256: ' + esc((entry.seq * 2654435761 >>> 0).toString(16)) + 'c4e…</span></div>').join('') + '</div>' +
        '<div class="audit-foot"><button class="btn btn-sm" type="button" id="verify-chain">Verify chain</button><span style="font-family:var(--mono);font-size:12px;color:var(--muted)">last checked 09:42:11</span></div>';
    } else if (kind === 'usage') {
      el.drawerTitle.textContent = 'Usage';
      el.drawerSub.textContent = 'today · orbit-api';
      el.drawerBody.innerHTML = '<div class="context-block"><h3>Budget</h3><div class="kv"><span>Spent today</span><b>$3.84</b></div><div class="kv"><span>Daily cap</span><b>$12.00</b></div><div class="usage-bar"><i style="width:32%"></i></div><div class="kv"><span>Remaining</span><b>$8.16</b></div></div>' +
        '<div class="context-block"><h3>Runs</h3><div class="kv"><span>Completed</span><b>3</b></div><div class="kv"><span>Awaiting approval</span><b>1</b></div><div class="kv"><span>Queued</span><b>1</b></div></div>' +
        '<div class="context-block"><h3>Providers</h3><div class="kv"><span>anthropic · sonnet-4</span><b>$2.91</b></div><div class="kv"><span>anthropic · opus-4</span><b>$0.93</b></div></div>' +
        '<div class="context-block"><h3>Limits</h3><div class="kv"><span>Max spend per run</span><b>$2.00</b></div><div class="kv"><span>Max steps per run</span><b>30</b></div></div>';
    } else if (kind === 'context') {
      el.drawerTitle.textContent = 'Context';
      el.drawerSub.textContent = run.id + ' · ' + run.tier;
      el.drawerBody.innerHTML = '<div class="context-block"><h3>Workspace</h3><div class="kv"><span>Project</span><b>orbit-api</b></div><div class="kv"><span>Path</span><b>~/work/orbit-api</b></div><div class="kv"><span>Daemon</span><b>127.0.0.1:8765</b></div></div>' +
        '<div class="context-block"><h3>Clearance</h3><div class="kv"><span>Tier</span><b>' + run.tier + '</b></div><div class="kv"><span>Image</span><b>' + (run.tier === 'restricted' ? 'a91c4e' : run.tier === 'elevated' ? '02b7f1' : '7ce0aa') + '</b></div><div class="kv"><span>Network</span><b>' + (run.tier === 'restricted' ? 'none' : 'allowlisted') + '</b></div><div class="kv"><span>Model</span><b>' + run.model + '</b></div></div>' +
        '<div class="context-block"><h3>Attachments</h3><div class="kv"><span>Uploads</span><b>~/.local/share/smolcode/uploads</b></div><div class="kv"><span>Files</span><b>none for this run</b></div></div>' +
        '<div class="context-block"><h3>Subagents</h3><div class="subagent"><span class="dot"></span>No subagents running</div></div>' +
        '<div class="context-block"><h3>Approval</h3><div class="kv"><span>Bound to</span><b>sha 9d07aa</b></div><div class="kv"><span>Audit entry</span><b>' + state.auditSeq.toLocaleString() + '</b></div></div>';
    } else if (kind === 'project') {
      el.drawerTitle.textContent = 'Projects';
      el.drawerSub.textContent = 'local workspaces';
      el.drawerBody.innerHTML = '<div class="context-block"><h3>Current</h3><div class="kv"><span>orbit-api</span><b>~/work/orbit-api</b></div></div>' +
        '<div class="context-block"><h3>Recent</h3><div class="kv"><span>smolcode</span><b>~/work/smolcode</b></div><div class="kv"><span>design-lab</span><b>~/work/design-lab</b></div></div>' +
        '<div class="context-block"><button class="btn btn-sm" type="button" data-toast="Project picker is outside this prototype.">Add project</button></div>';
    } else {
      el.drawerTitle.textContent = 'Shortcuts';
      el.drawerSub.textContent = 'keyboard first';
      el.drawerBody.innerHTML = '<div class="context-block"><h3>Navigate</h3><ul class="mini-list"><li><span>Command palette</span><span class="mono">⌘K</span></li><li><span>Runs</span><span class="mono">S</span></li><li><span>New run</span><span class="mono">N</span></li><li><span>Trace / changes / console / files</span><span class="mono">1–4</span></li><li><span>Queue</span><span class="mono">Q</span></li><li><span>Audit chain</span><span class="mono">G</span></li></ul></div>' +
        '<div class="context-block"><h3>Act</h3><ul class="mini-list"><li><span>Review change</span><span class="mono">A</span></li><li><span>Start from composer</span><span class="mono">⌘↵</span></li><li><span>Close panel</span><span class="mono">Esc</span></li></ul></div>' +
        '<div class="context-block"><h3>Safety</h3><p style="color:var(--muted);font-size:12px;line-height:1.5">Approval is bound to one diff. A new change needs a new signature. The queue never drains itself.</p></div>';
    }
  }

  function applyHash() {
    const kind = location.hash.replace(/^#/, '');
    if (overlayKinds.includes(kind)) {
      openOverlay(kind, false);
      return;
    }
    closeAllOverlays(false);
    const view = kind === 'review' ? 'changes' : views.includes(kind) ? kind : 'trace';
    setView(view, false);
  }

  function updateLaunchTier(tier) {
    selectedTier = tier;
    $$('.tier-option').forEach((option) => {
      const on = option.dataset.tierChoice === tier;
      option.classList.toggle('on', on);
      option.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    el.tierNote.innerHTML = icon('shield', 14) + '<span>' + tierNotes[tier] + '</span>';
    el.composerTier.textContent = tier;
  }

  function startRun() {
    const text = el.launchTask.value.trim();
    if (!text) {
      el.launchTask.focus();
      toast('Name the outcome first. The run needs a target.');
      return;
    }
    const model = el.launchModel.value;
    closeAllOverlays();
    el.composerTier.textContent = selectedTier;
    el.composerModel.textContent = model.replace('claude-', '');
    toast('<b>Queued</b> · run_1a2b · ' + selectedTier + ' · ' + model + ' — behind run_7f3a');
  }

  function toggleDrain() {
    state.drainOn = !state.drainOn;
    const button = $('#drain-btn');
    if (button) button.textContent = state.drainOn ? 'Stop drain' : 'Drain queue';
    el.queueBadge.hidden = state.drainOn;
    toast(state.drainOn ? '<b>Draining</b> · queued runs will start one at a time.' : '<b>Drain off</b> · queued runs wait for you.');
  }

  // ---------- events ----------
  document.addEventListener('click', (event) => {
    const open = event.target.closest('[data-open]');
    if (open) {
      event.preventDefault();
      openOverlay(open.dataset.open);
      return;
    }

    const close = event.target.closest('[data-close]');
    if (close) {
      event.preventDefault();
      closeAllOverlays();
      return;
    }

    const runButton = event.target.closest('[data-run]');
    if (runButton) {
      event.preventDefault();
      selectRun(runButton.dataset.run);
      return;
    }

    const viewButton = event.target.closest('[data-view]');
    if (viewButton) {
      event.preventDefault();
      setView(viewButton.dataset.view);
      return;
    }

    const routeButton = event.target.closest('[data-route]');
    if (routeButton) {
      event.preventDefault();
      setView(routeButton.dataset.route);
      return;
    }

    const filter = event.target.closest('[data-filter]');
    if (filter) {
      state.sessionFilter = filter.dataset.filter;
      $$('.filter', el.sessionFilters).forEach((button) => button.classList.toggle('on', button === filter));
      renderSessions();
      return;
    }

    const tier = event.target.closest('[data-tier-choice]');
    if (tier) {
      updateLaunchTier(tier.dataset.tierChoice);
      return;
    }

    const commandButton = event.target.closest('[data-cmd-index]');
    if (commandButton) {
      const command = state.paletteCommands[Number(commandButton.dataset.cmdIndex)];
      executeCommand(command);
      return;
    }

    const toastButton = event.target.closest('[data-toast]');
    if (toastButton) {
      event.preventDefault();
      toast(toastButton.dataset.toast);
      return;
    }

    if (event.target.closest('#gate-approve')) {
      event.preventDefault();
      approveGate();
      return;
    }
    if (event.target.closest('#gate-hold')) {
      event.preventDefault();
      toast('Held. The sandbox stays alive at 09:42:11.');
      return;
    }
    if (event.target.closest('#gate-reject')) {
      event.preventDefault();
      rejectGate();
      return;
    }
    if (event.target.closest('#run-btn')) {
      event.preventDefault();
      submitComposer();
      return;
    }
    if (event.target.closest('#attach-btn')) {
      event.preventDefault();
      $('#file-input').click();
      return;
    }
    if (event.target.closest('#drain-btn')) {
      event.preventDefault();
      toggleDrain();
      return;
    }
    if (event.target.closest('#launch-start')) {
      event.preventDefault();
      startRun();
      return;
    }
    if (event.target.closest('#verify-chain')) {
      event.preventDefault();
      toast('Chain verified. <b>' + state.auditSeq.toLocaleString() + '</b> entries, no gaps.');
      return;
    }
    if (event.target === el.scrim) {
      closeAllOverlays();
    }
  });

  el.sessionSearch.addEventListener('input', (event) => {
    state.sessionQuery = event.target.value;
    renderSessions();
  });

  el.paletteSearch.addEventListener('input', (event) => {
    state.paletteIndex = 0;
    renderPalette(event.target.value);
  });

  $('#file-input').addEventListener('change', (event) => {
    const count = event.target.files ? event.target.files.length : 0;
    if (count) toast('<b>' + count + '</b> file' + (count === 1 ? '' : 's') + ' attached to the next run.');
    event.target.value = '';
  });

  $('#auto-approve').addEventListener('change', (event) => {
    if (event.target.checked) {
      toast('Auto-approve only covers safe restricted diffs. Elevated and full access still gate every change.');
    }
  });

  function submitComposer() {
    const text = el.composerInput.value.trim();
    if (!text) {
      el.composerInput.focus();
      toast('Describe the change first. A run needs an outcome.');
      return;
    }
    el.composerInput.value = '';
    toast('<b>Queued</b> · run_1a2b · ' + selectedTier + ' · behind run_7f3a');
  }

  el.composerInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submitComposer();
    }
  });

  el.paletteSearch.addEventListener('keydown', (event) => {
    const list = state.paletteCommands || [];
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      state.paletteIndex = Math.min(list.length - 1, state.paletteIndex + 1);
      renderPalette(el.paletteSearch.value);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      state.paletteIndex = Math.max(0, state.paletteIndex - 1);
      renderPalette(el.paletteSearch.value);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      executeCommand(list[state.paletteIndex]);
    }
  });

  document.addEventListener('keydown', (event) => {
    const anyOverlayOpen = !el.sessions.hidden || !el.launch.hidden || !el.palette.hidden || !el.drawer.hidden;
    if (event.key === 'Escape' && anyOverlayOpen) {
      event.preventDefault();
      closeAllOverlays();
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (el.palette.hidden) openOverlay('palette');
      else closeAllOverlays();
      return;
    }
    const target = event.target;
    const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT');
    if (typing || anyOverlayOpen) return;
    const key = event.key.toLowerCase();
    if (key === 's') { event.preventDefault(); openOverlay('sessions'); }
    else if (key === 'n') { event.preventDefault(); openOverlay('launch'); }
    else if (key === 'q') { event.preventDefault(); setView('queue'); }
    else if (key === 'g') { event.preventDefault(); openOverlay('audit'); }
    else if (key === 'f') { event.preventDefault(); setView('files'); }
    else if (key === 'a') { event.preventDefault(); setView('changes'); }
    else if (key === '?') { event.preventDefault(); openOverlay('help'); }
    else if (key === '1') { event.preventDefault(); setView('trace'); }
    else if (key === '2') { event.preventDefault(); setView('changes'); }
    else if (key === '3') { event.preventDefault(); setView('console'); }
    else if (key === '4') { event.preventDefault(); setView('files'); }
  });

  window.addEventListener('hashchange', applyHash);

  // ---------- boot ----------
  renderRail();
  renderSessions();
  applyRun(state.currentRun);
  applyHash();
  if (location.hash === '' || location.hash === '#') history.replaceState(null, '', '#trace');
})();