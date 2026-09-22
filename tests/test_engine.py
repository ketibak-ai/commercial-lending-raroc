import numpy as np
import pytest

from raroc import config as C
from raroc import service
from raroc.engine import ftp_rate, irb_capital_k
from raroc.pricing import DealRequest, price_deal


@pytest.fixture(scope="module")
def book():
    return service.portfolio()


def test_account_counts(book):
    assert len(book["loans"]) == 1000
    assert len(book["revolvers"]) == 2000
    assert len(book["irds"]) == 20
    assert len(book["deposits"]) == 2000
    assert len(book["payments"]) == 2000
    assert len(book["result_accounts"]) == 7020


def test_ten_key_relationships_hold_every_product(book):
    rels = book["result_relationships"]
    key = rels[rels.segment == "Key Relationship"]
    assert len(key) == 10
    assert (key.n_term_loan > 0).all() and (key.n_deposit > 0).all() and (key.n_payments > 0).all()
    # all derivatives belong to key relationships
    assert set(book["irds"].relationship_id) <= set(key.relationship_id)


def test_simulation_is_deterministic():
    a = service.simulate(C.SEED)["loans"]
    b = service.simulate(C.SEED)["loans"]
    assert a.equals(b)


def test_ftp_interpolation():
    assert ftp_rate(1.0) == pytest.approx(C.FTP_CURVE[1.0])
    assert C.FTP_CURVE[1.0] > ftp_rate(1.5) > C.FTP_CURVE[2.0]


def test_irb_capital_monotonic_in_pd_and_maturity():
    pds = np.array([0.001, 0.01, 0.05])
    k = irb_capital_k(pds, np.full(3, 0.45), np.full(3, 2.5))
    assert (np.diff(k) > 0).all()
    assert irb_capital_k([0.01], [0.45], [5])[0] > irb_capital_k([0.01], [0.45], [1])[0]
    # Basel reference point: PD 1%, LGD 45%, M 2.5 -> K about 7.4%
    assert k[1] == pytest.approx(0.0739, abs=0.002)


def test_raroc_identity(book):
    acc = book["result_accounts"]
    np.testing.assert_allclose(acc.raroc, acc.net_income / acc.economic_capital)
    np.testing.assert_allclose(acc.eva, acc.net_income - C.CAPITAL.hurdle_rate * acc.economic_capital)


def test_deposits_and_payments_lift_relationship_raroc(book):
    rels = book["result_relationships"]
    key = rels[rels.segment == "Key Relationship"]
    assert (key.raroc > key.lending_raroc).all()


def test_standalone_price_hits_hurdle():
    req = DealRequest(product="Term Loan", amount=20e6, tenor_yrs=5, rating=5)
    r = price_deal(req)
    assert r["at_recommended"]["deal_raroc"] == pytest.approx(C.CAPITAL.hurdle_rate, abs=1e-3)


def test_relationship_pricing_respects_cost_floor():
    r = service.price(product="Term Loan", amount=25e6, tenor_yrs=5, rating=4,
                      collateral="Senior Secured", relationship_id="R004")
    assert r["recommended_spread"] >= r["cost_floor_spread"]
    assert r["recommended_spread"] <= r["standalone_floor_spread"]


def test_weak_relationship_gets_little_concession():
    strong = service.price(product="Revolver", amount=40e6, tenor_yrs=3, rating=7,
                           collateral="Unsecured", relationship_id="R004", utilization=0.3)
    weak = service.price(product="Revolver", amount=40e6, tenor_yrs=3, rating=7,
                         collateral="Unsecured", relationship_id="R007", utilization=0.3)
    assert weak["recommended_spread"] > strong["recommended_spread"]


@pytest.mark.parametrize("bad", [dict(rating=11), dict(product="Bond"), dict(amount=-1),
                                 dict(collateral="Gold")])
def test_invalid_deal_rejected(bad):
    with pytest.raises(ValueError):
        price_deal(DealRequest(**bad))
