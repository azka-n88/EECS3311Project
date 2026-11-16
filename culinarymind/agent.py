"""AgentExecutionEngine: reasoning loop for F02 (plan generation) and F03 (meal swap).
Behaviours: multi-step planning, tool use (LLM may call tools), RAG-capable toolset,
short-term memory (recent requests), long-term memory (preference rules in DB),
self-reflection (validation feedback -> retry up to 3x), deterministic fallback."""
import json, re
from collections import Counter
from .llm import LLMError
from .models import recipe_cost
from .strategies import get_strategy
from .validation import build_default_chain

SYSTEM = ("You are CulinaryMind, a meal-planning agent. You may call the provided tools to inspect the pantry or "
          "search recipes. Choose ONLY recipe ids from the supplied candidates. Respect every constraint and "
          "user preference. When you are ready, reply with ONLY a JSON object in the requested output_format.")

class AgentExecutionEngine:
    MAX_RETRIES = 3; MAX_TOOL_STEPS = 3; MAX_USES = 2

    def __init__(self, llm, tools, pantry, plan_model, con):
        self.llm, self.tools, self.pantry, self.plan, self.con = llm, tools, pantry, plan_model, con
        self.chain = build_default_chain()
        self.memory = []            # short-term: recent requests
        self.last_ctx = None

    # ---- long-term memory (populated by F10) ----
    def preferences(self):
        return [r["rule"] for r in self.con.execute("SELECT rule FROM preferences ORDER BY id")]

    # ---- helpers ----
    def _ctx(self, **kw):
        ctx = {"recipes": self.plan.recipes, "allergens": set(a.lower() for a in kw.get("allergens") or ()),
               "diet": kw.get("diet"), "budget": kw.get("budget"), "kcal": kw.get("kcal"),
               "expiring": {i["name"] for i in self.pantry.expiring_soon()}}
        return ctx

    def _pool(self, ctx, max_prep=None):
        pool = []
        for r in self.plan.recipes.values():
            if ctx["allergens"] & set(r["allergens"]): continue
            if ctx["diet"] and not ({ctx["diet"]} | ({"vegan"} if ctx["diet"] == "vegetarian" else set())) & set(r["tags"]): continue
            if max_prep is not None and r["prep_min"] > max_prep: continue
            pool.append(r)
        return pool

    @staticmethod
    def _brief(r, ctx):
        return {"id": r["id"], "title": r["title"], "meals": r["meals"], "cost": recipe_cost(r),
                "kcal": r["macros"]["kcal"], "protein": r["macros"]["protein"], "prep_min": r["prep_min"],
                "tags": r["tags"], "uses_expiring": [i["name"] for i in r["ingredients"] if i["name"] in ctx["expiring"]]}

    @staticmethod
    def _parse_json(text):
        m = re.search(r"\{.*\}", text or "", re.S)
        if not m: raise ValueError("response contained no JSON object")
        return json.loads(m.group(0))

    def _converse(self, messages):
        specs = [self.tools[n].spec() for n in ("get_pantry_items", "search_recipes") if n in self.tools]
        for step in range(self.MAX_TOOL_STEPS + 1):
            res = self.llm.generate(messages, tools=specs, system=SYSTEM)
            if res["tool_calls"] and step < self.MAX_TOOL_STEPS:
                for c in res["tool_calls"]:
                    tool = self.tools.get(c["name"])
                    try: out = tool.run(**c["arguments"]) if tool else {"error": "unknown tool"}
                    except Exception as e: out = {"error": str(e)}
                    messages.append({"role": "assistant", "content": f"[calling {c['name']} {json.dumps(c['arguments'])}]"})
                    messages.append({"role": "user", "content": "Tool result: " + json.dumps(out)[:4000]})
                continue
            messages.append({"role": "assistant", "content": res["text"]})
            return res["text"]
        return ""

    def _structural(self, plan, days, meals):
        if not isinstance(plan, list): return ["'plan' must be a list of {day, meal, recipe_id}"]
        issues, seen = [], set()
        for s in plan:
            try: key = (int(s["day"]), s["meal"]); rid = s["recipe_id"]
            except (KeyError, TypeError, ValueError): issues.append(f"Malformed slot {s}"); continue
            if rid not in self.plan.recipes: issues.append(f"Unknown recipe id {rid}"); continue
            if s["meal"] not in self.plan.recipes[rid]["meals"]: issues.append(f"{rid} is not a {s['meal']} recipe")
            seen.add(key)
        want = {(d, m) for d in range(1, days + 1) for m in meals}
        if want - seen: issues.append(f"Missing slots: {sorted(want - seen)}")
        return issues

    # ---- deterministic planner (fallback / repair) ----
    def _greedy(self, days, meals, pool, strategy, ctx):
        uses, plan, spent = Counter(), [], 0.0
        mincost = min(recipe_cost(r) for r in pool); remaining = days * len(meals)
        for d in range(1, days + 1):
            today = set()
            for m in meals:
                remaining -= 1
                base = [r for r in strategy.rank(pool, ctx) if m in r["meals"]]
                if not base: return None
                opts = [r for r in base if r["id"] not in today and uses[r["id"]] < self.MAX_USES] or base
                if ctx.get("budget") is not None:
                    aff = [r for r in opts if spent + recipe_cost(r) + remaining * mincost <= ctx["budget"]]
                    opts = aff or sorted(opts, key=recipe_cost)[:1]
                if ctx.get("kcal"):
                    share = ctx["kcal"] / len(meals)
                    opts = sorted(opts[:5], key=lambda r: abs(r["macros"]["kcal"] - share)) + opts[5:]
                r = opts[0]; uses[r["id"]] += 1; today.add(r["id"]); spent += recipe_cost(r)
                plan.append({"day": d, "meal": m, "recipe_id": r["id"]})
        return plan

    # ---- F02 ----
    def generate_plan(self, days=3, budget=None, kcal=None, diet=None, allergens=(), strategy="budget",
                      meals=("breakfast", "lunch", "dinner"), max_prep=None, use_llm=True):
        ctx = self._ctx(budget=budget, kcal=kcal, diet=diet, allergens=allergens); strat = get_strategy(strategy)
        self.last_ctx = {"budget": budget, "kcal": kcal, "diet": diet, "allergens": allergens,
                         "strategy": strategy, "max_prep": max_prep}
        self.memory = (self.memory + [f"plan {days}d budget={budget} diet={diet} allergens={list(allergens)} strategy={strategy}"])[-5:]
        pool = self._pool(ctx, max_prep)
        meals = tuple(meals)
        # Reasoning: feasibility pre-check (impossible constraints)
        missing = [m for m in meals if not any(m in r["meals"] for r in pool)]
        if missing:
            return {"ok": False, "issues": [f"No recipes available for {', '.join(missing)} under these constraints"],
                    "suggestions": ["Relax diet/allergen filters or the max prep time"]}
        if budget is not None:
            per_day = sum(min(recipe_cost(r) for r in pool if m in r["meals"]) for m in meals)
            if per_day * days > budget:
                ok_days = int(budget // per_day)
                return {"ok": False, "issues": [f"Cheapest possible {days}-day plan costs ${round(per_day*days,2)}, over budget ${budget}"],
                        "suggestions": [f"Raise budget to at least ${round(per_day*days,2)}",
                                        f"Or reduce the plan to {ok_days} day(s)" if ok_days else "Or relax dietary restrictions"]}
        plan, mode, attempts, issues = None, "greedy", 0, []
        if use_llm:
            payload = {"task": f"Plan {days} day(s) with meals {list(meals)} (one serving per slot).",
                       "constraints": {"budget": budget, "target_kcal_per_day": kcal, "diet": diet, "excluded_allergens": sorted(ctx["allergens"]), "max_prep_min": max_prep},
                       "strategy": strat.name, "expiring_pantry_items": sorted(ctx["expiring"]),
                       "user_preferences": self.preferences(), "recent_requests": self.memory,
                       "candidates": [self._brief(r, ctx) for r in strat.rank(pool, ctx)],
                       "output_format": {"plan": [{"day": 1, "meal": "breakfast", "recipe_id": "<candidate id>"}]}}
            messages = [{"role": "user", "content": json.dumps(payload)}]
            try:
                for attempts in range(1, self.MAX_RETRIES + 1):
                    text = self._converse(messages)
                    try: cand = self._parse_json(text).get("plan")
                    except (ValueError, AttributeError) as e: cand, issues = None, [f"Invalid JSON: {e}"]
                    else:
                        issues = self._structural(cand, days, meals)
                        if not issues: issues = self.chain.handle(cand, ctx)       # Chain of Responsibility
                    if not issues: plan, mode = cand, "llm"; break
                    messages.append({"role": "user", "content": "Plan rejected: " + "; ".join(issues) + ". Fix these and return corrected JSON only."})
            except LLMError as e:
                issues = [f"LLM unavailable: {e}"]; mode = "greedy-fallback"
        if plan is None:                                 # deterministic planner (fallback or repair)
            cand = self._greedy(days, meals, pool, strat, ctx)
            gi = self.chain.handle(cand, ctx) if cand else ["No feasible plan"]
            if not gi:
                plan = cand; mode = "greedy-fallback" if mode == "greedy-fallback" else ("llm+greedy-repair" if use_llm else "greedy")
            else: issues = gi
        if plan is None:
            return {"ok": False, "issues": issues, "suggestions": ["Relax budget, calories or dietary constraints"], "attempts": attempts}
        self.plan.clear()
        for s in sorted(plan, key=lambda s: (int(s["day"]), meals.index(s["meal"]) if s["meal"] in meals else 9)):
            self.plan.set_slot(int(s["day"]), s["meal"], s["recipe_id"])
        names = {i["name"] for s in plan for i in self.plan.recipes[s["recipe_id"]]["ingredients"]}
        have = {i["name"] for i in self.pantry.list_items()}
        return {"ok": True, "mode": mode, "attempts": attempts, "plan": self.plan.get_plan(),
                "total_cost": self.plan.total_cost(), "pantry_utilization_pct": round(100 * len(names & have) / max(len(names), 1)),
                "notes": issues if mode != "llm" else []}

    # ---- F03 ----
    def swap_meal(self, day, meal, reason="", max_prep=None, use_llm=True):
        cur = next((s for s in self.plan.get_plan() if s["day"] == day and s["meal"] == meal), None)
        if not cur: return {"ok": False, "issues": [f"No meal planned for day {day} {meal}"], "suggestions": []}
        lc = self.last_ctx or {}
        ctx = self._ctx(budget=None, kcal=None, diet=lc.get("diet"), allergens=lc.get("allergens") or ())
        used = {s["recipe_id"] for s in self.plan.get_plan()}
        pool = [r for r in self._pool(ctx, max_prep if max_prep is not None else lc.get("max_prep")) if meal in r["meals"] and r["id"] != cur["recipe_id"]]
        fresh = [r for r in pool if r["id"] not in used] or pool
        if not fresh:
            return {"ok": False, "issues": ["No alternative matches the constraints"],
                    "suggestions": ["Relax the prep-time limit", "Relax diet/allergen filters", "Pull a recipe from an external web search"]}
        strat = get_strategy(lc.get("strategy", "budget")); ranked = strat.rank(fresh, ctx)
        self.memory = (self.memory + [f"swap day{day} {meal}: {reason}"])[-5:]
        new_id, mode = None, "greedy"
        if use_llm:
            payload = {"task": f"Replace the {meal} on day {day} ({self.plan.recipes[cur['recipe_id']]['title']}).",
                       "reason": reason, "other_meals_in_plan": [s for s in self.plan.get_plan() if s != cur],
                       "user_preferences": self.preferences(), "candidates": [self._brief(r, ctx) for r in ranked],
                       "output_format": {"recipe_id": "<candidate id>"}}
            messages = [{"role": "user", "content": json.dumps(payload)}]
            try:
                for _ in range(2):
                    try: rid = self._parse_json(self._converse(messages)).get("recipe_id")
                    except (ValueError, AttributeError): rid = None
                    if rid in {r["id"] for r in fresh}: new_id, mode = rid, "llm"; break
                    messages.append({"role": "user", "content": "Invalid choice. Return JSON with a recipe_id from the candidates only."})
            except LLMError: mode = "greedy-fallback"
        if new_id is None: new_id = ranked[0]["id"]
        self.plan.set_slot(day, meal, new_id)
        return {"ok": True, "mode": mode, "old": cur["recipe_id"], "new": new_id, "title": self.plan.recipes[new_id]["title"]}
