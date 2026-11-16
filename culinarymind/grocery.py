"""F04: aggregate recipe ingredients (one serving per plan slot), subtract pantry,
group by aisle. Deterministic; ambiguous units are flagged for LLM fallback / user confirmation."""
from collections import defaultdict
from .units import to_base, UnitError

def consolidate(plan, recipes, pantry_items):
    need = defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "category": "Other"})
    review = []
    for slot in plan:
        r = recipes[slot["recipe_id"]]; f = 1 / max(r.get("servings", 1), 1)
        for ing in r["ingredients"]:
            try: q, dim = to_base(ing["qty"] * f, ing["unit"])
            except UnitError:
                review.append({"name": ing["name"], "qty": round(ing["qty"] * f, 2), "unit": ing["unit"],
                               "reason": "ambiguous unit - confirm weight/volume"}); continue
            e = need[(ing["name"], dim)]
            e["qty"] += q; e["cost"] += ing.get("cost", 0) * f; e["category"] = ing.get("category", "Other")
    have = defaultdict(float)
    for p in pantry_items:
        try: q, dim = to_base(p["qty"], p["unit"]); have[(p["name"], dim)] += q
        except UnitError: pass
    out = defaultdict(list)
    for (name, dim), e in sorted(need.items()):
        missing = e["qty"] - have.get((name, dim), 0)
        if missing > 1e-6:
            out[e["category"]].append({"name": name, "qty": round(missing, 1), "unit": dim,
                                       "est_cost": round(e["cost"] * missing / e["qty"], 2)})
    return {"by_aisle": dict(out), "needs_review": review,
            "total_cost": round(sum(i["est_cost"] for v in out.values() for i in v), 2)}
