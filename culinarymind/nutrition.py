"""F07: deterministic nutrient totals vs targets + LLM (or template) narrative."""
import json
from .llm import LLMError

ACT = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725}
GOAL = {"lose": -400, "maintain": 0, "gain": 300}
HINTS = {"fiber_g": "chia seeds, lentils or oats", "calcium_mg": "yogurt, tofu or fortified milk", "iron_mg": "lentils, spinach or beef",
         "protein": "eggs, chicken or tofu", "kcal": "a snack such as a yogurt parfait"}

def targets(profile):
    w = float(profile.get("weight_kg", 70)); age = int(profile.get("age", 25))
    kcal = w * 24 * ACT.get(profile.get("activity", "moderate"), 1.55) + GOAL.get(profile.get("goal", "maintain"), 0)
    return {"kcal": round(kcal), "protein": round(w * (1.2 if profile.get("goal") == "gain" else 0.8)),
            "fiber_g": 25, "calcium_mg": 1200 if age > 50 else 1000, "iron_mg": 8, "sodium_mg": 2300}

def analyze(plan_model, profile, llm=None, use_llm=True):
    plan = plan_model.get_plan()
    if not plan: return {"ok": False, "error": "No meal plan to analyse"}
    tg = targets(profile); days, missing = {}, set()
    for s in plan:
        r = plan_model.recipes[s["recipe_id"]]; d = days.setdefault(s["day"], dict.fromkeys(("kcal", "protein", "carbs", "fat", "fiber_g", "sodium_mg", "calcium_mg", "iron_mg"), 0.0))
        for k, v in r["macros"].items(): d[k] += v
        if "micros" in r:
            for k, v in r["micros"].items(): d[k] += v
        else: missing.add(r["id"])
    avg = {k: round(sum(d[k] for d in days.values()) / len(days), 1) for k in next(iter(days.values()))}
    comp = {k: round(100 * avg[k] / tg[k]) for k in tg}
    warnings = []
    for k, pct in comp.items():
        if k == "sodium_mg":
            if pct > 100: warnings.append(f"Sodium is {pct}% of the daily limit")
        elif pct < 70: warnings.append(f"{k.replace('_', ' ')} is low ({pct}% of target)")
        elif k == "kcal" and pct > 130: warnings.append(f"Calories are high ({pct}% of target)")
    for d, v in sorted(days.items()):
        if v["fiber_g"] < 0.6 * tg["fiber_g"]: warnings.append(f"Day {d} is low in fiber ({round(v['fiber_g'])} g)")
    summary = {"targets": tg, "average_daily": avg, "compliance_pct": comp, "warnings": warnings}
    narrative, nmode = None, "template"
    if use_llm and llm is not None:
        try:
            res = llm.generate([{"role": "user", "content": json.dumps({"task": "Write a concise 2-3 sentence nutrition summary with one practical suggestion.", "data": summary})}],
                               system="You are a friendly dietitian assistant.")
            if res["text"].strip(): narrative, nmode = res["text"].strip(), "llm"
        except LLMError: pass
    if narrative is None:
        low = [k for k, p in comp.items() if k != "sodium_mg" and p < 70]
        narrative = ("Your plan looks well balanced." if not low else
                     "Gaps: " + "; ".join(f"{k.replace('_', ' ')} (consider {HINTS.get(k, 'more variety')})" for k in low) + ".")
    return {"ok": True, "daily": days, **summary, "narrative": narrative, "narrative_mode": nmode,
            "missing_data": sorted(missing)}
