/* RAROC engine for the browser: a line-for-line port of src/raroc/engine.py + pricing.py,
 * extended with scenario levers. Parity with Python is enforced by tests/test_js_parity.py.
 * Works in the browser (window.RarocEngine) and in Node (module.exports).
 */
(function (root) {
  "use strict";

  // ---- statistics ----------------------------------------------------------------------
  function erfc(x) { // Numerical Recipes erfcc, fractional error < 1.2e-7
    const z = Math.abs(x), t = 1 / (1 + 0.5 * z);
    const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 +
      t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 +
      t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? r : 2 - r;
  }
  const normCdf = x => 0.5 * erfc(-x / Math.SQRT2);

  function normInv(p) { // Acklam, relative error < 1.2e-9
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.3577518672690, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const lo = 0.02425, hi = 1 - lo;
    let q, r;
    if (p < lo) {
      q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p > hi) {
      q = Math.sqrt(-2 * Math.log(1 - p));
      return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    q = p - 0.5; r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

  function interp(t, xs, ys) { // numpy.interp semantics (clamped ends)
    if (t <= xs[0]) return ys[0];
    const n = xs.length;
    if (t >= xs[n - 1]) return ys[n - 1];
    for (let i = 1; i < n; i++) {
      if (t <= xs[i]) return ys[i - 1] + (t - xs[i - 1]) / (xs[i] - xs[i - 1]) * (ys[i] - ys[i - 1]);
    }
    return ys[n - 1];
  }

  /** Basel corporate asset correlation, 12%-24% decreasing in PD. */
  function assetCorr(pd) {
    const w = (1 - Math.exp(-50 * pd)) / (1 - Math.exp(-50));
    return 0.12 * w + 0.24 * (1 - w);
  }

  /** Basel IRB corporate capital requirement K per unit of EAD (maturity capped at 5y by Basel). */
  function irbK(pd, lgd, maturity, confidence, maxMaturity = 5) {
    pd = clamp(pd, 0.0003, 0.9999);
    const m = clamp(maturity, 1, maxMaturity);
    const r = assetCorr(pd);
    const b = Math.pow(0.11852 - 0.05478 * Math.log(pd), 2);
    const cond = normCdf((normInv(pd) + Math.sqrt(r) * normInv(confidence)) / Math.sqrt(1 - r));
    return lgd * (cond - pd) * (1 + (m - 2.5) * b) / (1 - 1.5 * b);
  }

  /** Single-factor Z-shift, TTC -> point-in-time PD. Z = 0 reproduces TTC; Z < 0 = downturn. */
  function pitPd(pdTtc, z) {
    const pd = clamp(pdTtc, 1e-6, 0.9999), rho = assetCorr(pd);
    return normCdf(normInv(pd) - Math.sqrt(rho) * z);
  }

  function maturityBucket(m, buckets) {
    for (const b of buckets) if (m <= b) return b;
    return buckets[buckets.length - 1];
  }

  /** Economic capital per $1 EAD at 100% LGD from the calibrated factor table. */
  function ecapFactor(cfg, pd, maturity, industry) {
    const k = irbK(pd, 1, maturityBucket(maturity, cfg.ecapBuckets), cfg.ecapConfidence, cfg.ecapMaxMaturity);
    return k * cfg.ecapDiversification * (cfg.ecapIndustryMult[industry] ?? 1);
  }

  function ecapFactorTable(cfg) {
    return Object.keys(cfg.pd).map(r => ({ rating: +r, pd: cfg.pd[r],
      factors: cfg.ecapBuckets.map(m => irbK(cfg.pd[r], 1, m, cfg.ecapConfidence, cfg.ecapMaxMaturity) * cfg.ecapDiversification) }));
  }

  // ---- scenario --------------------------------------------------------------------------
  function baseModel(cfg) {
    return { capitalBasis: "economic", baselApproach: "AIRB", outputFloor: false, cet1Target: cfg.cet1Target,
             elPdBasis: "TTC", ecapMethod: "analytic", cycleShift: 0, cycleZ: { ...cfg.cycleZ } };
  }

  function baseScenario(cfg) {
    return {
      name: "Base case",
      hurdle: cfg.hurdle, taxRate: cfg.taxRate,
      rateShockBps: 0,
      depositBetas: { "Operating": 0.25, "Non-Operating": 0.60, "Time Deposit": 0.85 },
      scope: "ALL",               // "ALL", "KEY" or a relationship id
      ratingNotches: 0, lgdShockPts: 0, utilizationPts: 0,
      loanSpreadBps: 0, revolverSpreadBps: 0, unusedFeeBps: 0,
      depositBalancePct: 0, depositRateBps: 0, paymentsFeePct: 0,
      newDeals: [],
      model: baseModel(cfg),
    };
  }

  function rows(table) { // {fields, rows} -> array of objects
    const f = table.fields;
    return table.rows.map(r => { const o = {}; for (let i = 0; i < f.length; i++) o[f[i]] = r[i]; return o; });
  }

  function prepare(data) {
    const rels = rows(data.relationships);
    return {
      cfg: data.config,
      rels, relById: Object.fromEntries(rels.map(r => [r.relationship_id, r])),
      loans: rows(data.loans), revolvers: rows(data.revolvers), irds: rows(data.irds),
      deposits: rows(data.deposits), payments: rows(data.payments),
    };
  }

  // ---- account calculators ----------------------------------------------------------------
  function makeCtx(book, sc) {
    const cfg = book.cfg, shock = sc.rateShockBps / 1e4;
    const xs = cfg.ftpCurve.map(p => p[0]), ys = cfg.ftpCurve.map(p => p[1] + shock);
    const keySet = new Set(book.rels.filter(r => r.segment === "Key Relationship").map(r => r.relationship_id));
    const inScope = sc.scope === "ALL" ? () => true
      : sc.scope === "KEY" ? id => keySet.has(id) : id => id === sc.scope;
    const model = { ...baseModel(cfg), ...(sc.model || {}) };
    const industryOf = id => (book.relById[id] || {}).industry || "";
    return { cfg, sc, model, industryOf, shock, ftp: t => interp(t, xs, ys), inScope,
             ccr: cfg.capitalCreditRate + shock, hurdle: sc.hurdle, tax: sc.taxRate };
  }

  function finish(a, ctx) {
    const cfg = ctx.cfg, m = ctx.model;
    a.revenue = a.nii + a.fee;
    const revPos = Math.max(a.revenue, 0);
    a.opCapital = (a.opCapital || 0) + cfg.opRiskPct * revPos;
    a.econCapital = a.creditCapital + a.opCapital;
    a.rwa = (a.creditRwa || 0) + 12.5 * cfg.smaBicRate * revPos;
    a.regCapital = a.rwa * m.cet1Target;
    a.capital = m.capitalBasis === "regulatory" ? a.regCapital
      : m.capitalBasis === "max" ? Math.max(a.econCapital, a.regCapital) : a.econCapital;
    const pre = a.revenue - a.opex - a.el + ctx.ccr * a.capital;
    a.net = pre * (1 - ctx.tax);
    a.raroc = a.capital ? a.net / a.capital : null;
    a.eva = a.net - ctx.hurdle * a.capital;
    if (a.elLife == null) a.elLife = 0;
    return a;
  }

  /** EL (1-year + lifetime), economic capital and Basel credit RWA for a credit exposure. */
  function credit(a, o, ctx) {
    const cfg = ctx.cfg, m = ctx.model;
    const pdTtc = cfg.pd[String(o.rating)];
    const z = (m.cycleZ[o.industry] ?? 0) + m.cycleShift;
    const pdP = pitPd(pdTtc, z);
    a.pd = pdTtc; a.pdPit = pdP; a.lgd = o.lgd; a.industry = o.industry;
    a.el = (m.elPdBasis === "PIT" ? pdP : pdTtc) * o.lgd * a.ead;
    a.elLife = (1 - Math.pow(1 - pdP, Math.max(o.maturity, 1))) * o.lgd * a.ead;
    const kEc = m.ecapMethod === "factor"
      ? ecapFactor(cfg, pdTtc, o.maturity, o.industry) * o.lgd
      : irbK(pdTtc, o.lgd, o.maturity, cfg.confidence) * cfg.ecMultiplier;
    a.creditCapital = kEc * a.ead;
    const rwaSa = o.saRw * o.eadSa, pdReg = Math.max(pdTtc, cfg.irbPdFloor);
    let rwa;
    if (m.baselApproach === "SA") rwa = rwaSa;
    else if (m.baselApproach === "FIRB") rwa = irbK(pdReg, cfg.firbLgd[o.collateral], cfg.firbMaturity, cfg.confidence) * 12.5 * o.eadSa;
    else {
      const lgdDt = Math.max(cfg.downturnLgd[0] + cfg.downturnLgd[1] * o.lgd, cfg.airbLgdFloor[o.collateral]);
      rwa = irbK(pdReg, lgdDt, o.maturity, cfg.confidence) * 12.5 * a.ead;
    }
    if (m.outputFloor && m.baselApproach !== "SA") rwa = Math.max(rwa, cfg.outputFloor * rwaSa);
    a.creditRwa = rwa;
  }
  const saRw = (cfg, rating, subType) => subType === "CRE Term" ? cfg.saCreRw : cfg.saCorporateRw[String(rating)];

  function stressRating(r, id, ctx) {
    return ctx.inScope(id) ? clamp(Math.round(r + ctx.sc.ratingNotches), 1, 10) : r;
  }
  function stressLgd(l, id, ctx) {
    return ctx.inScope(id) ? clamp(l + ctx.sc.lgdShockPts / 100, 0, 1) : l;
  }

  function termLoan(l, ctx, isNew) {
    const cfg = ctx.cfg, s = ctx.inScope(l.relationship_id) && !isNew;
    const spread = l.spread + (s ? ctx.sc.loanSpreadBps / 1e4 : 0);
    const rating = isNew ? l.rating : stressRating(l.rating, l.relationship_id, ctx);
    const lgd = isNew ? cfg.lgd[l.collateral] : stressLgd(cfg.lgd[l.collateral], l.relationship_id, ctx);
    const lp = cfg.loanLiquidityPremium * Math.min(l.remaining_yrs, 5) / 5;
    const a = { id: l.account_id, rel: l.relationship_id, product: "Term Loan", subType: l.sub_type,
      exposure: l.balance, ead: l.balance, rating, rate: spread, rateLabel: "spread",
      nii: l.balance * (spread - lp), fee: l.balance * l.orig_fee_pct / l.tenor_yrs,
      opex: l.commitment * cfg.loanOpex };
    credit(a, { rating, lgd, maturity: l.remaining_yrs, eadSa: l.balance, collateral: l.collateral,
      saRw: saRw(cfg, rating, l.sub_type), industry: l.industry ?? ctx.industryOf(l.relationship_id) }, ctx);
    return finish(a, ctx);
  }

  function revolver(v, ctx, isNew) {
    const cfg = ctx.cfg, s = ctx.inScope(v.relationship_id) && !isNew;
    let balance = v.balance;
    if (s && ctx.sc.utilizationPts) balance = v.commitment * clamp(v.utilization + ctx.sc.utilizationPts / 100, 0, 1);
    const spread = v.spread + (s ? ctx.sc.revolverSpreadBps / 1e4 : 0);
    const unused = Math.max(v.unused_fee + (s ? ctx.sc.unusedFeeBps / 1e4 : 0), 0);
    const rating = isNew ? v.rating : stressRating(v.rating, v.relationship_id, ctx);
    const lgd = isNew ? cfg.lgd[v.collateral] : stressLgd(cfg.lgd[v.collateral], v.relationship_id, ctx);
    const undrawn = v.commitment - balance;
    const a = { id: v.account_id, rel: v.relationship_id, product: "Revolver", subType: v.sub_type,
      exposure: v.commitment, ead: balance + cfg.ccf * undrawn, rating, rate: spread, rateLabel: "spread",
      utilization: v.commitment ? balance / v.commitment : 0,
      nii: balance * (spread - cfg.loanLiquidityPremium * cfg.revolverDrawnLpFactor)
        - undrawn * cfg.revolverLiquidityPremium * cfg.revolverUndrawnLpFactor,
      fee: undrawn * unused + v.commitment * v.orig_fee_pct / v.tenor_yrs,
      opex: v.commitment * cfg.revolverOpex };
    credit(a, { rating, lgd, maturity: v.remaining_yrs, eadSa: balance + cfg.saCommitmentCcf * undrawn,
      collateral: v.collateral, saRw: saRw(cfg, rating, v.sub_type),
      industry: v.industry ?? ctx.industryOf(v.relationship_id) }, ctx);
    return finish(a, ctx);
  }

  function ird(t, ctx) {
    const cfg = ctx.cfg;
    // Client pays fixed: higher rates move value to the client, lowering the bank's MTM exposure
    const dv = t.sub_type === "Interest Rate Cap" ? 0 : (t.sub_type === "Collar" ? 0.5 : 1);
    const mtm = t.mtm - dv * t.notional * Math.min(t.remaining_yrs, 10) * 0.9 * ctx.shock;
    const addon = cfg.irdAddon.find(p => t.remaining_yrs <= p[0])[1];
    const rating = stressRating(t.rating, t.relationship_id, ctx);
    const lgd = stressLgd(cfg.irdLgd, t.relationship_id, ctx);
    const a = { id: t.account_id, rel: t.relationship_id, product: "Interest Rate Derivative", subType: t.sub_type,
      exposure: t.notional, ead: cfg.saccrAlpha * (Math.max(mtm, 0) + addon * t.notional), rating,
      rate: t.sales_credit_bps / 1e4, rateLabel: "sales credit", mtm,
      nii: 0, fee: t.notional * t.sales_credit_bps / 1e4, opex: cfg.irdOpexPerTrade };
    credit(a, { rating, lgd, maturity: t.remaining_yrs, eadSa: a.ead, collateral: "Unsecured",
      saRw: cfg.saCorporateRw[String(rating)], industry: ctx.industryOf(t.relationship_id) }, ctx);
    a.creditCapital *= cfg.cvaMultiplier;
    a.creditRwa *= cfg.cvaMultiplier;
    return finish(a, ctx);
  }

  function deposit(dp, ctx) {
    const cfg = ctx.cfg, s = ctx.inScope(dp.relationship_id), sc = ctx.sc;
    const balance = dp.balance * (s ? 1 + sc.depositBalancePct / 100 : 1);
    const beta = sc.depositBetas[dp.deposit_type] || 0;
    const ratePaid = Math.max(dp.rate_paid + beta * ctx.shock + (s ? sc.depositRateBps / 1e4 : 0), 0);
    const duration = cfg.depositDuration[dp.deposit_type] ?? dp.tenor_yrs;
    const h = cfg.runoff[dp.deposit_type];
    const ftpCredit = ctx.ftp(duration) * (1 - h) + h * ctx.ftp(0.25) * cfg.volatileFtpShare;
    const a = { id: dp.account_id, rel: dp.relationship_id, product: "Deposit", subType: dp.sub_type,
      depositType: dp.deposit_type, exposure: balance, ead: 0, rating: null, rate: ratePaid,
      rateLabel: "rate paid", ftpCredit, nii: balance * (ftpCredit - ratePaid), fee: 0,
      opex: balance * cfg.depositOpex, el: 0, creditCapital: 0, opCapital: balance * cfg.depositOpCapPct };
    return finish(a, ctx);
  }

  function payment(p, ctx) {
    const cfg = ctx.cfg, s = ctx.inScope(p.relationship_id);
    const gross = p.monthly_revenue * 12 * (s ? 1 + ctx.sc.paymentsFeePct / 100 : 1);
    const a = { id: p.account_id, rel: p.relationship_id, product: "Payments", subType: p.sub_type,
      exposure: gross, ead: 0, rating: null, rate: p.ecr_offset_pct, rateLabel: "ECR offset",
      nii: 0, fee: gross * (1 - p.ecr_offset_pct), opex: gross * cfg.paymentsCostToIncome,
      el: gross * cfg.paymentsLossRate, creditCapital: 0 };
    return finish(a, ctx);
  }

  // A proposed deal, in the same shape as a book row
  function dealRow(d, id) {
    const common = { account_id: id, relationship_id: d.rel, sub_type: "New " + d.product,
      tenor_yrs: d.tenor, remaining_yrs: d.tenor, spread: d.spread, rating: d.rating,
      collateral: d.collateral, orig_fee_pct: d.feePct };
    return d.product === "Revolver"
      ? { ...common, commitment: d.amount, utilization: d.utilization, balance: d.amount * d.utilization, unused_fee: d.unusedFee }
      : { ...common, balance: d.amount, commitment: d.amount };
  }
  function dealMetrics(d, ctx, id) {
    const row = dealRow(d, id || "NEW");
    return d.product === "Revolver" ? revolver(row, ctx, true) : termLoan(row, ctx, true);
  }

  // ---- aggregation ------------------------------------------------------------------------
  const LENDING = new Set(["Term Loan", "Revolver", "Interest Rate Derivative"]);
  const PRODUCTS = ["Term Loan", "Revolver", "Interest Rate Derivative", "Deposit", "Payments"];

  function blank() {
    return { n: 0, exposure: 0, ead: 0, revenue: 0, opex: 0, el: 0, elLife: 0, econCapital: 0, rwa: 0,
             regCapital: 0, capital: 0, net: 0, eva: 0 };
  }
  function add(t, a) {
    t.n++; t.exposure += a.exposure; t.ead += a.ead; t.revenue += a.revenue; t.opex += a.opex; t.el += a.el;
    t.elLife += a.elLife; t.econCapital += a.econCapital; t.rwa += a.rwa; t.regCapital += a.regCapital;
    t.capital += a.capital; t.net += a.net; t.eva += a.eva;
  }
  const ratio = t => { t.raroc = t.capital ? t.net / t.capital : null; return t; };

  function run(book, sc) {
    const ctx = makeCtx(book, sc);
    const accounts = [];
    for (const l of book.loans) accounts.push(termLoan(l, ctx));
    for (const v of book.revolvers) accounts.push(revolver(v, ctx));
    for (const t of book.irds) accounts.push(ird(t, ctx));
    for (const d of book.deposits) accounts.push(deposit(d, ctx));
    for (const p of book.payments) accounts.push(payment(p, ctx));
    (sc.newDeals || []).forEach((d, i) => {
      const a = dealMetrics(d, ctx, "NEW-" + (i + 1)); a.isNew = true; accounts.push(a);
    });

    const total = blank(), byProduct = Object.fromEntries(PRODUCTS.map(p => [p, blank()]));
    const byRel = {};
    for (const r of book.rels) byRel[r.relationship_id] = { ...r, all: blank(), lending: blank(),
      products: Object.fromEntries(PRODUCTS.map(p => [p, blank()])) };
    for (const a of accounts) {
      add(total, a); add(byProduct[a.product], a);
      const r = byRel[a.rel];
      add(r.all, a); add(r.products[a.product], a);
      if (LENDING.has(a.product)) add(r.lending, a);
    }
    ratio(total); PRODUCTS.forEach(p => ratio(byProduct[p]));
    for (const id in byRel) {
      const r = byRel[id]; ratio(r.all); ratio(r.lending); PRODUCTS.forEach(p => ratio(r.products[p]));
      r.meetsHurdle = r.all.raroc !== null && r.all.raroc >= sc.hurdle;
      r.watch = r.segment === "Key Relationship" && r.all.raroc !== null && r.all.raroc < book.cfg.watchList;
    }
    const relList = Object.values(byRel);
    return { ctx, accounts, total, byProduct, byRel, relList,
      belowHurdle: relList.filter(r => !r.meetsHurdle).length };
  }

  // ---- pricing (mirror of pricing.py) ----------------------------------------------------
  function solve(f, lo, hi) {
    for (let i = 0; i < 200 && hi - lo >= 1e-7; i++) {
      const mid = (lo + hi) / 2;
      if (f(mid) < 0) lo = mid; else hi = mid;
    }
    return hi;
  }

  function priceDeal(book, sc, result, deal) {
    const ctx = result.ctx, h = sc.hurdle;
    const at = s => dealMetrics({ ...deal, spread: s }, ctx);
    const standalone = solve(s => { const m = at(s); return m.net - h * m.capital; }, -0.05, 0.25);
    const out = { standalone };
    const rel = deal.rel && result.byRel[deal.rel];
    if (rel) {
      const ni = rel.all.net, ec = rel.all.capital;
      const relFloor = solve(s => { const m = at(s); return (ni + m.net) - h * (ec + m.capital); }, 0, 0.25);
      const pd = book.cfg.pd[String(deal.rating)];
      const costFloor = pd * book.cfg.lgd[deal.collateral] + book.cfg.loanLiquidityPremium + book.cfg.loanOpex;
      Object.assign(out, { relRarocBefore: ec ? ni / ec : null, relFloor, costFloor,
        relFloorBinding: relFloor > costFloor, recommended: Math.max(relFloor, costFloor) });
      out.concessionBps = (standalone - out.recommended) * 1e4;
    } else {
      out.recommended = standalone;
    }
    const m = at(out.recommended);
    out.atRecommended = { raroc: m.raroc, revenue: m.revenue, el: m.el, capital: m.capital, eva: m.eva };
    if (rel) out.relRarocAfter = (rel.all.net + m.net) / (rel.all.capital + m.capital);
    return out;
  }

  const api = { normCdf, normInv, irbK, assetCorr, pitPd, ecapFactor, ecapFactorTable, interp, baseModel,
    baseScenario, prepare, run, priceDeal, dealMetrics, PRODUCTS, LENDING };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RarocEngine = api;
})(typeof self !== "undefined" ? self : this);
