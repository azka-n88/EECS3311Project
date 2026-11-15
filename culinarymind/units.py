"""Deterministic unit conversion into base units (g for mass, ml for volume, pc for count)."""
MASS = {"g": 1, "kg": 1000, "oz": 28.3495, "lb": 453.592}
VOLUME = {"ml": 1, "l": 1000, "tsp": 4.92892, "tbsp": 14.7868, "cup": 236.588}
COUNT = {"pc": 1, "piece": 1, "pcs": 1, "unit": 1, "": 1}

class UnitError(ValueError): pass

def to_base(qty: float, unit: str):
    """Return (quantity_in_base, base_unit). Raises UnitError for unknown units
    (caller may fall back to the LLM for e.g. 'bunch')."""
    u = unit.lower().strip()
    if u in MASS: return qty * MASS[u], "g"
    if u in VOLUME: return qty * VOLUME[u], "ml"
    if u in COUNT: return qty * COUNT[u], "pc"
    raise UnitError(f"Unknown unit: {unit!r}")

def convert(qty: float, from_unit: str, to_unit: str) -> float:
    base, dim = to_base(qty, from_unit)
    tb, tdim = to_base(1, to_unit)
    if dim != tdim:
        raise UnitError(f"Cannot convert {from_unit} to {to_unit}")
    return base / tb
