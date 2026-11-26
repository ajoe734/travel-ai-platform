'use strict';
/**
 * backlog ENG-06 frontend regression checks for
 * prototypes/merchant-assistant/workbench/index.html. Run from the
 * repository root:
 *   node tests/workbench_frontend_test.cjs
 *
 * Same technique as tests/prototype-regression.cjs: executes the real
 * inline script with Node's `vm` and minimal DOM substitutes, no real
 * browser. The one addition this file needs is `fetch`, because the
 * workbench frontend talks to a server instead of holding fake state in
 * localStorage/setTimeout (docs/verification/prototype-audit.md §6.1,
 * §9). `FakeWorkbenchServer` below is a plain-JS mirror of
 * services/workbench/service.py's state machine, scoped to exactly what
 * this frontend calls -- it is a test harness fixture, NOT the real
 * backend and NOT a second implementation the product ships; the real
 * contract is specs/workbench/api-contract.md and services/workbench/.
 *
 * This verifies state changes and generated markup, NOT actual browser
 * clicks, visual layout, accessibility, or a real HTTP round trip.
 */
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const htmlPath = path.resolve(__dirname, '../prototypes/merchant-assistant/workbench/index.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const scriptBlocks = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/gi)];
if (scriptBlocks.length !== 1) throw new Error('Expected one inline workbench script');
const source = scriptBlocks[0][1];

const TENANT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const CHANNEL_DISPLAY = { NEW: 'not_started', VALIDATING: 'not_started', READY: 'not_started', EXECUTING: 'pending', WAITING: 'pending', UNKNOWN: 'pending', DONE: 'live', FAILED: 'rejected', CANCELLED: 'cancelled' };

function sortedKeysJson(obj) {
  // Stand-in canonicalization: good enough for a deterministic test hash,
  // not a claim of cross-language SD §3.2 compliance (that is
  // services/workbench/canonical_json.py's job on the real backend).
  return JSON.stringify(obj, Object.keys(obj).sort());
}

class FakeWorkbenchServer {
  constructor() {
    this.works = new Map();
    this.decisions = new Map();
    this.drafts = new Map();
    this.tasks = new Map(); // work_id -> { group: {...}, children: [{channel, status}] }
    this.seq = 0;
  }

  _id() { return 'id-' + (++this.seq); }

  propose(tenantId, caseId, actor, fields) {
    if (fields.capacity < 1 || fields.capacity > 8) throw httpError(422, 'INVALID_SERVICE_REVISION_FIELD', 'capacity out of range');
    if (fields.duration_minutes < 15 || fields.duration_minutes > 300) throw httpError(422, 'INVALID_SERVICE_REVISION_FIELD', 'duration out of range');
    if (Number(fields.price.amount_minor_units) < 1) throw httpError(422, 'INVALID_SERVICE_REVISION_FIELD', 'price must be positive');
    const workId = this._id();
    const work = { tenant_id: tenantId, id: workId, case_id: caseId, objective: '核准並發布服務改版：' + fields.name, status: 'WAITING_INPUT', missing_fields: ['asset_ref', 'rights_confirmed'] };
    this.works.set(workId, work);
    this.drafts.set(workId, fields);
    return work;
  }

  submitInput(tenantId, workId, body) {
    const draft = this.drafts.get(workId);
    if (body.asset_ref) { draft.asset_ref = body.asset_ref; draft.rights_confirmed = !!body.rights_confirmed; delete draft.asset_waived; }
    else if (body.asset_waived) { draft.asset_waived = true; delete draft.asset_ref; delete draft.rights_confirmed; }
    else if (body.rights_confirmed) { draft.rights_confirmed = true; }
    const work = this.works.get(workId);
    if (!draft.asset_ref && !draft.asset_waived) work.missing_fields = ['asset_ref', 'rights_confirmed'];
    else if (draft.asset_ref && !draft.rights_confirmed) work.missing_fields = ['rights_confirmed'];
    else work.missing_fields = [];
    return work;
  }

  requestDecision(tenantId, workId, body) {
    const draft = this.drafts.get(workId);
    const work = this.works.get(workId);
    if (work.missing_fields.length) throw httpError(422, 'MISSING_REQUIRED_INPUT', 'still missing input');
    if (!body || !body.expires_at) throw httpError(422, 'INVALID_SERVICE_REVISION_FIELD', 'expires_at is required per specs/workbench/api-contract.md');
    const decisionId = this._id();
    const payloadHash = 'hash-' + sortedKeysJson(draft).length + '-' + draft.content.length;
    const decision = {
      tenant_id: tenantId, id: decisionId, work_id: workId, status: 'PENDING', revision: 1,
      options: [{ option_id: 'approve', description: '核准並發布' }, { option_id: 'defer', description: '先不核准' }],
      display_payload: draft, payload_hash: payloadHash,
    };
    this.decisions.set(decisionId, decision);
    work.status = 'WAITING_DECISION';
    work.decision_id = decisionId;
    return { work, decision };
  }

  submitDecision(tenantId, decisionId, body) {
    const decision = this.decisions.get(decisionId);
    if (!decision) throw httpError(404, 'WORK_NOT_FOUND', 'no such decision');
    if (decision.status !== 'PENDING') throw httpError(409, 'DECISION_NOT_PENDING', 'already decided');
    if (decision.revision !== body.if_match_revision || decision.payload_hash !== body.if_match_payload_hash) {
      throw httpError(409, 'AUTHORIZATION_STALE', 'stale decision content');
    }
    decision.status = body.selected_option_id === 'approve' ? 'APPROVED' : 'REJECTED';
    const work = this.works.get(decision.work_id);
    if (decision.status === 'APPROVED') {
      work.status = 'RUNNING';
      this.tasks.set(work.id, { group: { status: 'EXECUTING' }, children: decision.display_payload.channels.map((c) => ({ channel: c, status: 'NEW' })) });
    } else {
      work.status = 'CANCELLED';
      work.cancellation_reason = '商家不核准此次改版';
    }
    return work;
  }

  // -- test-only: never reached through the frontend's fetch() calls -----
  advanceExecution(workId) {
    const entry = this.tasks.get(workId);
    if (!entry) return;
    for (const child of entry.children) {
      if (child.status === 'NEW') { child.status = 'WAITING'; continue; }
      if (child.status === 'WAITING' && child._review === 'LIVE_VERIFIED') { child.status = 'DONE'; continue; }
      if (child.status === 'WAITING' && child._review === 'REJECTED') { child.status = 'FAILED'; continue; }
      if (child.status === 'WAITING' && child._review === 'LOST') { child.status = 'UNKNOWN'; continue; }
      if (child.status === 'UNKNOWN' && child._review === 'LIVE_VERIFIED') { child.status = 'DONE'; continue; }
      if (child.status === 'UNKNOWN' && child._review === 'REJECTED') { child.status = 'FAILED'; continue; }
    }
    const work = this.works.get(workId);
    const statuses = entry.children.map((c) => c.status);
    if (statuses.every((s) => s === 'DONE')) { work.status = 'COMPLETED'; work.completed_at = 'TEST-COMPLETED-AT-2026-11-27T02:00:00Z'; }
    else if (statuses.some((s) => s === 'FAILED') && statuses.some((s) => s === 'DONE')) work.status = 'PARTIAL';
    else if (statuses.some((s) => s === 'WAITING' || s === 'UNKNOWN')) {
      work.status = 'WAITING_EXTERNAL';
      work.waiting_reason = statuses.some((s) => s === 'UNKNOWN') ? 'RESULT_UNKNOWN' : 'KNOWN_PENDING';
    }
  }

  simulateReview(workId, channel, outcome) {
    const entry = this.tasks.get(workId);
    const child = entry.children.find((c) => c.channel === channel);
    child._review = outcome;
  }

  workStatus(workId) {
    const work = this.works.get(workId);
    const entry = this.tasks.get(workId) || { children: [] };
    const channels = {};
    for (const child of entry.children) channels[child.channel] = CHANNEL_DISPLAY[child.status];
    return { status: work.status, channels, partial_summary: work.status === 'PARTIAL' ? {
      completed_items: entry.children.filter((c) => c.status === 'DONE').map((c) => c.channel),
      incomplete_items: entry.children.filter((c) => c.status !== 'DONE').map((c) => ({ item: c.channel, reason: 'channel rejected' })),
    } : undefined, failure: work.status === 'FAILED' ? { reason: 'all channels failed' } : undefined, cancellation: work.cancellation_reason ? { reason: work.cancellation_reason } : undefined,
      completion_record: work.status === 'COMPLETED' ? { completed_at: work.completed_at } : undefined,
      waiting_external: work.status === 'WAITING_EXTERNAL' ? { waiting_reason: work.waiting_reason } : undefined };
  }

  home(tenantId) {
    return [...this.works.values()].filter((w) => w.tenant_id === tenantId).map((work) => {
      if (work.status === 'WAITING_INPUT') return { work_id: work.id, status: work.status, objective: work.objective, missing_fields: work.missing_fields };
      if (work.status === 'WAITING_DECISION') {
        const decision = this.decisions.get(work.decision_id);
        return { work_id: work.id, status: work.status, objective: work.objective, decision_card: { decision_id: decision.id, revision: decision.revision, payload_hash: decision.payload_hash, display_payload: decision.display_payload } };
      }
      return { work_id: work.id, status: work.status, objective: work.objective, work_status: this.workStatus(work.id) };
    });
  }
}

function httpError(status, code, detail) { const e = new Error(detail); e.httpStatus = status; e.code = code; return e; }

function fetchFactory(server) {
  return async (url, opts) => {
    const u = new URL(url, 'http://workbench.invalid');
    const method = (opts && opts.method) || 'GET';
    const body = opts && opts.body ? JSON.parse(opts.body) : {};
    try {
      let payload;
      if (method === 'GET' && u.pathname === '/v1/workbench/home') payload = server.home(u.searchParams.get('tenant_id'));
      else if (method === 'POST' && u.pathname === '/v1/workbench/works') payload = server.propose(body.tenant_id, body.case_id, body.actor, body.fields);
      else if (method === 'POST' && /\/v1\/workbench\/works\/[^/]+\/input$/.test(u.pathname)) payload = server.submitInput(body.tenant_id, u.pathname.split('/')[4], body);
      else if (method === 'POST' && /\/v1\/workbench\/works\/[^/]+\/request-decision$/.test(u.pathname)) payload = server.requestDecision(body.tenant_id, u.pathname.split('/')[4], body);
      else if (method === 'POST' && /\/v1\/workbench\/decisions\/[^/]+\/submit$/.test(u.pathname)) payload = server.submitDecision(body.tenant_id, u.pathname.split('/')[4], body);
      else throw httpError(404, 'WORK_NOT_FOUND', 'unknown route');
      return { ok: true, status: 200, json: async () => payload };
    } catch (err) {
      return { ok: false, status: err.httpStatus || 500, json: async () => ({ code: err.code, detail: err.message }) };
    }
  };
}

function environment(server) {
  const elements = new Map();
  const events = {};
  function element(id) {
    if (!elements.has(id)) elements.set(id, { id, innerHTML: '', value: '', textContent: '' });
    return elements.get(id);
  }
  const document = {
    getElementById: element,
    addEventListener(kind, fn) { events[kind] = fn; },
  };
  const window = {};
  const context = vm.createContext({ document, window, fetch: fetchFactory(server), setInterval: () => 0, clearInterval() {}, console, URL, JSON });
  vm.runInContext(source, context, { filename: 'workbench/index.html#script', timeout: 1000 });
  return {
    context, api: window.workbench, e: element,
    click(dataset) { events.click({ preventDefault() {}, target: { closest: () => ({ dataset }) } }); },
  };
}

async function flush() { await new Promise((resolve) => setImmediate(resolve)); await new Promise((resolve) => setImmediate(resolve)); }

const checks = [];
function check(name, fn) {
  return fn().then((result) => checks.push({ name, ...result })).catch((e) => checks.push({ name, status: 'error', error: e.stack || e.message }));
}

const VALID_FIELDS = () => ({
  name: '60 分鐘品飲版', content: '原本的完整體驗保留。另做60分鐘品飲，兩款茶和一份茶點，不含沖泡實作。平日14:00，每人680元，最多6人。',
  price: { amount_minor_units: '68000', currency: 'TWD', currency_scale_ref: 'twd-v1' }, duration_minutes: 60, capacity: 6,
  available_times: '平日 14:00', onsite_note: '中文示範＋英文說明卡', channels: ['WEB', 'PARTNER'],
});

async function proposeViaForm(x, overrides = {}) {
  const f = { ...VALID_FIELDS(), ...overrides };
  x.e('wbContent').value = f.content;
  x.e('wbName').value = f.name;
  x.e('wbPrice').value = String(Number(f.price.amount_minor_units) / 100);
  x.e('wbDuration').value = String(f.duration_minutes);
  x.e('wbCapacity').value = String(f.capacity);
  x.e('wbTimes').value = f.available_times;
  x.e('wbOnsite').value = f.onsite_note;
  x.click({ act: 'propose' });
  await flush();
}

(async () => {
  await check('Pending status never renders as live until a terminal readback lands', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    await proposeViaForm(x);
    const workId = [...server.works.keys()][0];
    x.click({ act: 'waive-asset', work: workId });
    await flush();
    const home1 = server.home(TENANT_ID);
    x.click({ act: 'request-decision', work: home1[0].work_id });
    await flush();
    const home2 = server.home(TENANT_ID);
    const card = home2[0].decision_card;
    x.click({ act: 'decide', work: home2[0].work_id, decision: card.decision_id, option: 'approve', revision: String(card.revision), hash: card.payload_hash });
    await flush();

    const beforeDispatchHtml = x.e('homeList').innerHTML;
    const notLiveYet = !beforeDispatchHtml.includes('已生效');

    server.advanceExecution(workId); // dispatch tick, test-only
    await x.api.refresh();
    const afterDispatchHtml = x.e('homeList').innerHTML;
    const stillNotLiveWhilePending = !afterDispatchHtml.includes('已生效');

    server.simulateReview(workId, 'WEB', 'LIVE_VERIFIED');
    server.simulateReview(workId, 'PARTNER', 'LIVE_VERIFIED');
    server.advanceExecution(workId);
    await x.api.refresh();
    const afterReviewHtml = x.e('homeList').innerHTML;
    const nowLive = afterReviewHtml.includes('已生效');

    return { status: notLiveYet && stillNotLiveWhilePending && nowLive ? 'pass' : 'fail', notLiveYet, stillNotLiveWhilePending, nowLive };
  });

  await check('A second page load resumes the same work from the server, no localStorage', async () => {
    const server = new FakeWorkbenchServer();
    const x1 = environment(server);
    await flush();
    await proposeViaForm(x1);
    const workId = [...server.works.keys()][0];
    x1.click({ act: 'waive-asset', work: workId });
    await flush();

    // A fresh script execution against the SAME server state, exactly like
    // a browser reload hitting the same backend -- the workbench script
    // itself never persists anything client-side.
    const x2 = environment(server);
    await flush();
    const resumedHtml = x2.e('homeList').innerHTML;
    return { status: resumedHtml.includes('查看確認卡') ? 'pass' : 'fail', resumedHtml: resumedHtml.slice(0, 200) };
  });

  await check("Merchant's own text is shown verbatim, not a canned example", async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    const customText = '改成咖啡拉花體驗，兩杯咖啡，不含拉花教學。平日15:00，每人500元，最多4人。';
    await proposeViaForm(x, { content: customText, name: '咖啡拉花體驗', capacity: 4, duration_minutes: 45, price: { amount_minor_units: '50000', currency: 'TWD', currency_scale_ref: 'twd-v1' } });
    const workId = [...server.works.keys()][0];
    x.click({ act: 'waive-asset', work: workId });
    await flush();
    x.click({ act: 'request-decision', work: workId });
    await flush();
    const html = x.e('homeList').innerHTML;
    return { status: html.includes(customText) && !html.includes('兩款茶') ? 'pass' : 'fail' };
  });

  await check('Zero/over-cap capacity is rejected client-side before any network call', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    await proposeViaForm(x, { capacity: 0 });
    const zeroBlocked = server.works.size === 0 && x.e('proposeError').textContent.length > 0;
    await proposeViaForm(x, { capacity: 9 });
    const nineBlocked = server.works.size === 0 && x.e('proposeError').textContent.length > 0;
    await proposeViaForm(x, { capacity: 8 });
    const eightAccepted = server.works.size === 1;
    return { status: zeroBlocked && nineBlocked && eightAccepted ? 'pass' : 'fail', zeroBlocked, nineBlocked, eightAccepted };
  });

  await check('A hostile client bypassing the form still gets rejected by the server, not shown as success', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    let threw = false;
    try {
      await x.context.fetch('/v1/workbench/works', { method: 'POST', body: JSON.stringify({ tenant_id: TENANT_ID, case_id: {}, actor: {}, fields: { ...VALID_FIELDS(), capacity: 0 } }) }).then(async (res) => {
        if (!res.ok) throw Object.assign(new Error('rejected'), { status: res.status, body: await res.json() });
      });
    } catch (e) { threw = true; }
    return { status: threw && server.works.size === 0 ? 'pass' : 'fail' };
  });

  await check('Approving never renders a per-channel execute button', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    await proposeViaForm(x);
    const workId = [...server.works.keys()][0];
    x.click({ act: 'waive-asset', work: workId });
    await flush();
    x.click({ act: 'request-decision', work: workId });
    await flush();
    const home = server.home(TENANT_ID);
    const card = home[0].decision_card;
    x.click({ act: 'decide', work: home[0].work_id, decision: card.decision_id, option: 'approve', revision: String(card.revision), hash: card.payload_hash });
    await flush();
    const html = x.e('homeList').innerHTML;
    const hasExecuteButton = /data-act="[^"]*execute[^"]*"/.test(html);
    const onlyKnownActs = [...html.matchAll(/data-act="([^"]+)"/g)].every((m) => ['decide'].includes(m[1]));
    return { status: !hasExecuteButton && onlyKnownActs ? 'pass' : 'fail', hasExecuteButton };
  });

  await check('An asset that still needs rights confirmation offers a confirm button, not a dead-end request-decision', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    await proposeViaForm(x);
    const workId = [...server.works.keys()][0];
    // Provide the asset WITHOUT confirming rights in the same call -- this
    // is the two-step path missing_fields should report as
    // ['rights_confirmed'] only, not ['asset_ref', 'rights_confirmed'].
    await x.context.fetch(`/v1/workbench/works/${workId}/input`, { method: 'POST', body: JSON.stringify({ tenant_id: TENANT_ID, asset_ref: 'asset-demo-card' }) });
    await x.api.refresh();
    const htmlBeforeConfirm = x.e('homeList').innerHTML;
    const offersConfirmNotDeadEnd = htmlBeforeConfirm.includes('data-act="confirm-rights"') && !htmlBeforeConfirm.includes('data-act="request-decision"');

    x.click({ act: 'confirm-rights', work: workId });
    await flush();
    const htmlAfterConfirm = x.e('homeList').innerHTML;
    const reachedDecisionCard = htmlAfterConfirm.includes('data-act="decide"') || htmlAfterConfirm.includes('查看確認卡');
    return { status: offersConfirmNotDeadEnd && reachedDecisionCard ? 'pass' : 'fail', offersConfirmNotDeadEnd, reachedDecisionCard };
  });

  await check('An error banner survives the refresh() that follows it, and clears when a new action starts', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    await proposeViaForm(x);
    const workId = [...server.works.keys()][0];
    x.click({ act: 'waive-asset', work: workId });
    await flush();
    x.click({ act: 'request-decision', work: workId });
    await flush();
    const home = server.home(TENANT_ID);
    const card = home[0].decision_card;
    // Submit with a wrong hash to force AUTHORIZATION_STALE; handle()'s
    // catch sets the error and then calls refresh() -- the error must not
    // be wiped out by that same refresh().
    x.click({ act: 'decide', work: home[0].work_id, decision: card.decision_id, option: 'approve', revision: String(card.revision), hash: 'wrong-hash' });
    await flush();
    const errorSurvivesRefresh = x.e('globalError').textContent.length > 0;

    x.click({ act: 'waive-asset', work: workId }); // an unrelated action on the same work; harmless no-op server-side
    await flush();
    const errorClearedOnNextAction = x.e('globalError').textContent.length === 0;
    return { status: errorSurvivesRefresh && errorClearedOnNextAction ? 'pass' : 'fail', errorSurvivesRefresh, errorClearedOnNextAction };
  });

  await check('Incomplete-item reasons are escaped once, not double-encoded', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    await proposeViaForm(x, { channels: ['WEB', 'PARTNER'] });
    const workId = [...server.works.keys()][0];
    x.click({ act: 'waive-asset', work: workId });
    await flush();
    x.click({ act: 'request-decision', work: workId });
    await flush();
    const home = server.home(TENANT_ID);
    const card = home[0].decision_card;
    x.click({ act: 'decide', work: home[0].work_id, decision: card.decision_id, option: 'approve', revision: String(card.revision), hash: card.payload_hash });
    await flush();
    server.advanceExecution(workId);
    await x.api.refresh();
    server.simulateReview(workId, 'WEB', 'LIVE_VERIFIED');
    server.simulateReview(workId, 'PARTNER', 'REJECTED');
    server.advanceExecution(workId);
    await x.api.refresh();
    const html = x.e('homeList').innerHTML;
    return { status: html.includes('部分完成') && !html.includes('&amp;#39;') && !html.includes('&amp;quot;') ? 'pass' : 'fail' };
  });

  await check('A completed work shows its objective and completion evidence, a WAITING_EXTERNAL result-unknown is distinguished from known-pending', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    await proposeViaForm(x); // the frontend always proposes both WEB and PARTNER channels
    const workId = [...server.works.keys()][0];
    x.click({ act: 'waive-asset', work: workId });
    await flush();
    x.click({ act: 'request-decision', work: workId });
    await flush();
    const home = server.home(TENANT_ID);
    const card = home[0].decision_card;
    const objective = home[0].objective;
    x.click({ act: 'decide', work: home[0].work_id, decision: card.decision_id, option: 'approve', revision: String(card.revision), hash: card.payload_hash });
    await flush();

    server.advanceExecution(workId); // dispatch -> WAITING
    await x.api.refresh();
    const runningHtml = x.e('homeList').innerHTML;
    const objectiveShownWhileRunning = runningHtml.includes(objective);

    // WEB's upstream response is lost (UNKNOWN); PARTNER has not been
    // reviewed at all yet (still WAITING) -- the mix must surface as
    // RESULT_UNKNOWN, not be flattened into the ordinary pending message.
    server.simulateReview(workId, 'WEB', 'LOST');
    server.advanceExecution(workId); // -> WAITING_EXTERNAL / RESULT_UNKNOWN
    await x.api.refresh();
    const unknownPendingHtml = x.e('homeList').innerHTML;
    const showsResultUnknown = unknownPendingHtml.includes('結果尚未確認');

    server.simulateReview(workId, 'WEB', 'LIVE_VERIFIED');
    server.simulateReview(workId, 'PARTNER', 'LIVE_VERIFIED');
    server.advanceExecution(workId); // -> COMPLETED
    await x.api.refresh();
    const completedHtml = x.e('homeList').innerHTML;
    const showsCompletionEvidence = completedHtml.includes('TEST-COMPLETED-AT-2026-11-27T02:00:00Z') && completedHtml.includes(objective);

    return {
      status: objectiveShownWhileRunning && showsResultUnknown && showsCompletionEvidence ? 'pass' : 'fail',
      objectiveShownWhileRunning, showsResultUnknown, showsCompletionEvidence,
    };
  });

  await check('request-decision sends expires_at per specs/workbench/api-contract.md', async () => {
    const server = new FakeWorkbenchServer();
    const x = environment(server);
    await flush();
    await proposeViaForm(x);
    const workId = [...server.works.keys()][0];
    x.click({ act: 'waive-asset', work: workId });
    await flush();
    x.click({ act: 'request-decision', work: workId });
    await flush();
    // FakeWorkbenchServer.requestDecision throws INVALID_SERVICE_REVISION_FIELD
    // if expires_at is missing; reaching WAITING_DECISION proves it was sent.
    const home = server.home(TENANT_ID);
    return { status: home[0].status === 'WAITING_DECISION' ? 'pass' : 'fail', status_seen: home[0].status };
  });

  console.log('Workbench frontend regression: Node VM with minimal DOM + fetch mock; NOT browser E2E, NOT the real backend.');
  for (const result of checks) {
    console.log('[' + result.status.toUpperCase() + '] ' + result.name);
    if (result.status !== 'pass') console.log(JSON.stringify(result, null, 2));
  }
  const failures = checks.filter((c) => c.status !== 'pass');
  console.log(JSON.stringify({ checks: checks.length, passed: checks.length - failures.length, failed: failures.length }, null, 2));
  if (failures.length) process.exitCode = 1;
})();
