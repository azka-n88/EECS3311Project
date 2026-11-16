"""CONTROLLER of MVC. Shared by GUI and CLI so neither contains business logic."""
from . import db, grocery, export
from .agent import AgentExecutionEngine
from .llm import get_adapter
from .tools import SystemToolFactory
from . import receipt, feedback, adapt, nutrition
from .cooking import CookingSession
from .models import PantryModel, MealPlanModel, ValidationError

class ServiceController:
    def __init__(self, con=None, llm=None):
        self.con = con or db.connect()
        self.pantry = PantryModel(self.con)
        self.plan = MealPlanModel(self.con)
        self.tools = SystemToolFactory(self.pantry, self.plan).create_all()
        self._llm = llm; self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = AgentExecutionEngine(self._llm or get_adapter(), self.tools, self.pantry, self.plan, self.con)
        return self._engine

    def _get_llm(self):
        if self._llm is None:
            try: self._llm = get_adapter()
            except Exception: return None
        return self._llm

    # F08
    def parse_receipt(self, text, use_llm=True): return receipt.parse_receipt(text, self._get_llm() if use_llm else None, use_llm)
    def confirm_import(self, items):
        added, skipped = 0, []
        for i in items:
            if i.get("review"): skipped.append(i["raw"]); continue
            try: self.pantry.add_item(name=i["name"], qty=i["qty"], unit=i["unit"], expiry_date=i.get("expiry_date"), category=i["category"]); added += 1
            except ValidationError as e: skipped.append(f"{i['raw']} ({e})")
        return {"added": added, "skipped": skipped}
    # F10
    def submit_feedback(self, recipe_id, rating, effort="", notes="", use_llm=True, confirm=False):
        return feedback.submit_feedback(self.con, self.plan.recipes, recipe_id, rating, effort, notes, self._get_llm() if use_llm else None, use_llm, confirm)
    def preferences(self): return feedback.list_preferences(self.con)
    # F06
    def adapt_recipe(self, recipe_id=None, text=None, restrictions=(), use_llm=True):
        llm = self._get_llm() if use_llm else None
        if text:
            base = adapt.parse_recipe_text(text, llm)
        else:
            if recipe_id not in self.plan.recipes: raise ValidationError(f"Unknown recipe {recipe_id!r}")
            base = self.plan.recipes[recipe_id]
        return adapt.adapt_recipe(base, list(restrictions), llm, use_llm)
    def save_recipe(self, recipe): self.plan.add_recipe(recipe)
    # F07
    def nutrition(self, profile, use_llm=True): return nutrition.analyze(self.plan, profile, self._get_llm() if use_llm else None, use_llm)
    # F05
    def start_cooking(self, recipe_id, seconds_per_min=60, use_llm=True):
        if recipe_id not in self.plan.recipes: raise ValidationError(f"Unknown recipe {recipe_id!r}")
        return CookingSession(self.plan.recipes[recipe_id], self.tools, self.pantry, self._get_llm() if use_llm else None, seconds_per_min)

    # F02 / F03 (AI agent)
    def generate_plan(self, **kw): return self.engine.generate_plan(**kw)
    def swap_meal(self, day, meal, **kw):
        res = self.engine.swap_meal(day, meal, **kw)
        if res["ok"]: res["grocery"] = self.grocery_list()      # dependent grocery list refreshes
        return res
    def macros(self): return self.tools["calculate_macros"].run()

    # F01
    def add_pantry_item(self, **kw): return self.pantry.add_item(**kw)
    def list_pantry(self): return self.pantry.list_items()
    def expiring(self): return self.pantry.expiring_soon()
    def update_pantry_qty(self, item_id, qty): self.pantry.update_quantity(item_id, qty)
    def delete_pantry_item(self, item_id): self.pantry.delete_item(item_id)
    # plan (manual slot assignment; agent generation added in batch 2)
    def set_meal(self, day, meal, recipe_id): self.plan.set_slot(day, meal, recipe_id)
    def get_plan(self): return self.plan.get_plan()
    # F04
    def grocery_list(self):
        return grocery.consolidate(self.plan.get_plan(), self.plan.recipes, self.pantry.list_items())
    # F09
    def export(self, fmt, path):
        p, r = self.plan.get_plan(), self.plan.recipes
        fn = {"json": lambda: export.export_plan_json(p, r, path), "md": lambda: export.export_plan_markdown(p, r, path),
              "ics": lambda: export.export_plan_ics(p, r, path), "csv": lambda: export.export_grocery_csv(self.grocery_list(), path)}
        if fmt not in fn: raise ValidationError(f"Unknown format {fmt!r}; use {list(fn)}")
        ok, err = export.safe_export(fn[fmt]); return ok, err
