const dollar = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const state = { payload: null, benchmark: null, activePlan: 'delta' };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);
const money = (cents) => cents == null ? '—' : dollar.format(cents / 100);
const title = (value) => String(value ?? '').replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
const percent = (value) => `${(Number(value) * 100).toFixed(1)}%`;

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

function total(outcome, field) {
  return outcome.lines
    .filter((line) => line.result_kind === 'MODELED')
    .reduce((sum, line) => sum + (line[field] || 0), 0);
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2200);
}

function renderClaim(claim) {
  $('#claim-id').textContent = `${claim.claim_id} · ${title(claim.coverage_tier)}`;
  $('#claim-lines').innerHTML = claim.lines.map((line) => `<tr>
    <td><span class="order-index">${line.source_sequence}</span></td>
    <td><strong class="procedure-code">${escapeHtml(line.submitted_code)}</strong><small>Submitted procedure</small></td>
    <td><span class="class-chip">Class ${escapeHtml(line.service_class)}</span></td>
    <td><span class="network-chip">${title(line.network_state)}</span></td>
    <td>${escapeHtml(line.date_of_service)}</td>
    <td class="amount">${money(line.submitted_cents)}</td>
  </tr>`).join('');
}

function planLineSummary(line) {
  if (line.result_kind !== 'MODELED') {
    return `<div class="line-summary review"><div><span>${escapeHtml(line.line_id)}</span><strong>${escapeHtml(line.submitted_code)} · ${title(line.kind)}</strong></div><span>Review required</span></div>`;
  }
  return `<div class="line-summary"><div><span>${escapeHtml(line.line_id)}</span><strong>${escapeHtml(line.submitted_code)}${line.benefited_code !== line.submitted_code ? ` → ${escapeHtml(line.benefited_code)}` : ''}</strong></div><div><strong>${money(line.plan_pays_cents)}</strong><span>plan pays</span></div></div>`;
}

function renderPlanCards(payload) {
  const plans = ['delta', 'metlife'];
  $('#plan-cards').innerHTML = plans.map((plan) => {
    const outcome = payload.outcomes[plan];
    const meta = payload.plans[plan];
    const incomplete = outcome.result_kind !== 'COMPLETE';
    const planPay = total(outcome, 'plan_pays_cents');
    const memberPay = total(outcome, 'member_cost_share_cents');
    const abstention = outcome.lines.find((line) => line.result_kind === 'ABSTENTION');
    return `<article class="plan-card ${plan}" data-plan-card="${plan}">
      <div class="plan-accent"></div>
      <header>
        <div><span class="carrier-label">${escapeHtml(meta.carrier)}</span><h3>${escapeHtml(meta.label)}</h3><p>${escapeHtml(meta.spec_id)}</p></div>
        <span class="decision-badge ${incomplete ? 'review' : 'modeled'}"><i></i>${incomplete ? 'REVIEW REQUIRED' : 'MODELED'}</span>
      </header>
      <div class="primary-result">
        <span>Total plan payment</span>
        <strong>${money(planPay)}</strong>
        <small>on the frozen benchmark allowance</small>
      </div>
      <div class="secondary-result">
        <div><span>Member share</span><strong>${incomplete ? 'Withheld' : money(memberPay)}</strong></div>
        <div><span>Decision status</span><strong>${incomplete ? 'Scoped review' : 'Complete'}</strong></div>
      </div>
      <div class="card-lines">${outcome.lines.map(planLineSummary).join('')}</div>
      ${abstention ? `<div class="review-callout"><strong>${title(abstention.kind)}</strong><p>${escapeHtml(abstention.question)}</p></div>` : ''}
      <button class="inspect-button" data-inspect-plan="${plan}">Inspect ${escapeHtml(meta.carrier)} trace <span>→</span></button>
    </article>`;
  }).join('');

  $$('[data-inspect-plan]').forEach((button) => button.addEventListener('click', () => {
    state.activePlan = button.dataset.inspectPlan;
    renderTrace();
    renderEvidence();
    $('#trace').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  renderDivergence(payload);
}

function renderDivergence(payload) {
  const delta = payload.outcomes.delta;
  const metlife = payload.outcomes.metlife;
  const deltaPay = total(delta, 'plan_pays_cents');
  const metlifePay = total(metlife, 'plan_pays_cents');
  const gap = Math.abs(metlifePay - deltaPay);
  const bothComplete = delta.result_kind === 'COMPLETE' && metlife.result_kind === 'COMPLETE';
  if (!bothComplete) {
    $('#divergence-insight').innerHTML = `<span class="insight-mark">!</span><div><strong>A forced comparison would be dishonest.</strong><p>At least one plan needs scoped review, so ARBITER withholds the unresolved total while preserving every unaffected line.</p></div>`;
    return;
  }
  const higherPlan = metlifePay >= deltaPay ? payload.plans.metlife.label : payload.plans.delta.label;
  const leadExplanation = payload.case.case_id === 'B01'
    ? 'Delta’s shared annual maximum has only $50 left for the second crown. MetLife still pays $350 on that line.'
    : `${higherPlan} produces the higher modeled payment under the reviewed rules for this scenario.`;
  $('#divergence-insight').innerHTML = `<span class="insight-mark">${money(gap)}</span><div><strong>Same treatment, ${money(gap)} apart.</strong><p>${escapeHtml(leadExplanation)}</p></div><a href="#trace">See the rule sequence <span>↓</span></a>`;
  if (payload.case.case_id === 'B01') {
    $('#hero-delta-pay').textContent = money(deltaPay);
    $('#hero-metlife-pay').textContent = money(metlifePay);
    $('#hero-gap').textContent = `+${money(gap)}`;
  }
}

function effectValue(effect) {
  if (effect.value_unit === 'cents') return `${money(effect.before_value)} → ${money(effect.after_value)}`;
  if (effect.before_value == null) return String(effect.after_value ?? 'Applied');
  return `${effect.before_value} → ${effect.after_value}`;
}

function clauseButtons(effect) {
  return effect.acceptable_clause_ids.map((clauseId) => `<button class="clause-link" data-clause="${escapeHtml(clauseId)}">Source clause <span>↗</span></button>`).join('');
}

function renderTrace() {
  const plan = state.activePlan;
  const outcome = state.payload.outcomes[plan];
  $('#trace-tabs').innerHTML = Object.entries(state.payload.plans).map(([key, meta]) => {
    const pay = total(state.payload.outcomes[key], 'plan_pays_cents');
    return `<button role="tab" aria-selected="${key === plan}" data-plan="${key}"><span>${escapeHtml(meta.label)}</span><strong>${money(pay)}</strong></button>`;
  }).join('');
  $$('#trace-tabs button').forEach((button) => button.addEventListener('click', () => {
    state.activePlan = button.dataset.plan;
    renderTrace();
    renderEvidence();
  }));

  $('#trace-content').innerHTML = `<div class="trace-list">${outcome.lines.map((line) => {
    const result = line.result_kind === 'MODELED' ? `${money(line.plan_pays_cents)}` : 'Review';
    const effects = line.effects.map((effect, index) => `<li class="effect">
      <span class="effect-index">${String(index + 1).padStart(2, '0')}</span>
      <div class="effect-copy"><span class="effect-stage">${title(effect.stage)}</span><p>${escapeHtml(effect.description)}</p>${effect.assumption_ids.map((id) => `<span class="assumption">Assumption · ${escapeHtml(id)}</span>`).join('')}</div>
      <div class="effect-outcome"><strong>${escapeHtml(effectValue(effect))}</strong>${clauseButtons(effect)}</div>
    </li>`).join('');
    const abstention = line.result_kind === 'ABSTENTION' ? `<div class="abstention"><span>Decision withheld</span><strong>${title(line.kind)} · ${title(line.stage)}</strong><p>${escapeHtml(line.question)}</p>${line.required_document_kind ? `<small>Required evidence: ${escapeHtml(line.required_document_kind)}</small>` : ''}</div>` : '';
    return `<article class="trace-line">
      <header><div><span class="line-kicker">CLAIM LINE ${escapeHtml(line.line_id)}</span><h3>${escapeHtml(line.submitted_code)}${line.benefited_code !== line.submitted_code ? ` <i>→</i> ${escapeHtml(line.benefited_code)}` : ''}</h3><p>${line.result_kind === 'MODELED' ? `Allowed ${money(line.benchmark_allowed_cents)} · Member ${money(line.member_cost_share_cents)}` : 'No unresolved dollar amount is presented.'}</p></div><div class="trace-result"><strong>${result}</strong><span>${line.result_kind === 'MODELED' ? 'plan pays' : 'human review'}</span></div></header>
      <ol class="effect-list">${effects}</ol>${abstention}
    </article>`;
  }).join('')}</div>`;

  $$('.clause-link').forEach((button) => button.addEventListener('click', () => focusClause(button.dataset.clause)));
}

function evidenceId(plan, clauseId) {
  return `evidence-${plan}-${clauseId.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
}

function renderEvidence() {
  const plan = state.activePlan;
  const evidence = Object.values(state.payload.evidence[plan]);
  $('#evidence-content').innerHTML = evidence.length ? evidence.map((item) => `<article id="${evidenceId(plan, item.clause_id)}" class="evidence-card" data-clause-card="${escapeHtml(item.clause_id)}">
    <header><div><span class="source-dot"></span><strong>${escapeHtml(state.payload.plans[plan].carrier)} brochure</strong></div><span>PAGE ${item.page_number}</span></header>
    <blockquote>“${escapeHtml(item.quoted_text)}”</blockquote>
    <footer><code>${escapeHtml(item.clause_id)}</code><button class="copy-button" data-copy="${escapeHtml(item.quoted_text)}" aria-label="Copy quoted clause">Copy</button></footer>
  </article>`).join('') : '<div class="evidence-empty"><strong>No brochure sentence is being claimed here.</strong><p>This line uses a declared benchmark assumption or is waiting for a required evidence class.</p></div>';
  $$('.copy-button').forEach((button) => button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      showToast('Clause copied');
    } catch (_) {
      showToast('Copy is unavailable in this browser');
    }
  }));
}

function focusClause(clauseId) {
  renderEvidence();
  const card = document.getElementById(evidenceId(state.activePlan, clauseId));
  if (!card) {
    showToast('This effect uses a declared assumption, not a brochure clause');
    return;
  }
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  card.classList.remove('flash');
  window.requestAnimationFrame(() => card.classList.add('flash'));
}

function renderMeta(caseData) {
  $('#case-meta').innerHTML = `<div id="case-summary"><strong>${escapeHtml(caseData.case_id)} · ${escapeHtml(caseData.title)}</strong><span>${escapeHtml(caseData.thesis)}</span></div><div class="case-tags">${caseData.tags.slice(0, 4).map((tag) => `<span>${escapeHtml(title(tag))}</span>`).join('')}</div>`;
}

function findingCopy(example) {
  if (example.gold_state === 'ambiguous') {
    return {
      kicker: 'AMBIGUOUS LANGUAGE',
      verified: 'More than one reading survives the brochure.',
      action: 'Abstain only when the competing readings change this claim.'
    };
  }
  return {
    kicker: 'MISSING SOURCE',
    verified: 'The brochure does not contain enough evidence to decide.',
    action: 'Request the missing source before moving money.'
  };
}

function renderBenchmark(benchmark) {
  const delta = benchmark.metrics.delta;
  const metlife = benchmark.metrics.metlife;
  $('#benchmark-summary').innerHTML = `
    <article><span>MODEL UNDER TEST</span><strong>${escapeHtml(title(benchmark.model))}</strong><small>Vertex · structured extraction</small></article>
    <article><span>COMPLETED PASSES</span><strong>${benchmark.completed_calls}/${benchmark.requested_calls}</strong><small>Three independent runs per plan</small></article>
    <article class="risk"><span>UNSAFE ASSERTIONS</span><strong>${benchmark.unsafe_assertion_count}</strong><small>Across the three MetLife trials</small></article>
    <article><span>SAFE ABSTENTIONS</span><strong>${delta.safe_abstentions + metlife.safe_abstentions}</strong><small>The model never chose uncertainty</small></article>`;

  const unique = [...new Map(benchmark.unsafe_examples.map((item) => [item.gold_state, item])).values()];
  $('#benchmark-findings').innerHTML = unique.map((example) => {
    const copy = findingCopy(example);
    return `<article class="finding-card">
      <div class="finding-top"><span>${copy.kicker}</span><small>${escapeHtml(example.plan.toUpperCase())} · ${escapeHtml(example.trial.toUpperCase())}</small></div>
      <div class="claim-comparison">
        <div class="model-claim"><span>GEMINI ASSERTED</span><strong>${escapeHtml(title(example.model_value))}</strong><small>${escapeHtml(title(example.model_state))} · no abstention</small></div>
        <div class="verified-claim"><span>HUMAN-AUDITED SPEC</span><strong>${escapeHtml(title(example.gold_state))}</strong><small>${escapeHtml(copy.verified)}</small></div>
      </div>
      <div class="arbiter-action"><span>ARBITER ACTION</span><p>${escapeHtml(copy.action)}</p></div>
    </article>`;
  }).join('');
  $('#benchmark-run').textContent = `${benchmark.run_id} · ${percent(delta.coverage_rate)} Delta / ${percent(metlife.coverage_rate)} MetLife strict field coverage`;
}

async function loadCase(caseId) {
  const picker = $('#case-picker');
  picker.disabled = true;
  document.body.classList.add('is-loading');
  try {
    const payload = await api(`/api/case/${encodeURIComponent(caseId)}`);
    state.payload = payload;
    state.activePlan = 'delta';
    renderMeta(payload.case);
    renderClaim(payload.case.claim);
    renderPlanCards(payload);
    renderTrace();
    renderEvidence();
  } finally {
    picker.disabled = false;
    document.body.classList.remove('is-loading');
  }
}

async function boot() {
  const [list, benchmark] = await Promise.all([api('/api/cases'), api('/api/benchmark')]);
  state.benchmark = benchmark;
  renderBenchmark(benchmark);
  const picker = $('#case-picker');
  picker.innerHTML = list.cases.map((item) => `<option value="${item.case_id}">${item.demo_lead ? '★ ' : ''}${escapeHtml(item.case_id)} — ${escapeHtml(item.title)}</option>`).join('');
  picker.value = list.cases.find((item) => item.demo_lead)?.case_id || list.cases[0].case_id;
  picker.addEventListener('change', () => loadCase(picker.value));
  await loadCase(picker.value);
}

boot().catch((error) => {
  $('#main').innerHTML = `<section class="fatal-error wrap"><p class="eyebrow">ARBITER COULD NOT LOAD</p><h1>The local evidence service is unavailable.</h1><p>${escapeHtml(error.message)}</p><button onclick="window.location.reload()">Try again</button></section>`;
});
