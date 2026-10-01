import math, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from core.calc import *


def close(a, b, tol): assert abs(a - b) <= tol, f"{a} vs {b}"


def test_irr_simple():
    close(irr([(0, -100), (1, 110)]), 0.10, 1e-6)
    close(irr([(0, -100), (2, 121)]), 0.10, 1e-6)

def test_irr_no_solution():
    assert irr([(0, 100), (1, 50)]) is None

def test_all_in_cost_matches_thread():
    close(all_in_cost(11_000_000), 11_740_000, 5_000)   # thread: £11.0m -> £11.74m all-in

def test_niy_matches_thread():
    close(1_224_000 / all_in_cost(11_000_000), 0.1043, 0.0005)  # thread: 10.43% NIY

def test_rent_flows_total():
    close(sum(cf for _, cf in rent_flows(1_224_000, 5.5)), 1_224_000 * 5.5, 1)

def test_exit_value_needed_roundtrip():
    cost, r, rent, yrs = all_in_cost(11_000_000), 0.09, 1_224_000, 5.5
    ev = exit_value_needed(cost, r, rent, yrs)
    flows = [(0, -cost)] + rent_flows(rent, yrs) + [(yrs, ev)]
    close(irr(flows), r, 1e-6)

def test_exit_value_in_thread_ballpark():
    # thread: at £11.0m, 9% needs ~£10.1m exit in mid-2032 (~£308 psf). Allow for timing conventions.
    ev = exit_value_needed(all_in_cost(11_000_000), 0.09, 1_224_000, 5.5)
    assert 9.7e6 < ev < 10.5e6, ev

def test_probabilities_must_sum_to_one():
    try:
        weighted_flows(1, 1, 1, [Scenario("a", 0.5)])
        assert False
    except ValueError:
        pass

def test_single_scenario_equals_deterministic():
    cost = all_in_cost(10_000_000)
    sc = [Scenario("sell", 1.0, [(5.5, 9_000_000)])]
    direct = irr([(0, -cost)] + rent_flows(1_224_000, 5.5) + [(5.5, 9_000_000)])
    close(expected_irr(cost, 1_224_000, 5.5, sc), direct, 1e-9)

def test_price_for_target_roundtrip():
    sc = [Scenario("renew", 0.5, [(5.5, 11_000_000)]), Scenario("sell", 0.5, [(5.5, 8_000_000)])]
    p = price_for_target(0.095, 1_224_000, 5.5, sc)
    close(expected_irr(all_in_cost(p), 1_224_000, 5.5, sc), 0.095, 1e-6)

def test_tenant_failure_stops_rent():
    sc = Scenario("fail", 1.0, [(3.0, 5_000_000)])
    flows = scenario_flows(10e6, 1_000_000, 5.5, sc, fail_year=3.0)
    rent = sum(cf for t, cf in flows if 0 < t <= 3.0) - 5_000_000   # strip the sale proceeds at t=3.0
    close(rent, 3_000_000, 1)
    assert max(t for t, _ in flows) == 3.0   # no rent after failure

def test_hard_floor():
    h = hard_floor(11_740_000, 1_224_000, 5.4, deposit=805_000, land_value_net=3_300_000, empty_value=6_600_000)
    close(h["rent_to_expiry"], 6_609_600, 1)
    close(h["money_at_risk"], 11_740_000 - 6_609_600 - 805_000, 1)
    assert h["land_cover"] < 1 < h["empty_cover"]

def test_hard_floor_fully_covered():
    h = hard_floor(1_000, 500, 3, deposit=0, land_value_net=0, empty_value=0)
    assert h["money_at_risk"] == 0 and h["land_cover"] == float("inf")

def test_sensitivity():
    out = sensitivity(exit_value_needed, dict(cost=11e6, target=0.09, annual_rent=1.2e6, lease_years=5.5), "target", [0.07, 0.09, 0.11])
    assert out[0][1] < out[1][1] < out[2][1]
