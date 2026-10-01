"""Deal calculator. All arithmetic lives here, in plain tested code, never in the LLM.

Cash flows are (t_years, amount) pairs. Rent is modelled quarterly in arrears.
"""
from dataclasses import dataclass, field


def npv(rate, flows):
    return sum(cf / (1 + rate) ** t for t, cf in flows)


def irr(flows, lo=-0.9, hi=1.0, tol=1e-9):
    """Bisection IRR. Returns None if no sign change (no real IRR)."""
    f_lo, f_hi = npv(lo, flows), npv(hi, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid, flows)
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def all_in_cost(price, sdlt_rate=0.05, fee_rate=0.0176):
    """Price plus acquisition costs. Defaults reproduce £11.74m on £11.0m (SDLT ~5% + fees/VAT ~1.76%). Override per deal."""
    return price * (1 + sdlt_rate + fee_rate)


def rent_flows(annual_rent, years, start=0.0):
    """Quarterly rent in arrears over `years` (can be fractional)."""
    flows, t = [], 0.25
    while t < years + 1e-9:
        flows.append((start + t, annual_rent / 4))
        t += 0.25
    rem = years - (t - 0.25)
    if rem > 1e-6:
        flows.append((start + years, annual_rent * rem))
    return flows


@dataclass
class Scenario:
    name: str
    probability: float
    # extra cash flows after the lease ends, as (t_years, amount), t measured from completion
    flows: list = field(default_factory=list)


def scenario_flows(cost, annual_rent, lease_years, sc: Scenario, fail_year=None):
    """Full cash flow for a scenario: -cost at t=0, rent until lease end (or failure), then scenario flows."""
    rent_years = fail_year if fail_year is not None else lease_years
    return [(0.0, -cost)] + rent_flows(annual_rent, rent_years) + sc.flows


def weighted_flows(cost, annual_rent, lease_years, scenarios, fail_years=None):
    """Probability-weighted expected cash flows. fail_years: {scenario_name: years_of_rent_before_failure}."""
    total_p = sum(s.probability for s in scenarios)
    if abs(total_p - 1) > 1e-6:
        raise ValueError(f"Scenario probabilities sum to {total_p}, not 1")
    fail_years = fail_years or {}
    out = {}
    for s in scenarios:
        for t, cf in scenario_flows(cost, annual_rent, lease_years, s, fail_years.get(s.name)):
            out[t] = out.get(t, 0.0) + s.probability * cf
    return sorted(out.items())


def expected_irr(cost, annual_rent, lease_years, scenarios, fail_years=None):
    return irr(weighted_flows(cost, annual_rent, lease_years, scenarios, fail_years))


def value_at_target(target, annual_rent, lease_years, scenarios, fail_years=None):
    """Probability-weighted PV of all inflows at the target return = the max all-in cost you can pay."""
    flows = weighted_flows(0.0, annual_rent, lease_years, scenarios, fail_years)
    return npv(target, flows)


def price_for_target(target, annual_rent, lease_years, scenarios, fail_years=None, sdlt_rate=0.05, fee_rate=0.0176):
    """Max headline price that still earns `target` (after acquisition costs)."""
    return value_at_target(target, annual_rent, lease_years, scenarios, fail_years) / (1 + sdlt_rate + fee_rate)


def exit_value_needed(cost, target, annual_rent, lease_years):
    """Sale price at lease end needed to hit `target` unlevered return on all-in `cost`, rent as contracted."""
    pv_rent = npv(target, rent_flows(annual_rent, lease_years))
    return (cost - pv_rent) * (1 + target) ** lease_years


def hard_floor(cost, annual_rent, lease_years, deposit=0.0, land_value_net=0.0, empty_value=0.0):
    """Fukuoka Dome test: undiscounted certain cash vs all-in cost.

    certain = contracted rent to lease end + deposit. Money at risk = cost - certain.
    Cover ratios compare the land (hard floor) and empty-building value with the money at risk.
    """
    rent_total = annual_rent * lease_years
    certain = rent_total + deposit
    at_risk = max(cost - certain, 0.0)
    return {
        "rent_to_expiry": rent_total,
        "certain_cash": certain,
        "money_at_risk": at_risk,
        "land_cover": (land_value_net / at_risk) if at_risk else float("inf"),
        "empty_cover": (empty_value / at_risk) if at_risk else float("inf"),
        "floor_returns_pct_of_cost": certain / cost,
        "break_even_cost_land_floor": certain + land_value_net,  # all-in cost fully recovered even if office thesis fails
    }


def sensitivity(fn, base_kwargs, param, values):
    """Re-run fn(**base_kwargs) varying one parameter. Returns [(value, result)]."""
    out = []
    for v in values:
        kw = dict(base_kwargs)
        kw[param] = v
        out.append((v, fn(**kw)))
    return out
