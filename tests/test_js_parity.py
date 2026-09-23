"""The browser engine (web/engine.js) must reproduce the Python engine under every model setting."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from raroc import service
from raroc.config import ModelSettings
from raroc.report import SAMPLE_DEALS, export_data

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")
SCRIPT = Path(__file__).with_name("js_parity.cjs")

SETTINGS = [
    ModelSettings(),
    ModelSettings(ecap_method="factor"),
    ModelSettings(el_pd_basis="PIT", cycle_shift=-1.0),
    ModelSettings(capital_basis="regulatory", basel_approach="SA"),
    ModelSettings(capital_basis="regulatory", basel_approach="FIRB", cet1_target=0.12),
    ModelSettings(capital_basis="regulatory", basel_approach="AIRB", output_floor=True),
    ModelSettings(capital_basis="max", basel_approach="SA", ecap_method="factor", el_pd_basis="PIT"),
]


def to_js(s: ModelSettings) -> dict:
    return {"capitalBasis": s.capital_basis, "baselApproach": s.basel_approach,
            "outputFloor": s.output_floor, "cet1Target": s.cet1_target, "elPdBasis": s.el_pd_basis,
            "ecapMethod": s.ecap_method, "cycleShift": s.cycle_shift}


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("js")
    (tmp / "data.json").write_text(json.dumps(export_data()))
    deals = [{"rel": d["relationship_id"], "product": d["product"], "amount": d["amount"],
              "tenor": d["tenor_yrs"], "rating": d["rating"], "collateral": d["collateral"],
              "utilization": d.get("utilization", 0.5), "unusedFee": 0.0025, "feePct": 0.005,
              "spread": 0.02} for d in SAMPLE_DEALS]
    (tmp / "deals.json").write_text(json.dumps(deals))
    (tmp / "models.json").write_text(json.dumps([to_js(s) for s in SETTINGS]))
    files = [str(tmp / f) for f in ("data.json", "deals.json", "models.json")]
    out = subprocess.run([NODE, str(SCRIPT), *files],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


COLS = ["total_revenue", "expected_loss", "capital", "net_income", "raroc", "economic_capital",
        "rwa", "reg_capital", "el_lifetime", "pd_pit"]


@pytest.mark.parametrize("i", range(len(SETTINGS)), ids=[repr(s) for s in SETTINGS])
def test_every_account_matches(js, i):
    acc = service.portfolio(SETTINGS[i])["result_accounts"].set_index("account_id")
    got = np.array([js[i]["accounts"][a] for a in acc.index], dtype=float)
    want = acc[COLS].to_numpy(dtype=float)
    assert len(js[i]["accounts"]) == len(acc) == 7020
    dollars = [0, 1, 2, 3, 5, 6, 7, 8]
    np.testing.assert_allclose(got[:, dollars], want[:, dollars], rtol=1e-5, atol=0.01)
    np.testing.assert_allclose(got[:, 4], want[:, 4], rtol=1e-5, atol=1e-6)            # RAROC
    np.testing.assert_allclose(got[:, 9], want[:, 9], rtol=1e-5, atol=1e-9, equal_nan=True)  # PIT PD


@pytest.mark.parametrize("i", range(len(SETTINGS)))
def test_relationships_match(js, i):
    rels = service.portfolio(SETTINGS[i])["result_relationships"].set_index("relationship_id")
    for rid, (raroc, lending) in js[i]["rels"].items():
        assert (raroc or 0) == pytest.approx(rels.loc[rid, "raroc"], abs=1e-6)
        assert (lending or 0) == pytest.approx(rels.loc[rid, "lending_raroc"], abs=1e-6)
    assert js[i]["belowHurdle"] == int((~rels.meets_hurdle).sum())


@pytest.mark.parametrize("i", range(len(SETTINGS)))
def test_pricing_matches(js, i):
    for d, got in zip(SAMPLE_DEALS, js[i]["priced"], strict=True):
        want = service.price(settings=SETTINGS[i], **d)
        assert got["standalone"] == pytest.approx(want["standalone_floor_spread"], abs=2e-5)
        assert got["recommended"] == pytest.approx(want["recommended_spread"], abs=2e-5)
