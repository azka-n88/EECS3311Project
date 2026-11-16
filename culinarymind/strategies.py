"""STRATEGY pattern: interchangeable candidate-ranking heuristics for meal planning."""
from abc import ABC, abstractmethod
from .models import recipe_cost

class PlanStrategy(ABC):
    name = ""
    @abstractmethod
    def score(self, recipe, ctx) -> float: ...
    def rank(self, recipes, ctx):
        return sorted(recipes, key=lambda r: -self.score(r, ctx))

class BudgetFirstStrategy(PlanStrategy):
    name = "budget"
    def score(self, recipe, ctx): return -recipe_cost(recipe)

class ZeroWasteStrategy(PlanStrategy):
    name = "zero_waste"
    def score(self, recipe, ctx):
        hits = sum(1 for i in recipe["ingredients"] if i["name"] in ctx.get("expiring", ()))
        return hits * 10 - recipe_cost(recipe) * 0.1

class HighProteinStrategy(PlanStrategy):
    name = "protein"
    def score(self, recipe, ctx): return recipe["macros"]["protein"]

STRATEGIES = {s.name: s for s in (BudgetFirstStrategy(), ZeroWasteStrategy(), HighProteinStrategy())}

def get_strategy(name):
    if name not in STRATEGIES: raise ValueError(f"Unknown strategy {name!r}; choose from {list(STRATEGIES)}")
    return STRATEGIES[name]
