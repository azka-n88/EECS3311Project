"""Agent tools + FACTORY METHOD pattern.
Creator: ToolFactory | Concrete creator: SystemToolFactory | Product: BaseTool and subclasses."""
import json, math, re
from abc import ABC, abstractmethod
from collections import Counter
from . import config
from .models import recipe_cost

class BaseTool(ABC):
    name = ""; description = ""; parameters = {"type": "object", "properties": {}}
    @abstractmethod
    def run(self, **kw): ...
    def spec(self): return {"name": self.name, "description": self.description, "parameters": self.parameters}

class PantryLookupTool(BaseTool):
    name = "get_pantry_items"; description = "List pantry items with quantity, unit, expiry date and expiry status."
    def __init__(self, pantry): self.pantry = pantry
    def run(self, **kw):
        return [{k: i[k] for k in ("name", "qty", "unit", "expiry_date", "status")} for i in self.pantry.list_items()]

class RecipeSearchTool(BaseTool):
    name = "search_recipes"; description = "Search the recipe database by text, tag, max prep minutes, max cost per serving."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}, "tag": {"type": "string"},
                  "max_prep_min": {"type": "number"}, "max_cost": {"type": "number"}}}
    def __init__(self, recipes): self.recipes = recipes
    def run(self, query="", tag=None, max_prep_min=None, max_cost=None, **kw):
        out = []
        for r in self.recipes.values():
            if query and query.lower() not in (r["title"] + " " + " ".join(i["name"] for i in r["ingredients"])).lower(): continue
            if tag and tag not in r["tags"]: continue
            if max_prep_min is not None and r["prep_min"] > max_prep_min: continue
            if max_cost is not None and recipe_cost(r) > max_cost: continue
            out.append({"id": r["id"], "title": r["title"], "cost": recipe_cost(r), "prep_min": r["prep_min"],
                        "kcal": r["macros"]["kcal"], "meals": r["meals"]})
        return out[:15]

class MacroCalcTool(BaseTool):
    name = "calculate_macros"; description = "Sum calories/protein/carbs/fat per day for the current meal plan."
    def __init__(self, plan_model): self.plan = plan_model
    def run(self, **kw):
        days = {}
        for s in self.plan.get_plan():
            m = self.plan.recipes[s["recipe_id"]]["macros"]
            d = days.setdefault(s["day"], {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0})
            for k in d: d[k] += m[k]
        n = max(len(days), 1)
        avg = {k: round(sum(d[k] for d in days.values()) / n, 1) for k in ("kcal", "protein", "carbs", "fat")}
        return {"daily": days, "average_daily": avg}

class RAGSearchTool(BaseTool):
    """Lightweight retrieval (TF-IDF) over verified culinary technique documents."""
    name = "search_techniques"; description = "Retrieve culinary technique/substitution guidance relevant to a question."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    def __init__(self, path=None):
        self.docs = json.loads((path or config.ROOT / "data" / "techniques.json").read_text())
        self.tok = [Counter(self._t(d["title"] + " " + d["text"])) for d in self.docs]
        df = Counter(w for t in self.tok for w in t)
        self.idf = {w: math.log((1 + len(self.docs)) / (1 + c)) + 1 for w, c in df.items()}
    @staticmethod
    def _t(s): return re.findall(r"[a-z]+", s.lower())
    def run(self, query="", k=2, **kw):
        q = self._t(query)
        scored = sorted(((sum(t[w] * self.idf.get(w, 0) for w in q), d) for t, d in zip(self.tok, self.docs)),
                        key=lambda x: -x[0])
        return [{"id": d["id"], "title": d["title"], "text": d["text"], "score": round(s, 2)} for s, d in scored[:k] if s > 0]

class ToolFactory(ABC):
    @abstractmethod
    def create_tool(self, name: str) -> BaseTool: ...
    @abstractmethod
    def available(self) -> list: ...
    def create_all(self) -> dict:
        return {n: self.create_tool(n) for n in self.available()}

class SystemToolFactory(ToolFactory):
    def __init__(self, pantry, plan_model):
        self._makers = {"get_pantry_items": lambda: PantryLookupTool(pantry),
                        "search_recipes": lambda: RecipeSearchTool(plan_model.recipes),
                        "calculate_macros": lambda: MacroCalcTool(plan_model),
                        "search_techniques": lambda: RAGSearchTool()}
    def available(self): return list(self._makers)
    def create_tool(self, name):
        if name not in self._makers: raise KeyError(f"Unknown tool {name!r}")
        return self._makers[name]()
