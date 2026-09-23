/* Interactive RAROC app: overview, relationships, accounts, scenarios & deal pricing. */
(function () {
  "use strict";
  const E = window.RarocEngine, D = window.RAROC_DATA;
  const book = E.prepare(D);
  const BASE = E.baseScenario(book.cfg);
  const base = E.run(book, BASE);
  let sc = clone(BASE), cur = base;

  const KEY_IDS = book.rels.filter(r => r.segment === "Key Relationship").map(r => r.relationship_id);
  const PRODUCTS = E.PRODUCTS;
  const PROD_COLOR = { "Term Loan": "--s1", "Revolver": "--s2", "Interest Rate Derivative": "--s3", "Deposit": "--s4", "Payments": "--s5" };
  const PAGE = 50;
  const ui = {
    tab: "overview", relId: null,
    rels: { q: "", seg: "all", below: false, sort: "eva", dir: -1, page: 0 },
    accs: { q: "", product: "all", seg: "all", below: false, sort: "eva", dir: 1, page: 0 },
    relAccs: { sort: "product", dir: 1, page: 0 },
    deal: { rel: "R007", product: "Revolver", amountM: 40, tenor: 3, rating: 7, collateral: "Unsecured",
            utilPct: 30, unusedBps: 25, feeBps: 50, spreadBps: null },
  };

  // ---- helpers ------------------------------------------------------------------------
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  /** Fill in any model keys missing from an older saved or shared scenario. */
  function normalise() {
    sc.model = { ...E.baseModel(book.cfg), ...(sc.model || {}) };
    sc.model.cycleZ = { ...book.cfg.cycleZ, ...(sc.model.cycleZ || {}) };
    if (!Array.isArray(sc.newDeals)) sc.newDeals = [];
  }
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v, d = 1) => v == null || !isFinite(v) ? "–" : (v * 100).toFixed(d) + "%";
  const bps = v => v == null || !isFinite(v) ? "–" : Math.round(v * 1e4) + " bps";
  const money = v => {
    if (v == null || !isFinite(v)) return "–";
    const a = Math.abs(v), s = v < 0 ? "−$" : "$";
    if (a >= 1e9) return s + (a / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return s + (a / 1e6).toFixed(1) + "M";
    if (a >= 1e3) return s + (a / 1e3).toFixed(0) + "K";
    return s + a.toFixed(0);
  };
  const ptsDelta = (a, b) => {
    if (a == null || b == null) return "";
    const d = (b - a) * 100;
    if (Math.abs(d) < 0.05) return `<span class="note">no change</span>`;
    return `<span class="${d > 0 ? "delta-up" : "delta-down"}">${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} pts</span>`;
  };
  const moneyDelta = (a, b, upGood = true) => {
    const d = b - a;
    if (Math.abs(d) < 500) return `<span class="note">no change</span>`;
    const good = upGood ? d > 0 : d < 0;
    return `<span class="${good ? "delta-up" : "delta-down"}">${d > 0 ? "+" : "−"}${money(Math.abs(d)).replace("$", "$")}</span>`;
  };
  const relName = id => book.relById[id] ? book.relById[id].name : id;
  const isScenario = () => {
    const a = clone(sc), b = clone(BASE); delete a.name; delete b.name;
    return JSON.stringify(a) !== JSON.stringify(b);
  };
  function statusOf(r) {
    if (!r.meetsHurdle) return ["var(--critical)", "Below hurdle"];
    if (r.watch) return ["var(--warning)", "Watch list"];
    return ["var(--good)", "Meets hurdle"];
  }
  const statusHtml = r => { const [c, t] = statusOf(r); return `<span class="status"><i style="background:${c}"></i>${t}</span>`; };
  function rateText(a) {
    if (a.product === "Term Loan" || a.product === "Revolver") return bps(a.rate) + " spread";
    if (a.product === "Interest Rate Derivative") return bps(a.rate) + " credit";
    if (a.product === "Deposit") return pct(a.rate, 2) + " paid";
    return pct(a.rate, 0) + " ECR";
  }

  // tooltip
  const tip = $("#tip");
  function showTip(evt, html) {
    tip.innerHTML = html; tip.style.opacity = 1;
    const x = Math.min(evt.pageX + 14, window.scrollX + document.documentElement.clientWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px"; tip.style.top = (evt.pageY + 14) + "px";
  }
  const hideTip = () => { tip.style.opacity = 0; };

  // svg
  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent, text) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function hover(node, html) {
    node.addEventListener("mousemove", e => showTip(e, html));
    node.addEventListener("mouseleave", hideTip);
  }
  const barPath = (x, y, w, h) => w <= 4 ? `M${x},${y} h${w} v${h} h${-w} z`
    : `M${x},${y} h${w - 4} a4,4 0 0 1 4,4 v${h - 8} a4,4 0 0 1 -4,4 h${-(w - 4)} z`;

  // ---- charts ---------------------------------------------------------------------------
  function productChart(svg) {
    svg.innerHTML = "";
    const rows = PRODUCTS.map(p => ({ p, s: cur.byProduct[p], b: base.byProduct[p] })).sort((a, b) => a.s.raroc - b.s.raroc);
    const W = 1000, rowH = 40, top = 8, left = 190, right = 90, H = top + rows.length * rowH + 28;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const maxV = Math.max(...rows.map(r => Math.max(r.s.raroc, r.b.raroc)), sc.hurdle);
    const max = Math.ceil(maxV * 2) / 2;
    const x = v => left + (Math.max(v, 0) / max) * (W - left - right);
    for (let t = 0; t <= max + 1e-9; t += 0.5) {
      el("line", { x1: x(t), x2: x(t), y1: top, y2: H - 24, stroke: "var(--grid)" }, svg);
      el("text", { x: x(t), y: H - 6, "text-anchor": "middle", class: "tick" }, svg, pct(t, 0));
    }
    const showBase = isScenario();
    rows.forEach((r, i) => {
      const y = top + i * rowH + 10, h = 20, w = Math.max(x(r.s.raroc) - left, 2);
      el("text", { x: left - 12, y: y + 15, "text-anchor": "end" }, svg, r.p);
      el("path", { d: barPath(left, y, w, h), fill: "var(--s1)" }, svg);
      if (showBase) el("rect", { x: x(r.b.raroc) - 1.5, y: y - 3, width: 3, height: h + 6, rx: 1, fill: "var(--ink)" }, svg);
      el("text", { x: left + w + 8, y: y + 15, style: "fill:var(--ink)" }, svg, pct(r.s.raroc));
      const hit = el("rect", { x: 0, y: y - 8, width: W, height: rowH, fill: "transparent" }, svg);
      hover(hit, `<b>${esc(r.p)}</b>RAROC ${pct(r.s.raroc)}${showBase ? ` (base ${pct(r.b.raroc)})` : ""}<br>${r.s.n.toLocaleString()} accounts · capital ${money(r.s.capital)}<br>Net income ${money(r.s.net)} · EVA ${money(r.s.eva)}`);
    });
    el("line", { x1: x(sc.hurdle), x2: x(sc.hurdle), y1: top - 4, y2: H - 24, stroke: "var(--hurdle)", "stroke-width": 1.5, "stroke-dasharray": "4 3" }, svg);
    el("text", { x: x(sc.hurdle) + 6, y: top + 4, class: "tick" }, svg, pct(sc.hurdle, 0) + " hurdle");
  }

  function dumbbellChart(svg, onPick) {
    svg.innerHTML = "";
    const rows = KEY_IDS.map(id => cur.byRel[id]).sort((a, b) => b.all.raroc - a.all.raroc);
    const W = 1000, rowH = 34, top = 8, left = 240, right = 70, H = top + rows.length * rowH + 28;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const max = Math.ceil(Math.max(...rows.map(r => Math.max(r.all.raroc, r.lending.raroc)), sc.hurdle) * 10) / 10;
    const x = v => left + (Math.max(v, 0) / max) * (W - left - right);
    const step = max > 0.6 ? 0.1 : 0.05;
    for (let t = 0; t <= max + 1e-9; t += step) {
      el("line", { x1: x(t), x2: x(t), y1: top, y2: H - 24, stroke: "var(--grid)" }, svg);
      el("text", { x: x(t), y: H - 6, "text-anchor": "middle", class: "tick" }, svg, pct(t, 0));
    }
    el("line", { x1: x(sc.hurdle), x2: x(sc.hurdle), y1: top - 4, y2: H - 24, stroke: "var(--hurdle)", "stroke-width": 1.5, "stroke-dasharray": "4 3" }, svg);
    rows.forEach((r, i) => {
      const y = top + i * rowH + rowH / 2;
      const flag = !r.meetsHurdle || r.watch;
      el("text", { x: left - 12, y: y + 4, "text-anchor": "end", style: flag ? "fill:var(--ink);font-weight:600" : "" }, svg, (flag ? "⚠ " : "") + r.name);
      el("line", { x1: x(r.lending.raroc), x2: x(r.all.raroc), y1: y, y2: y, stroke: "var(--axis)", "stroke-width": 3 }, svg);
      el("circle", { cx: x(r.lending.raroc), cy: y, r: 6, fill: "var(--s1)", stroke: "var(--surface)", "stroke-width": 2 }, svg);
      el("circle", { cx: x(r.all.raroc), cy: y, r: 6, fill: "var(--s2)", stroke: "var(--surface)", "stroke-width": 2 }, svg);
      el("text", { x: x(Math.max(r.all.raroc, r.lending.raroc)) + 12, y: y + 4, style: "fill:var(--ink)" }, svg, pct(r.all.raroc));
      const hit = el("rect", { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: "transparent", style: "cursor:pointer" }, svg);
      hover(hit, `<b>${esc(r.name)}</b>Relationship RAROC ${pct(r.all.raroc)}<br>Lending-only RAROC ${pct(r.lending.raroc)}<br>Uplift from deposits + payments ${ptsDelta(r.lending.raroc, r.all.raroc)}<br>EVA ${money(r.all.eva)}<br><i>Click to open</i>`);
      hit.addEventListener("click", () => onPick(r.relationship_id));
    });
  }

  function mixChart(svg, legendEl) {
    svg.innerHTML = ""; legendEl.innerHTML = "";
    PRODUCTS.forEach(p => legendEl.insertAdjacentHTML("beforeend", `<span><i class="sw" style="background:var(${PROD_COLOR[p]})"></i>${esc(p)}</span>`));
    const rows = KEY_IDS.map(id => cur.byRel[id]).sort((a, b) => b.all.raroc - a.all.raroc);
    const W = 1000, rowH = 30, left = 240, right = 20, top = 4, H = top + rows.length * rowH + 24;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const span = W - left - right;
    [0, .25, .5, .75, 1].forEach(t => el("text", { x: left + t * span, y: H - 4, "text-anchor": "middle", class: "tick" }, svg, pct(t, 0)));
    rows.forEach((r, i) => {
      const y = top + i * rowH + 5, h = 20;
      const total = PRODUCTS.reduce((s, p) => s + Math.max(r.products[p].revenue, 0), 0);
      el("text", { x: left - 12, y: y + 15, "text-anchor": "end" }, svg, r.name);
      let cx = left;
      PRODUCTS.forEach(p => {
        const v = Math.max(r.products[p].revenue, 0), w = total ? v / total * span : 0;
        if (w <= 0) return;
        const seg = el("rect", { x: cx + 1, y, width: Math.max(w - 2, 0.5), height: h, rx: 3, fill: `var(${PROD_COLOR[p]})` }, svg);
        hover(seg, `<b>${esc(r.name)}</b>${esc(p)}: ${money(v)} (${pct(v / total)})`);
        cx += w;
      });
    });
  }

  function compareChart(svg) {
    svg.innerHTML = "";
    const rows = KEY_IDS.map(id => ({ r: cur.byRel[id], b: base.byRel[id] })).sort((a, b) => b.b.all.raroc - a.b.all.raroc);
    const W = 1000, rowH = 38, top = 8, left = 240, right = 70, H = top + rows.length * rowH + 28;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const max = Math.ceil(Math.max(...rows.map(o => Math.max(o.r.all.raroc, o.b.all.raroc)), sc.hurdle) * 10) / 10;
    const x = v => left + (Math.max(v, 0) / max) * (W - left - right);
    const step = max > 0.6 ? 0.1 : 0.05;
    for (let t = 0; t <= max + 1e-9; t += step) {
      el("line", { x1: x(t), x2: x(t), y1: top, y2: H - 24, stroke: "var(--grid)" }, svg);
      el("text", { x: x(t), y: H - 6, "text-anchor": "middle", class: "tick" }, svg, pct(t, 0));
    }
    rows.forEach((o, i) => {
      const y = top + i * rowH + 4, h = 13;
      el("text", { x: left - 12, y: y + 17, "text-anchor": "end" }, svg, o.r.name);
      [[o.b.all.raroc, "--s1", 0], [o.r.all.raroc, "--s2", h + 2]].forEach(([v, c, dy]) => {
        const w = Math.max(x(v) - left, 2);
        el("path", { d: barPath(left, y + dy, w, h), fill: `var(${c})` }, svg);
      });
      el("text", { x: x(Math.max(o.r.all.raroc, o.b.all.raroc)) + 8, y: y + 17, style: "fill:var(--ink)" }, svg, pct(o.r.all.raroc));
      const hit = el("rect", { x: 0, y: y - 4, width: W, height: rowH, fill: "transparent" }, svg);
      hover(hit, `<b>${esc(o.r.name)}</b>Base ${pct(o.b.all.raroc)} → scenario ${pct(o.r.all.raroc)} (${ptsDelta(o.b.all.raroc, o.r.all.raroc)})<br>EVA ${money(o.b.all.eva)} → ${money(o.r.all.eva)}`);
    });
    el("line", { x1: x(sc.hurdle), x2: x(sc.hurdle), y1: top - 4, y2: H - 24, stroke: "var(--hurdle)", "stroke-width": 1.5, "stroke-dasharray": "4 3" }, svg);
  }

  // ---- generic sortable table ---------------------------------------------------------------
  function sortRows(list, key, dir, getters) {
    const g = getters[key];
    return list.slice().sort((a, b) => {
      const va = g(a), vb = g(b);
      if (typeof va === "string") return dir * va.localeCompare(vb);
      return dir * ((va ?? -Infinity) - (vb ?? -Infinity));
    });
  }
  function header(cols, st) {
    return "<thead><tr>" + cols.map(c => {
      const cls = [c.left ? "l" : "", c.sort ? "sortable" : ""].join(" ").trim();
      const arrow = c.sort && st.sort === c.sort ? `<span class="arrow">${st.dir > 0 ? "▲" : "▼"}</span>` : "";
      const aria = c.sort && st.sort === c.sort ? ` aria-sort="${st.dir > 0 ? "ascending" : "descending"}"` : "";
      return `<th class="${cls}" ${c.sort ? `data-sort="${c.sort}" tabindex="0"` : ""}${aria}>${c.label}${arrow}</th>`;
    }).join("") + "</tr></thead>";
  }
  function bindSort(table, st, render) {
    table.querySelectorAll("th[data-sort]").forEach(th => {
      const go = () => {
        const k = th.dataset.sort;
        if (st.sort === k) st.dir = -st.dir; else { st.sort = k; st.dir = ["name", "id", "product", "rel", "industry", "segment"].includes(k) ? 1 : -1; }
        st.page = 0; render();
      };
      th.addEventListener("click", go);
      th.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
  }
  function pager(container, st, total, render) {
    const pages = Math.max(1, Math.ceil(total / PAGE));
    st.page = Math.min(st.page, pages - 1);
    const div = document.createElement("div"); div.className = "pager";
    div.innerHTML = `<span>${total ? st.page * PAGE + 1 : 0}–${Math.min((st.page + 1) * PAGE, total)} of ${total.toLocaleString()}</span>
      <button type="button" data-p="-1" ${st.page === 0 ? "disabled" : ""}>Previous</button>
      <button type="button" data-p="1" ${st.page >= pages - 1 ? "disabled" : ""}>Next</button>`;
    div.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { st.page += +b.dataset.p; render(); }));
    container.appendChild(div);
  }

  // accounts table (shared by Accounts tab and relationship detail)
  const ACC_COLS = [
    { label: "Account", sort: "id", left: true }, { label: "Relationship", sort: "rel", left: true },
    { label: "Product", sort: "product", left: true }, { label: "Type", left: true },
    { label: "Rating", sort: "rating" }, { label: "Exposure", sort: "exposure" }, { label: "Pricing" },
    { label: "Revenue", sort: "revenue" }, { label: "Exp. loss", sort: "el" }, { label: "Capital", sort: "capital" },
    { label: "Net income", sort: "net" }, { label: "RAROC", sort: "raroc" }, { label: "EVA", sort: "eva" },
  ];
  const ACC_GET = {
    id: a => a.id, rel: a => relName(a.rel), product: a => a.product, rating: a => a.rating ?? 0,
    exposure: a => a.exposure, revenue: a => a.revenue, el: a => a.el, capital: a => a.capital,
    net: a => a.net, raroc: a => a.raroc, eva: a => a.eva,
  };
  function accountRows(list, showRel) {
    return list.map(a => `<tr class="${a.isNew ? "new" : ""}">
      <td class="l">${esc(a.id)}${a.isNew ? ' <span class="sub-id">proposed</span>' : ""}</td>
      ${showRel ? `<td class="l"><a href="#/relationships/${esc(a.rel)}">${esc(relName(a.rel))}</a></td>` : ""}
      <td class="l">${esc(a.product)}</td><td class="l">${esc(a.subType)}</td>
      <td>${a.rating ?? "–"}</td><td>${money(a.exposure)}</td><td>${rateText(a)}</td>
      <td>${money(a.revenue)}</td><td>${money(a.el)}</td><td>${money(a.capital)}</td>
      <td>${money(a.net)}</td><td><b>${pct(a.raroc)}</b></td><td>${money(a.eva)}</td></tr>`).join("");
  }
  function renderAccountTable(container, list, st, showRel, rerender) {
    const cols = showRel ? ACC_COLS : ACC_COLS.filter(c => c.sort !== "rel");
    const sorted = sortRows(list, st.sort, st.dir, ACC_GET);
    const page = sorted.slice(st.page * PAGE, (st.page + 1) * PAGE);
    const wrap = document.createElement("div"); wrap.className = "table-wrap";
    wrap.innerHTML = `<table>${header(cols, st)}<tbody>${accountRows(page, showRel) || `<tr><td class="l empty" colspan="${cols.length}">No accounts match these filters.</td></tr>`}</tbody></table>`;
    container.appendChild(wrap);
    bindSort(wrap.querySelector("table"), st, rerender);
    pager(container, st, sorted.length, rerender);
    return sorted;
  }

  function downloadCsv(filename, list) {
    const cols = ["id", "rel", "relationship_name", "product", "subType", "rating", "exposure", "rate", "revenue", "opex", "el", "capital", "net", "raroc", "eva"];
    const lines = [cols.join(",")].concat(list.map(a => cols.map(c => {
      const v = c === "relationship_name" ? relName(a.rel) : a[c];
      const s = v == null ? "" : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = filename;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---- banner -------------------------------------------------------------------------------
  function renderBanner() {
    const b = $("#banner");
    if (!isScenario()) { b.hidden = true; return; }
    b.hidden = false;
    const modelNote = JSON.stringify(sc.model) !== JSON.stringify(BASE.model) ? `<span>Models: ${esc(modelLabel(sc.model))}</span>` : "";
    b.innerHTML = `<span>Scenario active: <b>${esc(sc.name || "Custom scenario")}</b></span>${modelNote}
      <span>Portfolio RAROC ${pct(base.total.raroc)} → <b>${pct(cur.total.raroc)}</b> (${ptsDelta(base.total.raroc, cur.total.raroc)})</span>
      <span>EVA ${moneyDelta(base.total.eva, cur.total.eva)}</span>
      <span style="margin-left:auto;display:flex;gap:8px"><a href="#/scenarios">Edit scenario</a><button type="button" class="link" id="resetBase">Back to base case</button></span>`;
    $("#resetBase").addEventListener("click", () => { setScenario(clone(BASE)); if (ui.tab === "scenarios") renderScenarios(); });
  }

  // ---- overview -----------------------------------------------------------------------------
  function renderOverview() {
    const v = $("#view-overview");
    const t = cur.total, bt = base.total, on = isScenario();
    const keyWatch = KEY_IDS.filter(id => cur.byRel[id].watch || !cur.byRel[id].meetsHurdle).length;
    const tile = (label, value, note) => `<div class="tile"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div>`;
    v.innerHTML = `
      <section class="tiles">
        ${tile("Portfolio RAROC", pct(t.raroc), on ? `base ${pct(bt.raroc)} · ${ptsDelta(bt.raroc, t.raroc)}` : `vs. ${pct(sc.hurdle, 0)} hurdle`)}
        ${tile("Net income (after tax)", money(t.net), on ? `base ${money(bt.net)}` : "annualised")}
        ${tile(BASIS_LABEL[sc.model.capitalBasis], money(t.capital), on ? `base ${money(bt.capital)}` : sc.model.capitalBasis === "economic" ? "credit + operational" : APPROACH_LABEL[sc.model.baselApproach])}
        ${tile("EVA", money(t.eva), on ? `base ${money(bt.eva)}` : `net income − ${pct(sc.hurdle, 0)} × capital`)}
        ${tile("Relationships below hurdle", `${cur.belowHurdle} / ${book.rels.length}`, `${keyWatch} key relationship(s) flagged`)}
      </section>
      <h2>RAROC by product</h2>
      <p class="sub">Credit products carry nearly all the capital, and revolvers fall below the hurdle on their own. Deposits and payments use little capital, so their stand-alone RAROC is very high.${on ? " Black ticks mark the base case." : ""}</p>
      <div class="card">${on ? '<div class="legend"><span><i class="sw" style="background:var(--s1)"></i>Scenario</span><span><i class="sw tick"></i>Base case</span><span><i class="sw line"></i>Hurdle</span></div>' : ""}<svg id="productChart" role="img" aria-label="RAROC by product"></svg></div>
      <h2>Key relationships: lending vs. full relationship RAROC</h2>
      <p class="sub">Each row runs from credit-only RAROC to full relationship RAROC. The gap is the value of deposits and payments. Click a row to open the relationship.</p>
      <div class="card">
        <div class="legend"><span><i class="sw dot" style="background:var(--s1)"></i>Lending RAROC (loans, revolvers, IRDs)</span><span><i class="sw dot" style="background:var(--s2)"></i>Relationship RAROC (all products)</span><span><i class="sw line"></i>${pct(sc.hurdle, 0)} hurdle</span></div>
        <svg id="dumbbell" role="img" aria-label="Lending versus relationship RAROC for the ten key relationships"></svg>
      </div>
      <h2>Where key-relationship revenue comes from</h2>
      <p class="sub">Share of annual revenue by product. Keystone and Blue Mesa rely mostly on credit, which is why they sit closest to the hurdle.</p>
      <div class="card"><div class="legend" id="mixLegend"></div><svg id="mix" role="img" aria-label="Revenue mix by product for key relationships"></svg></div>
      <h2>Key relationship scorecard</h2>
      <div class="card table-wrap" id="keyTable"></div>`;
    productChart($("#productChart"));
    dumbbellChart($("#dumbbell"), id => go(`#/relationships/${id}`));
    mixChart($("#mix"), $("#mixLegend"));
    const rows = KEY_IDS.map(id => cur.byRel[id]).sort((a, b) => b.all.raroc - a.all.raroc);
    $("#keyTable").innerHTML = `<table><thead><tr><th class="l">Relationship</th><th class="l">Industry</th><th>Rating</th><th>Revenue</th><th>Capital</th><th>Net income</th><th>EVA</th><th>Lending RAROC</th><th>Relationship RAROC</th>${on ? "<th>vs. base</th>" : ""}<th class="l">Status</th></tr></thead><tbody>${
      rows.map(r => `<tr class="clickable" tabindex="0" data-rel="${r.relationship_id}"><td class="l"><a href="#/relationships/${r.relationship_id}">${esc(r.name)}</a></td><td class="l">${esc(r.industry)}</td><td>${r.rating}</td><td>${money(r.all.revenue)}</td><td>${money(r.all.capital)}</td><td>${money(r.all.net)}</td><td>${money(r.all.eva)}</td><td>${pct(r.lending.raroc)}</td><td><b>${pct(r.all.raroc)}</b></td>${on ? `<td>${ptsDelta(base.byRel[r.relationship_id].all.raroc, r.all.raroc)}</td>` : ""}<td class="l">${statusHtml(r)}</td></tr>`).join("")
    }</tbody></table>`;
    bindRowNav($("#keyTable"));
  }
  function bindRowNav(scope) {
    scope.querySelectorAll("tr[data-rel]").forEach(tr => {
      const open = () => go(`#/relationships/${tr.dataset.rel}`);
      tr.addEventListener("click", e => { if (e.target.tagName !== "A") open(); });
      tr.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
    });
  }

  // ---- relationships --------------------------------------------------------------------------
  const REL_GET = {
    name: r => r.name, segment: r => r.segment, industry: r => r.industry, rating: r => r.rating,
    n: r => r.all.n, revenue: r => r.all.revenue, capital: r => r.all.capital, net: r => r.all.net,
    eva: r => r.all.eva, lending: r => r.lending.raroc, raroc: r => r.all.raroc,
    delta: r => r.all.raroc - base.byRel[r.relationship_id].all.raroc,
  };
  function renderRelationships() {
    const v = $("#view-relationships");
    if (ui.relId) return renderRelDetail(v, ui.relId);
    const st = ui.rels, on = isScenario();
    v.innerHTML = `<h2>All relationships</h2>
      <p class="sub">All 500 client relationships with their RAROC across every product they hold. Click a row to see its accounts.</p>
      <div class="toolbar">
        <label>Search<input type="search" id="relQ" placeholder="Name, ID or industry" value="${esc(st.q)}"></label>
        <label>Segment<select id="relSeg">
          ${["all", "Key Relationship", "Middle Market", "Business Banking"].map(s => `<option value="${s}" ${st.seg === s ? "selected" : ""}>${s === "all" ? "All segments" : s}</option>`).join("")}
        </select></label>
        <label class="check"><input type="checkbox" id="relBelow" ${st.below ? "checked" : ""}> Below hurdle only</label>
        <span class="count" id="relCount"></span>
      </div>
      <div class="card" id="relTable"></div>`;
    const draw = () => {
      const q = st.q.trim().toLowerCase();
      let list = cur.relList.filter(r =>
        (st.seg === "all" || r.segment === st.seg) && (!st.below || !r.meetsHurdle) &&
        (!q || r.name.toLowerCase().includes(q) || r.relationship_id.toLowerCase().includes(q) || r.industry.toLowerCase().includes(q)));
      $("#relCount").textContent = `${list.length.toLocaleString()} relationships`;
      const cols = [
        { label: "Relationship", sort: "name", left: true }, { label: "Segment", sort: "segment", left: true },
        { label: "Industry", sort: "industry", left: true }, { label: "Rating", sort: "rating" },
        { label: "Accounts", sort: "n" }, { label: "Revenue", sort: "revenue" }, { label: "Capital", sort: "capital" },
        { label: "Net income", sort: "net" }, { label: "EVA", sort: "eva" }, { label: "Lending RAROC", sort: "lending" },
        { label: "RAROC", sort: "raroc" }].concat(on ? [{ label: "vs. base", sort: "delta" }] : []).concat([{ label: "Status", left: true }]);
      list = sortRows(list, st.sort, st.dir, REL_GET);
      const page = list.slice(st.page * PAGE, (st.page + 1) * PAGE);
      const box = $("#relTable"); box.innerHTML = "";
      const wrap = document.createElement("div"); wrap.className = "table-wrap";
      wrap.innerHTML = `<table>${header(cols, st)}<tbody>${page.map(r => `<tr class="clickable" tabindex="0" data-rel="${r.relationship_id}">
        <td class="l"><a href="#/relationships/${r.relationship_id}">${esc(r.name)}</a><span class="sub-id">${r.relationship_id}</span></td>
        <td class="l">${esc(r.segment)}</td><td class="l">${esc(r.industry)}</td><td>${r.rating}</td><td>${r.all.n}</td>
        <td>${money(r.all.revenue)}</td><td>${money(r.all.capital)}</td><td>${money(r.all.net)}</td><td>${money(r.all.eva)}</td>
        <td>${pct(r.lending.raroc)}</td><td><b>${pct(r.all.raroc)}</b></td>${on ? `<td>${ptsDelta(base.byRel[r.relationship_id].all.raroc, r.all.raroc)}</td>` : ""}
        <td class="l">${statusHtml(r)}</td></tr>`).join("") || `<tr><td class="l empty" colspan="${cols.length}">No relationships match.</td></tr>`}</tbody></table>`;
      box.appendChild(wrap);
      bindSort(wrap.querySelector("table"), st, draw);
      bindRowNav(wrap);
      pager(box, st, list.length, draw);
    };
    $("#relQ").addEventListener("input", e => { st.q = e.target.value; st.page = 0; draw(); });
    $("#relSeg").addEventListener("change", e => { st.seg = e.target.value; st.page = 0; draw(); });
    $("#relBelow").addEventListener("change", e => { st.below = e.target.checked; st.page = 0; draw(); });
    draw();
  }

  function renderRelDetail(v, id) {
    const r = cur.byRel[id], b = base.byRel[id], on = isScenario();
    if (!r) { v.innerHTML = `<p class="back"><a href="#/relationships">← All relationships</a></p><p>Relationship ${esc(id)} not found.</p>`; return; }
    const accs = cur.accounts.filter(a => a.rel === id);
    const tile = (label, value, note) => `<div class="tile"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div>`;
    v.innerHTML = `<p class="back"><a href="#/relationships">← All relationships</a></p>
      <div class="detail-head"><h2>${esc(r.name)}</h2><span class="sub-id">${id} · ${esc(r.segment)} · ${esc(r.industry)} · risk rating ${r.rating}</span>${statusHtml(r)}</div>
      <section class="tiles">
        ${tile("Relationship RAROC", pct(r.all.raroc), on ? `base ${pct(b.all.raroc)} · ${ptsDelta(b.all.raroc, r.all.raroc)}` : `hurdle ${pct(sc.hurdle, 0)}`)}
        ${tile("Lending-only RAROC", pct(r.lending.raroc), `uplift from deposits + payments ${ptsDelta(r.lending.raroc, r.all.raroc)}`)}
        ${tile("EVA", money(r.all.eva), on ? `base ${money(b.all.eva)}` : "net income − hurdle × capital")}
        ${tile("Revenue", money(r.all.revenue), `${r.all.n} accounts`)}
        ${tile("Economic capital", money(r.all.capital), `net income ${money(r.all.net)}`)}
      </section>
      <div class="actions">
        <button type="button" class="primary" id="priceHere">Price a new deal for this client</button>
        <button type="button" id="scopeHere">Run a scenario on this client only</button>
      </div>
      <h3>By product</h3>
      <div class="card table-wrap"><table><thead><tr><th class="l">Product</th><th>Accounts</th><th>Exposure</th><th>Revenue</th><th>Exp. loss</th><th>Capital</th><th>Net income</th><th>EVA</th><th>RAROC</th></tr></thead><tbody>${
        PRODUCTS.filter(p => r.products[p].n).map(p => { const x = r.products[p]; return `<tr><td class="l">${esc(p)}</td><td>${x.n}</td><td>${money(x.exposure)}</td><td>${money(x.revenue)}</td><td>${money(x.el)}</td><td>${money(x.capital)}</td><td>${money(x.net)}</td><td>${money(x.eva)}</td><td><b>${pct(x.raroc)}</b></td></tr>`; }).join("")
      }<tr><td class="l"><b>Total</b></td><td><b>${r.all.n}</b></td><td></td><td><b>${money(r.all.revenue)}</b></td><td><b>${money(r.all.el)}</b></td><td><b>${money(r.all.capital)}</b></td><td><b>${money(r.all.net)}</b></td><td><b>${money(r.all.eva)}</b></td><td><b>${pct(r.all.raroc)}</b></td></tr></tbody></table></div>
      <h3>All ${accs.length} accounts</h3>
      <div class="toolbar"><span class="count"></span><button type="button" id="relCsv">Download CSV${can("professional") ? "" : ' <span class="pro-badge">PRO</span>'}</button></div>
      <div class="card" id="relAccTable"></div>`;
    const draw = () => { const box = $("#relAccTable"); box.innerHTML = ""; renderAccountTable(box, accs, ui.relAccs, false, draw); };
    draw();
    $("#relCsv").addEventListener("click", () => can("professional") ? downloadCsv(`${id}_accounts.csv`, accs) : go("#/plans"));
    $("#priceHere").addEventListener("click", () => { ui.deal.rel = id; ui.deal.rating = r.rating; go("#/scenarios"); setTimeout(() => $("#dealBox")?.scrollIntoView({ behavior: "smooth" }), 50); });
    $("#scopeHere").addEventListener("click", () => { sc.scope = id; sc.name = `${r.name} scenario`; recompute(); go("#/scenarios"); });
  }

  // ---- accounts -----------------------------------------------------------------------------
  function renderAccounts() {
    const v = $("#view-accounts"), st = ui.accs;
    v.innerHTML = `<h2>All accounts</h2>
      <p class="sub">Every one of the ${cur.accounts.length.toLocaleString()} accounts with its revenue, expected loss, capital and RAROC under the current scenario. Sort by any column; download what you filter.</p>
      <div class="toolbar">
        <label>Search<input type="search" id="accQ" placeholder="Account ID or client" value="${esc(st.q)}"></label>
        <label>Product<select id="accProd"><option value="all">All products</option>${PRODUCTS.map(p => `<option ${st.product === p ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></label>
        <label>Segment<select id="accSeg">${["all", "Key Relationship", "Middle Market", "Business Banking"].map(s => `<option value="${s}" ${st.seg === s ? "selected" : ""}>${s === "all" ? "All segments" : s}</option>`).join("")}</select></label>
        <label class="check"><input type="checkbox" id="accBelow" ${st.below ? "checked" : ""}> RAROC below hurdle</label>
        <span class="count" id="accCount"></span>
        <button type="button" id="accCsv">Download CSV${can("professional") ? "" : ' <span class="pro-badge">PRO</span>'}</button>
      </div>
      <div class="card" id="accTable"></div>`;
    let filtered = [];
    const draw = () => {
      const q = st.q.trim().toLowerCase();
      filtered = cur.accounts.filter(a => {
        if (st.product !== "all" && a.product !== st.product) return false;
        if (st.seg !== "all" && book.relById[a.rel].segment !== st.seg) return false;
        if (st.below && !(a.raroc < sc.hurdle)) return false;
        return !q || a.id.toLowerCase().includes(q) || a.rel.toLowerCase().includes(q) || relName(a.rel).toLowerCase().includes(q);
      });
      const exp = filtered.reduce((s, a) => s + a.exposure, 0), net = filtered.reduce((s, a) => s + a.net, 0), cap = filtered.reduce((s, a) => s + a.capital, 0);
      $("#accCount").textContent = `${filtered.length.toLocaleString()} accounts · exposure ${money(exp)} · RAROC ${pct(cap ? net / cap : null)}`;
      const box = $("#accTable"); box.innerHTML = "";
      renderAccountTable(box, filtered, st, true, draw);
    };
    $("#accQ").addEventListener("input", e => { st.q = e.target.value; st.page = 0; draw(); });
    $("#accProd").addEventListener("change", e => { st.product = e.target.value; st.page = 0; draw(); });
    $("#accSeg").addEventListener("change", e => { st.seg = e.target.value; st.page = 0; draw(); });
    $("#accBelow").addEventListener("change", e => { st.below = e.target.checked; st.page = 0; draw(); });
    $("#accCsv").addEventListener("click", () => can("professional") ? downloadCsv("accounts.csv", sortRows(filtered, st.sort, st.dir, ACC_GET)) : go("#/plans"));
    draw();
  }

  // ---- scenarios ------------------------------------------------------------------------------
  const PRESETS = [
    { name: "Base case", set: {} },
    { name: "Rates +100 bps", set: { rateShockBps: 100 } },
    { name: "Rates −100 bps", set: { rateShockBps: -100 } },
    { name: "Mild recession", set: { ratingNotches: 1, lgdShockPts: 5, utilizationPts: 10, depositBalancePct: -5, paymentsFeePct: -5 } },
    { name: "Severe recession", set: { ratingNotches: 2, lgdShockPts: 10, utilizationPts: 20, depositBalancePct: -15, paymentsFeePct: -10, rateShockBps: -150 } },
    { name: "Reprice all revolvers", set: { revolverSpreadBps: 25, unusedFeeBps: 10 } },
    { name: "Deposit price war", set: { depositRateBps: 50, depositBalancePct: 5 } },
    { name: "Blue Mesa remediation", set: { scope: "R007", revolverSpreadBps: 50, loanSpreadBps: 25, depositBalancePct: 40, paymentsFeePct: 50 } },
    { name: "Key clients: deepen treasury", set: { scope: "KEY", depositBalancePct: 20, paymentsFeePct: 25 } },
  ];
  const LEVERS = [
    { group: "Market (applies to the whole book)", items: [
      { key: "rateShockBps", label: "Interest rate shock", unit: "bps", min: -300, max: 300, step: 25, hint: "Parallel shift in the FTP curve. Loans are match-funded, so rates move deposit margins, capital credit and derivative exposure." },
      { key: "hurdlePct", label: "Hurdle rate", unit: "%", min: 6, max: 20, step: 0.5 },
    ] },
    { group: "Credit (applies to scope)", items: [
      { key: "ratingNotches", label: "Risk rating migration", unit: "notches", min: -2, max: 3, step: 1, hint: "Positive = downgrade on loans, revolvers and derivatives." },
      { key: "lgdShockPts", label: "Loss given default", unit: "pts", min: -10, max: 25, step: 1 },
      { key: "utilizationPts", label: "Revolver utilization", unit: "pts", min: -30, max: 40, step: 5 },
    ] },
    { group: "Pricing (applies to scope)", items: [
      { key: "loanSpreadBps", label: "Term loan spreads", unit: "bps", min: -100, max: 200, step: 5 },
      { key: "revolverSpreadBps", label: "Revolver drawn spreads", unit: "bps", min: -100, max: 200, step: 5 },
      { key: "unusedFeeBps", label: "Revolver unused fees", unit: "bps", min: -20, max: 50, step: 5 },
    ] },
    { group: "Deposits & payments (applies to scope)", items: [
      { key: "depositBalancePct", label: "Deposit balances", unit: "%", min: -50, max: 100, step: 5 },
      { key: "depositRateBps", label: "Deposit rate paid", unit: "bps", min: -100, max: 150, step: 5, hint: "Pricing change on top of the rate shock pass-through (deposit betas)." },
      { key: "paymentsFeePct", label: "Payments fee revenue", unit: "%", min: -50, max: 100, step: 5 },
    ] },
  ];
  const getLever = k => k === "hurdlePct" ? +(sc.hurdle * 100).toFixed(2) : sc[k];
  const setLever = (k, v) => { if (k === "hurdlePct") sc.hurdle = v / 100; else sc[k] = v; };

  const STORE = "raroc.savedScenarios.v1";
  function loadSaved() { try { return JSON.parse(localStorage.getItem(STORE) || "[]"); } catch { return []; } }
  function storeSaved(list) { try { localStorage.setItem(STORE, JSON.stringify(list)); return true; } catch { return false; } }

  function scopeOptions() {
    const key = book.rels.filter(r => r.segment === "Key Relationship"), other = book.rels.filter(r => r.segment !== "Key Relationship");
    const opt = r => `<option value="${r.relationship_id}" ${sc.scope === r.relationship_id ? "selected" : ""}>${esc(r.name)} (${r.relationship_id})</option>`;
    return `<option value="ALL" ${sc.scope === "ALL" ? "selected" : ""}>Whole portfolio</option>
      <option value="KEY" ${sc.scope === "KEY" ? "selected" : ""}>All 10 key relationships</option>
      <optgroup label="Key relationships">${key.map(opt).join("")}</optgroup>
      <optgroup label="Other relationships">${other.map(opt).join("")}</optgroup>`;
  }
  function relOptions(sel) {
    return `<optgroup label="Key relationships">${book.rels.filter(r => r.segment === "Key Relationship").map(r => `<option value="${r.relationship_id}" ${sel === r.relationship_id ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</optgroup>
      <optgroup label="Other relationships">${book.rels.filter(r => r.segment !== "Key Relationship").map(r => `<option value="${r.relationship_id}" ${sel === r.relationship_id ? "selected" : ""}>${esc(r.name)} (${r.relationship_id})</option>`).join("")}</optgroup>`;
  }

  function renderScenarios() {
    const v = $("#view-scenarios"), d = ui.deal;
    const saved = loadSaved();
    v.innerHTML = `<div class="scenario-grid">
      <div class="panel" id="scenarioForm">
        <h3>Build a scenario</h3>
        <div class="row2">
          <label class="field">Start from a preset<select id="preset"><option value="">Choose…</option>${PRESETS.map((p, i) => `<option value="${i}">${esc(p.name)}</option>`).join("")}</select></label>
          <label class="field">Scenario name<input type="text" id="scName" value="${esc(sc.name)}" maxlength="60"></label>
        </div>
        <div data-pro="Custom levers, proposed deals, saving and sharing are Professional features. Presets are free">
        <label class="field" style="margin-top:8px">Apply credit, pricing and deposit levers to<select id="scope">${scopeOptions()}</select></label>
        ${LEVERS.map(g => `<fieldset><legend>${g.group}</legend>${g.items.map(l => `
          <div class="lever">
            <label for="n-${l.key}">${l.label}<span>${l.unit}</span></label>
            <input type="range" id="r-${l.key}" min="${l.min}" max="${l.max}" step="${l.step}" value="${getLever(l.key)}" aria-label="${l.label}">
            <input type="number" id="n-${l.key}" min="${l.min}" max="${l.max}" step="${l.step}" value="${getLever(l.key)}">
            ${l.hint ? `<p class="hint" style="grid-column:1/-1">${l.hint}</p>` : ""}
          </div>`).join("")}</fieldset>`).join("")}
        <fieldset><legend>Deposit betas (share of a rate move passed to depositors)</legend>
          <div class="row3">${["Operating", "Non-Operating", "Time Deposit"].map(t => `<label class="field">${t}<input type="number" step="0.05" min="0" max="1" data-beta="${t}" value="${sc.depositBetas[t]}"></label>`).join("")}</div>
        </fieldset>
        <div class="actions">
          <button type="button" class="primary" id="saveSc">Save scenario</button>
          <button type="button" id="shareSc">Copy share link</button>
          <button type="button" id="resetSc">Reset to base</button>
        </div>
        <p class="hint" id="saveMsg" aria-live="polite"></p>
        </div>
        <label class="field">Saved scenarios (this browser)<select id="savedList"><option value="">${saved.length ? "Load a saved scenario…" : "None saved yet"}</option>${saved.map((s, i) => `<option value="${i}">${esc(s.name)}</option>`).join("")}</select></label>
        ${saved.length ? '<button type="button" class="link" id="delSaved" style="margin-top:6px">Delete selected</button>' : ""}

        <fieldset id="dealBox"><legend>Price a new deal</legend>
          <p class="hint">Solves for the spread that earns the hurdle under this scenario, on its own and with the client's other accounts.</p>
          <label class="field">Client<select id="dRel">${relOptions(d.rel)}</select></label>
          <div class="row2" style="margin-top:8px">
            <label class="field">Product<select id="dProd"><option ${d.product === "Term Loan" ? "selected" : ""}>Term Loan</option><option ${d.product === "Revolver" ? "selected" : ""}>Revolver</option></select></label>
            <label class="field">Amount ($M)<input type="number" id="dAmt" min="0.1" step="0.5" value="${d.amountM}"></label>
            <label class="field">Tenor (years)<input type="number" id="dTenor" min="1" max="30" step="1" value="${d.tenor}"></label>
            <label class="field">Risk rating (1–10)<input type="number" id="dRating" min="1" max="10" step="1" value="${d.rating}"></label>
            <label class="field">Collateral<select id="dColl">${["Senior Secured", "Real Estate", "Unsecured"].map(c => `<option ${d.collateral === c ? "selected" : ""}>${c}</option>`).join("")}</select></label>
            <label class="field">Upfront fee (bps)<input type="number" id="dFee" min="0" max="500" step="5" value="${d.feeBps}"></label>
            <label class="field rev-only">Expected utilization (%)<input type="number" id="dUtil" min="0" max="100" step="5" value="${d.utilPct}"></label>
            <label class="field rev-only">Unused fee (bps)<input type="number" id="dUnused" min="0" max="200" step="5" value="${d.unusedBps}"></label>
          </div>
          <div id="priceOut" class="price-out"></div>
          <div class="row2" style="margin-top:10px;align-items:end" data-pro="Adding deals to a scenario is a Professional feature">
            <label class="field">Book it at spread (bps)<input type="number" id="dSpread" min="0" max="2500" step="5"></label>
            <button type="button" class="primary" id="addDeal">Add deal to scenario</button>
          </div>
          <ul class="deal-list" id="dealList"></ul>
        </fieldset>
      </div>
      <div class="results" id="scResults"></div>
    </div>`;

    // lever bindings
    LEVERS.forEach(g => g.items.forEach(l => {
      const r = $(`#r-${l.key}`), n = $(`#n-${l.key}`);
      const apply = val => { const x = Math.min(Math.max(+val || 0, l.min), l.max); setLever(l.key, x); r.value = x; n.value = x; markCustom(); recompute(); };
      r.addEventListener("input", () => apply(r.value));
      n.addEventListener("change", () => apply(n.value));
    }));
    v.querySelectorAll("[data-beta]").forEach(inp => inp.addEventListener("change", () => {
      sc.depositBetas[inp.dataset.beta] = Math.min(Math.max(+inp.value || 0, 0), 1); markCustom(); recompute();
    }));
    $("#scope").addEventListener("change", e => { sc.scope = e.target.value; markCustom(); recompute(); });
    $("#scName").addEventListener("input", e => { sc.name = e.target.value; renderBanner(); });
    $("#preset").addEventListener("change", e => {
      if (e.target.value === "") return;
      const p = PRESETS[+e.target.value];
      const deals = sc.newDeals, model = clone(sc.model);
      sc = Object.assign(clone(BASE), clone(p.set), { name: p.name, newDeals: deals, model });
      recompute(); renderScenarios();
    });
    $("#resetSc").addEventListener("click", () => { setScenario(clone(BASE)); renderScenarios(); });
    $("#saveSc").addEventListener("click", () => {
      const list = loadSaved().filter(s => s.name !== sc.name);
      list.push(clone(sc));
      $("#saveMsg").textContent = storeSaved(list) ? `Saved "${sc.name}" in this browser.` : "This browser blocks storage; use Copy share link instead.";
      setTimeout(renderScenarios, 900);
    });
    $("#savedList").addEventListener("change", e => {
      if (e.target.value === "") return;
      const s = loadSaved()[+e.target.value];
      if (s) { sc = Object.assign(clone(BASE), s); normalise(); recompute(); renderScenarios(); }
    });
    $("#delSaved")?.addEventListener("click", () => {
      const i = $("#savedList").value; if (i === "") return;
      const list = loadSaved(); list.splice(+i, 1); storeSaved(list); renderScenarios();
    });
    $("#shareSc").addEventListener("click", () => {
      const url = location.origin + location.pathname + "?s=" + encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(sc))))) + "#/scenarios";
      const done = ok => { $("#saveMsg").textContent = ok ? "Share link copied. Anyone opening it sees this scenario." : url; };
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(() => done(true), () => done(false)); else done(false);
    });

    // deal builder
    const readDeal = () => {
      Object.assign(d, { rel: $("#dRel").value, product: $("#dProd").value, amountM: +$("#dAmt").value || 0,
        tenor: +$("#dTenor").value || 1, rating: Math.min(Math.max(Math.round(+$("#dRating").value || 5), 1), 10),
        collateral: $("#dColl").value, feeBps: +$("#dFee").value || 0, utilPct: Math.min(Math.max(+$("#dUtil").value || 0, 0), 100),
        unusedBps: +$("#dUnused").value || 0 });
      v.querySelectorAll(".rev-only").forEach(e => { e.style.display = d.product === "Revolver" ? "" : "none"; });
    };
    const dealSpec = spread => ({ rel: d.rel, product: d.product, amount: d.amountM * 1e6, tenor: d.tenor, rating: d.rating,
      collateral: d.collateral, utilization: d.utilPct / 100, unusedFee: d.unusedBps / 1e4, feePct: d.feeBps / 1e4, spread });
    const priceNow = () => {
      readDeal();
      if (!(d.amountM > 0)) { $("#priceOut").innerHTML = '<p class="empty">Enter an amount above zero.</p>'; return; }
      const p = E.priceDeal(book, sc, cur, dealSpec(0.02));
      const conc = p.concessionBps;
      let approval = "Within policy: no pricing exception.";
      if (conc > 50) approval = "Concession above 50 bps: needs Regional Credit Officer approval.";
      $("#priceOut").innerHTML = `<div class="table-wrap"><table>
        <tr><td>Stand-alone floor</td><td>${bps(p.standalone)}</td></tr>
        <tr><td>Relationship floor</td><td>${p.relFloorBinding ? bps(p.relFloor) : "not binding"}</td></tr>
        <tr><td>Cost floor (EL + liquidity + opex)</td><td>${bps(p.costFloor)}</td></tr>
        <tr><td><b>Recommended spread</b></td><td><b>${bps(p.recommended)}</b></td></tr>
        <tr><td>Relationship concession</td><td>${Math.round(conc)} bps</td></tr>
        <tr><td>Deal RAROC at recommended</td><td>${pct(p.atRecommended.raroc)}</td></tr>
        <tr><td>Client RAROC before → after</td><td>${pct(p.relRarocBefore)} → ${pct(p.relRarocAfter)}</td></tr>
      </table></div><div class="note-box">${approval}</div>`;
      $("#dSpread").value = Math.round(p.recommended * 1e4);
    };
    ["#dRel", "#dProd", "#dAmt", "#dTenor", "#dRating", "#dColl", "#dFee", "#dUtil", "#dUnused"].forEach(s => $(s).addEventListener("change", priceNow));
    $("#addDeal").addEventListener("click", () => {
      readDeal();
      const spread = (+$("#dSpread").value || 0) / 1e4;
      sc.newDeals.push(dealSpec(spread)); markCustom(); recompute(); drawDeals(); priceNow();
    });
    const drawDeals = () => {
      const ul = $("#dealList");
      ul.innerHTML = sc.newDeals.length ? sc.newDeals.map((x, i) => `<li><span>NEW-${i + 1}: ${esc(relName(x.rel))}, ${money(x.amount)} ${esc(x.product.toLowerCase())}, ${x.tenor}y, rating ${x.rating}, ${Math.round(x.spread * 1e4)} bps</span><button type="button" class="link" data-rm="${i}">Remove</button></li>`).join("")
        : '<li class="empty">No proposed deals in this scenario.</li>';
      ul.querySelectorAll("[data-rm]").forEach(b => b.addEventListener("click", () => { sc.newDeals.splice(+b.dataset.rm, 1); recompute(); drawDeals(); priceNow(); }));
    };
    drawDeals(); priceNow(); renderResults();
    applyGates(v);
  }
  function markCustom() {
    const n = $("#scName");
    if (n && PRESETS.some(p => p.name === sc.name)) { sc.name = "Custom scenario"; n.value = sc.name; }
  }

  function renderResults() {
    const box = $("#scResults"); if (!box) return;
    const t = cur.total, b = base.total;
    const keyFlag = s => KEY_IDS.filter(id => s.byRel[id].watch || !s.byRel[id].meetsHurdle).length;
    const row = (label, bv, sv, fmt, delta) => `<tr><td class="l">${label}</td><td>${fmt(bv)}</td><td><b>${fmt(sv)}</b></td><td>${delta}</td></tr>`;
    const crossed = cur.relList.filter(r => r.meetsHurdle !== base.byRel[r.relationship_id].meetsHurdle);
    const movers = cur.relList.map(r => ({ r, d: r.all.eva - base.byRel[r.relationship_id].all.eva }))
      .filter(o => Math.abs(o.d) >= 1).sort((a, c) => Math.abs(c.d) - Math.abs(a.d)).slice(0, 10);
    const scopeLabel = sc.scope === "ALL" ? "whole portfolio" : sc.scope === "KEY" ? "10 key relationships" : relName(sc.scope);
    box.innerHTML = `
      <div class="card">
        <h3 style="margin-top:0">${esc(sc.name || "Scenario")} vs. base case</h3>
        <p class="hint">Scope for credit, pricing and deposit levers: ${esc(scopeLabel)}.${sc.newDeals.length ? ` Includes ${sc.newDeals.length} proposed deal(s).` : ""}</p>
        <div class="table-wrap"><table><thead><tr><th class="l">Metric</th><th>Base</th><th>Scenario</th><th>Change</th></tr></thead><tbody>
          ${row("Portfolio RAROC", b.raroc, t.raroc, v => pct(v), ptsDelta(b.raroc, t.raroc))}
          ${row("Net income (after tax)", b.net, t.net, money, moneyDelta(b.net, t.net))}
          ${row("Revenue", b.revenue, t.revenue, money, moneyDelta(b.revenue, t.revenue))}
          ${row("Expected loss", b.el, t.el, money, moneyDelta(b.el, t.el, false))}
          ${row("Economic capital", b.capital, t.capital, money, moneyDelta(b.capital, t.capital, false))}
          ${row("EVA", b.eva, t.eva, money, moneyDelta(b.eva, t.eva))}
          <tr><td class="l">Relationships below hurdle</td><td>${base.belowHurdle}</td><td><b>${cur.belowHurdle}</b></td><td>${cur.belowHurdle === base.belowHurdle ? '<span class="note">no change</span>' : `<span class="${cur.belowHurdle < base.belowHurdle ? "delta-up" : "delta-down"}">${cur.belowHurdle > base.belowHurdle ? "+" : "−"}${Math.abs(cur.belowHurdle - base.belowHurdle)}</span>`}</td></tr>
          <tr><td class="l">Key relationships flagged</td><td>${keyFlag(base)}</td><td><b>${keyFlag(cur)}</b></td><td></td></tr>
        </tbody></table></div>
      </div>
      <div class="card">
        <h3 style="margin-top:0">RAROC by product</h3>
        <div class="table-wrap"><table><thead><tr><th class="l">Product</th><th>Base</th><th>Scenario</th><th>Change</th><th>Scenario EVA</th></tr></thead><tbody>
          ${PRODUCTS.map(p => `<tr><td class="l">${esc(p)}</td><td>${pct(base.byProduct[p].raroc)}</td><td><b>${pct(cur.byProduct[p].raroc)}</b></td><td>${ptsDelta(base.byProduct[p].raroc, cur.byProduct[p].raroc)}</td><td>${money(cur.byProduct[p].eva)}</td></tr>`).join("")}
        </tbody></table></div>
      </div>
      <div class="card">
        <h3 style="margin-top:0">Key relationships: base vs. scenario RAROC</h3>
        <div class="legend"><span><i class="sw" style="background:var(--s1)"></i>Base case</span><span><i class="sw" style="background:var(--s2)"></i>Scenario</span><span><i class="sw line"></i>${pct(sc.hurdle, 0)} hurdle</span></div>
        <svg id="cmpChart" role="img" aria-label="Base versus scenario RAROC for key relationships"></svg>
      </div>
      <div class="card">
        <h3 style="margin-top:0">Biggest EVA changes</h3>
        ${movers.length ? `<div class="table-wrap"><table><thead><tr><th class="l">Relationship</th><th>Base RAROC</th><th>Scenario RAROC</th><th>EVA change</th><th class="l">Status</th></tr></thead><tbody>
          ${movers.map(o => `<tr class="clickable" tabindex="0" data-rel="${o.r.relationship_id}"><td class="l"><a href="#/relationships/${o.r.relationship_id}">${esc(o.r.name)}</a></td><td>${pct(base.byRel[o.r.relationship_id].all.raroc)}</td><td><b>${pct(o.r.all.raroc)}</b></td><td>${moneyDelta(0, o.d)}</td><td class="l">${statusHtml(o.r)}</td></tr>`).join("")}
        </tbody></table></div>` : '<p class="empty">No relationship changes yet. Move a lever to see the impact.</p>'}
        ${crossed.length ? `<p class="hint" style="margin-top:10px">${crossed.length} relationship(s) crossed the hurdle: ${crossed.filter(r => r.meetsHurdle).length} now meet it, ${crossed.filter(r => !r.meetsHurdle).length} fell below it.</p>` : ""}
      </div>`;
    compareChart($("#cmpChart"));
    bindRowNav(box);
  }

  // ---- plans & licensing ------------------------------------------------------------------------
  // License keys are ECDSA P-256 signed by the vendor (private key held outside this repo).
  // Client-side checks gate the demo UI; production entitlements are enforced server-side.
  const LICENSE_PUBKEY = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEs41+XBZNrYqPhLvaO2CjAjwiY/NZkI7MmQu9FPwTk9xYfN9kaiMLNTuaa8ICChRmXzu6eZmprIZ8nbCcd9Z6qA==";
  const PLAN_RANK = { community: 0, professional: 1, enterprise: 2 };
  const PLAN_NAME = { community: "Community", professional: "Professional", enterprise: "Enterprise" };
  const lic = { plan: "community", org: null, exp: null, demo: false };
  const can = need => lic.demo || PLAN_RANK[lic.plan] >= PLAN_RANK[need];
  const store = {
    get(k, s = localStorage) { try { return s.getItem(k); } catch { return null; } },
    set(k, v, s = localStorage) { try { v == null ? s.removeItem(k) : s.setItem(k, v); } catch { /* storage blocked */ } },
  };
  const b64u = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));

  async function verifyLicense(key) {
    const parts = String(key || "").trim().split(".");
    if (parts.length !== 3 || parts[0] !== "RAROC1") throw new Error("That is not a RAROC license key.");
    if (!(window.crypto && crypto.subtle)) throw new Error("License checks need a secure (https) page.");
    const pub = await crypto.subtle.importKey("spki", b64u(LICENSE_PUBKEY), { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
    const ok = await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, pub, b64u(parts[2]),
      new TextEncoder().encode(parts[0] + "." + parts[1]));
    if (!ok) throw new Error("This key's signature is not valid.");
    const p = JSON.parse(new TextDecoder().decode(b64u(parts[1])));
    if (!PLAN_RANK[p.plan]) throw new Error("Unknown plan in key.");
    if (p.exp < new Date().toISOString().slice(0, 10)) throw new Error(`This key expired on ${p.exp}.`);
    return p;
  }
  async function activate(key, quiet) {
    try {
      const p = await verifyLicense(key);
      Object.assign(lic, { plan: p.plan, org: p.org, exp: p.exp, demo: false });
      store.set("raroc.license", key.trim());
      return null;
    } catch (e) {
      if (!quiet) return e.message;
      store.set("raroc.license", null);
      return e.message;
    }
  }
  function renderPlanChip() {
    const c = $("#planChip");
    c.innerHTML = lic.demo ? `<span class="pro-badge">PRO DEMO</span>`
      : lic.plan === "community" ? `Community · <a href="#/plans">Upgrade</a>`
      : `${PLAN_NAME[lic.plan]} · ${esc(lic.org)}`;
  }
  /** Disable Professional controls for Community users and explain how to unlock. */
  function applyGates(root) {
    if (can("professional")) return;
    root.querySelectorAll("[data-pro]").forEach(box => {
      box.classList.add("locked");
      box.querySelectorAll("input, select, button, textarea").forEach(el => { el.disabled = true; });
      if (!box.querySelector(".lock-note")) {
        box.insertAdjacentHTML("afterbegin", `<div class="lock-note"><span class="pro-badge">PRO</span> ${esc(box.dataset.pro || "Professional feature")}. <a href="#/plans">Start a free Pro demo or enter a license key</a>.</div>`);
      }
    });
  }

  function renderPlans() {
    const v = $("#view-plans");
    const status = lic.demo ? `You are in a <b>Professional demo</b> for this browser session.`
      : lic.plan === "community" ? `You are on the free <b>Community</b> plan.`
      : `Licensed to <b>${esc(lic.org)}</b>: <b>${PLAN_NAME[lic.plan]}</b> plan, valid to ${esc(lic.exp)}.`;
    v.innerHTML = `<h2>Plans</h2>
      <p class="sub">The RAROC Pricing Platform prices commercial deals and relationships on economic or regulatory capital. Start free on the synthetic book; upgrade to run your own models and scenarios. Pricing shown is indicative.</p>
      <div class="plans">
        <div class="plan"><h3>Community</h3><div class="who">Explore the method</div><div class="price">Free</div>
          <ul><li>Portfolio, relationship and account RAROC</li><li>All 500 relationships and 7,020 accounts</li><li>Scenario presets and deal pricer</li><li>Model reference tables (EL, PIT, ECAP, Basel)</li></ul>
          <button type="button" disabled>${lic.plan === "community" && !lic.demo ? "Current plan" : "Included"}</button></div>
        <div class="plan featured"><h3>Professional</h3><div class="who">Pricing and portfolio teams</div><div class="price">$2,500 <small>/ month, billed annually, up to 10 users</small></div>
          <ul><li>Everything in Community</li><li><b>Capital basis:</b> economic, Basel III regulatory, or the higher of the two</li><li><b>Basel approaches:</b> Standardized, Foundation IRB, Advanced IRB, 72.5% output floor, CET1 target</li><li><b>EL models:</b> TTC or point-in-time PD, lifetime (CECL-style) EL</li><li><b>PIT credit-cycle factors</b> by industry, editable</li><li><b>ECAP:</b> analytic or calibrated factor tables</li><li>Custom scenario levers, proposed deals, save and share</li><li>CSV export</li></ul>
          <button type="button" class="primary" id="startDemo">${lic.demo ? "Demo active" : "Start free Pro demo"}</button></div>
        <div class="plan"><h3>Enterprise</h3><div class="who">Banks rolling out firm-wide</div><div class="price">From $120,000 <small>/ year</small></div>
          <ul><li>Everything in Professional</li><li>Your loan, deposit and treasury data (connectors, secure upload)</li><li>REST API and the Claude-powered pricing copilot</li><li>Your own PD/LGD models, factor tables and policies</li><li>SSO, audit trail, deployment in your cloud (VPC)</li><li>Model documentation for validation (SR 11-7)</li></ul>
          <a class="btn-link" href="https://github.com/ketibak-ai/commercial-lending-raroc" target="_blank" rel="noopener">Talk to us</a></div>
      </div>
      <h3>License</h3>
      <div class="card">
        <p style="margin-top:0">${status}</p>
        <div class="toolbar" data-license>
          <label style="flex:1;min-width:240px">License key<input type="text" id="licKey" placeholder="RAROC1.…" autocomplete="off" spellcheck="false"></label>
          <button type="button" class="primary" id="licGo">Activate</button>
          ${lic.plan !== "community" || lic.demo ? '<button type="button" id="licOff">Return to Community</button>' : ""}
        </div>
        <p class="hint" id="licMsg" aria-live="polite">Keys are verified in your browser against the vendor's public signing key. Your data never leaves this page.</p>
      </div>`;
    $("#startDemo").addEventListener("click", () => {
      lic.demo = true; store.set("raroc.demo", "1", sessionStorage); renderPlanChip(); renderPlans(); renderBanner();
    });
    $("#licGo").addEventListener("click", async () => {
      const err = await activate($("#licKey").value);
      if (err) { $("#licMsg").textContent = err; return; }
      renderPlanChip(); renderPlans(); renderBanner();
    });
    $("#licOff")?.addEventListener("click", () => {
      Object.assign(lic, { plan: "community", org: null, exp: null, demo: false });
      store.set("raroc.license", null); store.set("raroc.demo", null, sessionStorage);
      renderPlanChip(); renderPlans(); renderBanner();
    });
  }

  // ---- risk & capital models --------------------------------------------------------------------
  const APPROACH_LABEL = { SA: "Standardized (SA)", FIRB: "Foundation IRB", AIRB: "Advanced IRB" };
  const BASIS_LABEL = { economic: "Economic capital", regulatory: "Regulatory capital", max: "Higher of economic and regulatory" };
  function modelLabel(m) {
    const bits = [BASIS_LABEL[m.capitalBasis]];
    if (m.capitalBasis !== "economic") bits.push(APPROACH_LABEL[m.baselApproach] + (m.outputFloor ? " + output floor" : ""));
    if (m.capitalBasis !== "regulatory") bits.push(m.ecapMethod === "factor" ? "ECAP factor table" : "analytic ECAP");
    bits.push(`${m.elPdBasis} EL`);
    return bits.join(" · ");
  }
  const runModel = over => E.run(book, { ...sc, model: { ...sc.model, ...over } });

  function renderModels() {
    const v = $("#view-models"), m = sc.model, cfg = book.cfg;
    const credit = cur.accounts.filter(a => E.LENDING.has(a.product));
    const sum = (list, f) => list.reduce((s, a) => s + f(a), 0);
    const ead = sum(credit, a => a.ead);
    const elTtc = sum(credit, a => a.pd * a.lgd * a.ead), elPit = sum(credit, a => a.pdPit * a.lgd * a.ead), elLife = sum(credit, a => a.elLife);

    const approaches = [
      ["Economic capital, analytic (ASRF 99.9%)", { capitalBasis: "economic", ecapMethod: "analytic" }],
      ["Economic capital, factor table (99.95%)", { capitalBasis: "economic", ecapMethod: "factor" }],
      ["Regulatory: Standardized", { capitalBasis: "regulatory", baselApproach: "SA", outputFloor: false }],
      ["Regulatory: Foundation IRB", { capitalBasis: "regulatory", baselApproach: "FIRB", outputFloor: false }],
      ["Regulatory: Advanced IRB", { capitalBasis: "regulatory", baselApproach: "AIRB", outputFloor: false }],
      ["Regulatory: Advanced IRB + output floor", { capitalBasis: "regulatory", baselApproach: "AIRB", outputFloor: true }],
    ].map(([label, over]) => { const r = runModel(over); return { label, r }; });

    const byRating = {};
    credit.forEach(a => {
      const k = a.rating, o = byRating[k] || (byRating[k] = { ead: 0, elTtc: 0, elPit: 0, elLife: 0, pd: a.pd });
      o.ead += a.ead; o.elTtc += a.pd * a.lgd * a.ead; o.elPit += a.pdPit * a.lgd * a.ead; o.elLife += a.elLife;
    });
    const factors = E.ecapFactorTable(cfg);
    const inds = Object.keys(cfg.cycleZ).sort((a, b) => m.cycleZ[a] - m.cycleZ[b]);

    v.innerHTML = `<h2>Risk &amp; capital models</h2>
      <p class="sub">Choose how expected loss and capital are measured. Every view in the app (overview, relationships, accounts, scenarios and deal pricing) recalculates on these settings.</p>
      <div class="card" data-pro="Model settings are a Professional feature">
        <h3 style="margin-top:0">Model settings <span class="pro-badge">PRO</span></h3>
        <div class="row3">
          <label class="field">Capital basis for RAROC<select id="mBasis">${Object.entries(BASIS_LABEL).map(([k, l]) => `<option value="${k}" ${m.capitalBasis === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          <label class="field">Basel approach (regulatory)<select id="mApproach">${Object.entries(APPROACH_LABEL).map(([k, l]) => `<option value="${k}" ${m.baselApproach === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          <label class="field">CET1 capital target (%)<input type="number" id="mCet1" min="4" max="30" step="0.5" value="${+(m.cet1Target * 100).toFixed(2)}"></label>
          <label class="field">Economic capital method<select id="mEcap"><option value="analytic" ${m.ecapMethod === "analytic" ? "selected" : ""}>Analytic (ASRF, 99.9%)</option><option value="factor" ${m.ecapMethod === "factor" ? "selected" : ""}>Factor table (99.95%, industry add-ons)</option></select></label>
          <label class="field">PD for expected loss<select id="mPd"><option value="TTC" ${m.elPdBasis === "TTC" ? "selected" : ""}>Through-the-cycle (TTC)</option><option value="PIT" ${m.elPdBasis === "PIT" ? "selected" : ""}>Point-in-time (PIT)</option></select></label>
          <label class="field">Credit-cycle shift (all industries, σ)<input type="number" id="mShift" min="-3" max="3" step="0.25" value="${m.cycleShift}"></label>
        </div>
        <label class="check" style="margin-top:10px;display:flex"><input type="checkbox" id="mFloor" ${m.outputFloor ? "checked" : ""}> Apply Basel III output floor (IRB RWA ≥ ${pct(cfg.outputFloor, 1)} of standardized)</label>
        <p class="hint">Active: ${esc(modelLabel(m))}</p>
      </div>

      <h3>Capital under each approach</h3>
      <p class="sub">Same book and scenario, measured six ways. Regulatory capital = RWA × CET1 target (${pct(m.cet1Target, 1)}); RAROC uses that capital as the denominator.</p>
      <div class="card table-wrap"><table><thead><tr><th class="l">Approach</th><th>Capital</th><th>RWA</th><th>RWA density (credit)</th><th>Portfolio RAROC</th><th>EVA</th><th>Below hurdle</th></tr></thead><tbody>
        ${approaches.map(({ label, r }) => { const cr = r.accounts.filter(a => E.LENDING.has(a.product)); const dens = sum(cr, a => a.creditRwa || 0) / sum(cr, a => a.ead);
          return `<tr><td class="l">${label}</td><td>${money(r.total.capital)}</td><td>${money(r.total.rwa)}</td><td>${pct(dens, 0)}</td><td><b>${pct(r.total.raroc)}</b></td><td>${money(r.total.eva)}</td><td>${r.belowHurdle}</td></tr>`; }).join("")}
      </tbody></table></div>

      <div class="split">
        <div>
          <h3>Expected loss model</h3>
          <p class="sub">EL = PD × LGD × EAD. Lifetime EL compounds the point-in-time PD over remaining life (CECL-style, undiscounted).</p>
          <div class="card table-wrap"><table class="kv"><tbody>
            <tr><td>Credit exposure at default</td><td>${money(ead)}</td></tr>
            <tr><td>1-year EL, through-the-cycle PD</td><td>${money(elTtc)} (${pct(elTtc / ead, 2)})</td></tr>
            <tr><td>1-year EL, point-in-time PD</td><td>${money(elPit)} (${pct(elPit / ead, 2)})</td></tr>
            <tr><td>Lifetime EL (CECL-style)</td><td>${money(elLife)} (${pct(elLife / ead, 2)})</td></tr>
            <tr><td>EL charged in RAROC</td><td><b>${m.elPdBasis} basis</b></td></tr>
          </tbody></table></div>
          <div class="card table-wrap" style="margin-top:12px"><table><thead><tr><th>Rating</th><th>PD (TTC)</th><th>PD (PIT, avg)</th><th>EAD</th><th>1y EL TTC</th><th>1y EL PIT</th><th>Lifetime EL</th></tr></thead><tbody>
            ${Object.keys(byRating).sort((a, b) => a - b).map(k => { const o = byRating[k]; return `<tr><td>${k}</td><td>${pct(o.pd, 2)}</td><td>${pct(o.elPit && o.elTtc ? o.pd * o.elPit / o.elTtc : null, 2)}</td><td>${money(o.ead)}</td><td>${money(o.elTtc)}</td><td>${money(o.elPit)}</td><td>${money(o.elLife)}</td></tr>`; }).join("")}
          </tbody></table></div>
        </div>
        <div>
          <h3>Point-in-time (PIT) factors</h3>
          <p class="sub">PD<sub>PIT</sub> = N(N⁻¹(PD<sub>TTC</sub>) − √ρ · Z), with ρ the Basel asset correlation. Z is each industry's credit-cycle index: 0 = long-run average, negative = downturn.</p>
          <div class="card table-wrap" data-pro="Editing credit-cycle factors is a Professional feature"><table><thead><tr><th class="l">Industry</th><th>Z</th><th>PD rating 3</th><th>PD rating 5</th><th>PD rating 7</th><th>PIT ÷ TTC (rating 5)</th></tr></thead><tbody>
            ${inds.map(ind => { const z = (m.cycleZ[ind] ?? 0) + m.cycleShift; const p = r => E.pitPd(cfg.pd[r], z);
              return `<tr><td class="l">${esc(ind)}</td><td><input class="z" type="number" step="0.1" min="-3" max="3" data-z="${esc(ind)}" value="${m.cycleZ[ind]}" aria-label="Credit-cycle Z for ${esc(ind)}"></td><td>${pct(p("3"), 2)}</td><td>${pct(p("5"), 2)}</td><td>${pct(p("7"), 2)}</td><td>${(p("5") / cfg.pd["5"]).toFixed(2)}×</td></tr>`; }).join("")}
          </tbody></table>${m.cycleShift ? `<p class="hint">Includes a ${m.cycleShift > 0 ? "+" : ""}${m.cycleShift}σ shift on every industry.</p>` : ""}</div>
        </div>
      </div>

      <h3>Economic capital factor table</h3>
      <p class="sub">Capital per $1 of EAD at 100% LGD, calibrated at ${pct(cfg.ecapConfidence, 2)} confidence with a ${pct(1 - cfg.ecapDiversification, 0)} diversification benefit. Account capital = factor × LGD × EAD × industry multiplier. Maturity rounds up to the next bucket.</p>
      <div class="card table-wrap"><table><thead><tr><th>Rating</th><th>PD</th>${cfg.ecapBuckets.map(b => `<th>${b}y</th>`).join("")}</tr></thead><tbody>
        ${factors.map(f => `<tr><td>${f.rating}</td><td>${pct(f.pd, 2)}</td>${f.factors.map(x => `<td>${pct(x, 2)}</td>`).join("")}</tr>`).join("")}
      </tbody></table>
      <p class="hint">Industry multipliers: ${Object.entries(cfg.ecapIndustryMult).map(([k, x]) => `${esc(k)} ${x.toFixed(2)}×`).join(" · ")}; all others 1.00×.</p></div>

      <h3>Regulatory capital parameters (Basel III)</h3>
      <div class="split">
        <div class="card table-wrap"><table><thead><tr><th>Rating</th><th>SA risk weight</th><th>PD (IRB, floored)</th></tr></thead><tbody>
          ${Object.keys(cfg.pd).map(r => `<tr><td>${r}</td><td>${pct(cfg.saCorporateRw[r], 0)}</td><td>${pct(Math.max(cfg.pd[r], cfg.irbPdFloor), 2)}</td></tr>`).join("")}
        </tbody></table><p class="hint">Income-producing CRE under SA: ${pct(cfg.saCreRw, 0)}. Undrawn commitments: ${pct(cfg.saCommitmentCcf, 0)} CCF (SA and F-IRB), ${pct(cfg.ccf, 0)} own estimate (A-IRB).</p></div>
        <div class="card table-wrap"><table><thead><tr><th class="l">Collateral</th><th>Economic LGD</th><th>F-IRB LGD</th><th>A-IRB floor</th></tr></thead><tbody>
          ${Object.keys(cfg.lgd).map(c => `<tr><td class="l">${esc(c)}</td><td>${pct(cfg.lgd[c], 0)}</td><td>${pct(cfg.firbLgd[c], 0)}</td><td>${pct(cfg.airbLgdFloor[c], 0)}</td></tr>`).join("")}
        </tbody></table><p class="hint">A-IRB uses downturn LGD = ${cfg.downturnLgd[0]} + ${cfg.downturnLgd[1]} × LGD, own maturity (1–5y). F-IRB maturity ${cfg.firbMaturity}y. PD floor ${pct(cfg.irbPdFloor, 2)}. Operational risk RWA = 12.5 × ${pct(cfg.smaBicRate, 0)} × revenue (SMA bucket 1).</p></div>
      </div>`;

    const setM = (k, val) => { if (!can("professional")) return go("#/plans"); sc.model[k] = val; markModelCustom(); recompute(); renderModels(); };
    $("#mBasis").addEventListener("change", e => setM("capitalBasis", e.target.value));
    $("#mApproach").addEventListener("change", e => setM("baselApproach", e.target.value));
    $("#mCet1").addEventListener("change", e => setM("cet1Target", Math.min(Math.max(+e.target.value || 10.5, 4), 30) / 100));
    $("#mEcap").addEventListener("change", e => setM("ecapMethod", e.target.value));
    $("#mPd").addEventListener("change", e => setM("elPdBasis", e.target.value));
    $("#mShift").addEventListener("change", e => setM("cycleShift", Math.min(Math.max(+e.target.value || 0, -3), 3)));
    $("#mFloor").addEventListener("change", e => setM("outputFloor", e.target.checked));
    v.querySelectorAll("[data-z]").forEach(inp => inp.addEventListener("change", () => {
      if (!can("professional")) return go("#/plans");
      sc.model.cycleZ[inp.dataset.z] = Math.min(Math.max(+inp.value || 0, -3), 3); markModelCustom(); recompute(); renderModels();
    }));
    applyGates(v);
  }
  function markModelCustom() {
    if (PRESETS.some(p => p.name === sc.name)) sc.name = "Custom scenario";
  }

  // ---- state, routing ---------------------------------------------------------------------------
  function recompute() { // the full book re-runs in ~10 ms, so recompute synchronously
    cur = E.run(book, sc);
    renderBanner();
    if (ui.tab === "scenarios") renderResults();
  }
  function setScenario(s) { sc = s; cur = E.run(book, sc); renderBanner(); }

  const VIEWS = ["overview", "relationships", "accounts", "scenarios", "models", "plans"];
  function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }
  function route() {
    const parts = (location.hash || "#/overview").replace(/^#\//, "").split("/");
    ui.tab = VIEWS.includes(parts[0]) ? parts[0] : "overview";
    ui.relId = ui.tab === "relationships" && parts[1] ? decodeURIComponent(parts[1]) : null;
    document.querySelectorAll("nav.tabs a").forEach(a => {
      if (a.dataset.tab === ui.tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    VIEWS.forEach(t => { $(`#view-${t}`).hidden = t !== ui.tab; });
    hideTip();
    ({ overview: renderOverview, relationships: renderRelationships, accounts: renderAccounts, scenarios: renderScenarios,
       models: renderModels, plans: renderPlans })[ui.tab]();
    renderBanner(); renderPlanChip();
  }

  // shared scenario from ?s=
  try {
    const s = new URLSearchParams(location.search).get("s");
    if (s) sc = Object.assign(clone(BASE), JSON.parse(decodeURIComponent(escape(atob(s)))));
    if (!Array.isArray(sc.newDeals)) sc.newDeals = [];
  } catch { sc = clone(BASE); }
  normalise();
  cur = E.run(book, sc);

  $("#meta").textContent = `As of ${D.asOf} · ${cur.accounts.length.toLocaleString()} accounts · 500 relationships · hurdle ${pct(BASE.hurdle, 0)} · tax ${pct(BASE.taxRate, 0)} · Basel IRB 99.9% economic capital`;
  window.addEventListener("hashchange", route);
  lic.demo = store.get("raroc.demo", sessionStorage) === "1";
  const savedKey = store.get("raroc.license");
  (savedKey ? activate(savedKey, true) : Promise.resolve()).finally(route);
})();
