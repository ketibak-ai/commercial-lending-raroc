"""The browser engine (web/engine.js) must reproduce the Python engine to the dollar."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from raroc import service
from raroc.report import SAMPLE_DEALS, export_data

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")
SCRIPT = Path(__file__).with_name("js_parity.cjs")


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("js")
    (tmp / "data.json").write_text(json.dumps(export_data()))
    deals = [{"rel": d["relationship_id"], "product": d["product"], "amount": d["amount"],
              "tenor": d["tenor_yrs"], "rating": d["rating"], "collateral": d["collateral"],
              "utilization": d.get("utilization", 0.5), "unusedFee": 0.0025, "feePct": 0.005,
              "spread": 0.02} for d in SAMPLE_DEALS]
    (tmp / "deals.json").write_text(json.dumps(deals))
    out = subprocess.run([NODE, str(SCRIPT), str(tmp / "data.json"), str(tmp / "deals.json")],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_every_account_matches(js):
    acc = service.portfolio()["result_accounts"].set_index("account_id")
    got = np.array([js["accounts"][i] for i in acc.index], dtype=float)
    want = acc[["total_revenue", "expected_loss", "economic_capital", "net_income", "raroc"]].to_numpy()
    assert len(js["accounts"]) == len(acc) == 7020
    np.testing.assert_allclose(got[:, :4], want[:, :4], rtol=1e-5, atol=0.01)  # dollars
    np.testing.assert_allclose(got[:, 4], want[:, 4], rtol=1e-5, atol=1e-6)    # RAROC


def test_relationships_match(js):
    rels = service.portfolio()["result_relationships"].set_index("relationship_id")
    for rid, (raroc, lending) in js["rels"].items():
        assert raroc == pytest.approx(rels.loc[rid, "raroc"], abs=1e-6)
        assert (lending or 0) == pytest.approx(rels.loc[rid, "lending_raroc"], abs=1e-6)
    assert js["belowHurdle"] == int((~rels.meets_hurdle).sum())


def test_pricing_matches(js):
    for d, got in zip(SAMPLE_DEALS, js["priced"], strict=True):
        want = service.price(**d)
        assert got["standalone"] == pytest.approx(want["standalone_floor_spread"], abs=2e-5)
        assert got["recommended"] == pytest.approx(want["recommended_spread"], abs=2e-5)
