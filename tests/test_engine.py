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
    np.testing.assert_allclose(acc.raroc, acc.net_income / acc.capital)
    np.testing.assert_allclose(acc.eva, acc.net_income - C.CAPITAL.hurdle_rate * acc.capital)


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


# ---- risk and capital models ---------------------------------------------------------------
from raroc.config import ModelSettings  # noqa: E402
from raroc.engine import ecap_factor_table, pit_pd  # noqa: E402


def test_pit_pd_moves_with_the_cycle():
    ttc = np.array([0.005])
    assert pit_pd(ttc, [-1.0])[0] > ttc[0] > pit_pd(ttc, [1.0])[0]
    assert pit_pd(ttc, [0.0])[0] == pytest.approx(0.005, rel=1e-6)


def test_ecap_factor_table_monotonic():
    t = ecap_factor_table()
    assert (t.diff(axis=0).iloc[1:] > 0).all().all()   # worse rating -> more capital
    assert (t.diff(axis=1).iloc[:, 1:] > 0).all().all()  # longer maturity -> more capital


def test_regulatory_capital_is_rwa_times_cet1():
    s = ModelSettings(capital_basis="regulatory", basel_approach="SA", cet1_target=0.12)
    acc = service.portfolio(s)["result_accounts"]
    np.testing.assert_allclose(acc.reg_capital, acc.rwa * 0.12)
    np.testing.assert_allclose(acc.capital, acc.reg_capital)


def test_output_floor_only_raises_rwa():
    base = service.portfolio(ModelSettings(basel_approach="AIRB"))["result_accounts"].rwa
    floor = ModelSettings(basel_approach="AIRB", output_floor=True)
    floored = service.portfolio(floor)["result_accounts"].rwa
    assert (floored >= base - 1e-6).all() and floored.sum() > base.sum()


def test_max_basis_is_binding_constraint():
    acc = service.portfolio(ModelSettings(capital_basis="max", basel_approach="SA"))["result_accounts"]
    np.testing.assert_allclose(acc.capital, np.maximum(acc.economic_capital, acc.reg_capital))


def test_downturn_raises_pit_expected_loss():
    calm = service.portfolio(ModelSettings(el_pd_basis="PIT"))["result_accounts"].expected_loss.sum()
    stress = service.portfolio(ModelSettings(el_pd_basis="PIT", cycle_shift=-1.5))["result_accounts"]
    assert stress.expected_loss.sum() > 2 * calm
    credit = stress[stress["product"].isin(["Term Loan", "Revolver", "Interest Rate Derivative"])]
    assert (credit.el_lifetime >= credit.expected_loss - 1e-6).all()


def test_invalid_settings_rejected():
    with pytest.raises(ValueError):
        ModelSettings(basel_approach="Basel IV").validate()


# ---- rate curves ------------------------------------------------------------------------------
from raroc.engine import curve_rate, liquidity_premium  # noqa: E402


def test_ftp_is_sofr_plus_liquidity_premium():
    for t in (0.25, 1, 2.5, 5, 7, 10):
        assert ftp_rate(t) == pytest.approx(curve_rate(C.SOFR_CURVE, t) + liquidity_premium(t))
    # calibrated so the SOFR-based FTP reproduces the original matched-maturity curve exactly
    original = {0.25: 0.0410, 1.0: 0.0385, 2.0: 0.0370, 3.0: 0.0365, 5.0: 0.0370, 7.0: 0.0380, 10.0: 0.0395}
    for t, r in original.items():
        assert ftp_rate(t) == pytest.approx(r, abs=1e-12)


def test_all_in_rate_uses_sofr_index(book):
    loans = book["loans"].set_index("account_id")
    acc = book["result_accounts"].set_index("account_id")
    fl = loans[loans.rate_type == "Floating"].index[0]
    fx = loans[loans.rate_type == "Fixed"].index[0]
    assert acc.loc[fl, "all_in_rate"] == pytest.approx(C.SOFR_CURVE[1 / 12] + loans.loc[fl, "spread"])
    assert acc.loc[fx, "all_in_rate"] == pytest.approx(
        curve_rate(C.SOFR_CURVE, loans.loc[fx, "tenor_yrs"]) + loans.loc[fx, "spread"])
