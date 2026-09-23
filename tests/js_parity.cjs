// Runs the browser engine under Node on exported data; prints results for each model setting.
// Usage: node tests/js_parity.cjs <data.json> <deals.json> <models.json>
const fs = require("fs");
const path = require("path");
const E = require(path.join(__dirname, "..", "src", "raroc", "web", "engine.js"));

const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const deals = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const models = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const book = E.prepare(data);

const out = models.map(model => {
  const sc = E.baseScenario(book.cfg);
  Object.assign(sc.model, model);
  const res = E.run(book, sc);
  const accounts = {};
  for (const a of res.accounts) {
    accounts[a.id] = [a.revenue, a.el, a.capital, a.net, a.raroc, a.econCapital, a.rwa, a.regCapital, a.elLife, a.pdPit ?? null];
  }
  const rels = {};
  for (const r of res.relList) rels[r.relationship_id] = [r.all.raroc, r.lending.raroc];
  const priced = deals.map(d => E.priceDeal(book, sc, res, d));
  return { accounts, rels, priced, belowHurdle: res.belowHurdle };
});
process.stdout.write(JSON.stringify(out));
