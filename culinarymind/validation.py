"""CHAIN OF RESPONSIBILITY: sequential plan validation with early exit on first failing handler.
ctx keys: recipes (dict), allergens (set), diet (str|None), budget (float|None), kcal (float|None)."""
from abc import ABC, abstractmethod
from .models import recipe_cost

class PlanValidationHandler(ABC):
    def __init__(self): self._next = None
    def set_next(self, handler): self._next = handler; return handler
    def handle(self, plan, ctx):
        issues = self.check(plan, ctx)
        if issues: return issues                      # early exit
        return self._next.handle(plan, ctx) if self._next else []
    @abstractmethod
    def check(self, plan, ctx) -> list: ...

class AllergenCheckHandler(PlanValidationHandler):
    def check(self, plan, ctx):
        bad = set(a.lower() for a in ctx.get("allergens") or ())
        return [f"Day {s['day']} {s['meal']}: {ctx['recipes'][s['recipe_id']]['title']} contains allergen {a}"
                for s in plan for a in ctx["recipes"][s["recipe_id"]]["allergens"] if a in bad]

class DietCheckHandler(PlanValidationHandler):
    def check(self, plan, ctx):
        diet = ctx.get("diet")
        if not diet: return []
        ok = {diet} | ({"vegan"} if diet == "vegetarian" else set())
        return [f"Day {s['day']} {s['meal']}: {ctx['recipes'][s['recipe_id']]['title']} is not {diet}"
                for s in plan if not ok & set(ctx["recipes"][s["recipe_id"]]["tags"])]

class BudgetCheckHandler(PlanValidationHandler):
    def check(self, plan, ctx):
        if ctx.get("budget") is None: return []
        total = round(sum(recipe_cost(ctx["recipes"][s["recipe_id"]]) for s in plan), 2)
        return [f"Estimated cost ${total} exceeds budget ${ctx['budget']}"] if total > ctx["budget"] else []

class MacroCheckHandler(PlanValidationHandler):
    TOL = 0.30
    def check(self, plan, ctx):
        target = ctx.get("kcal")
        if not target: return []
        days = {}
        for s in plan: days[s["day"]] = days.get(s["day"], 0) + ctx["recipes"][s["recipe_id"]]["macros"]["kcal"]
        return [f"Day {d}: {k} kcal is outside +/-{int(self.TOL*100)}% of target {target}"
                for d, k in sorted(days.items()) if not (target * (1 - self.TOL) <= k <= target * (1 + self.TOL))]

def build_default_chain():
    head = AllergenCheckHandler()
    head.set_next(DietCheckHandler()).set_next(BudgetCheckHandler()).set_next(MacroCheckHandler())
    return head
