"""CONTROLLER of MVC. Shared by GUI and CLI so neither contains business logic."""
from . import db, grocery, export
from .models import PantryModel, MealPlanModel, ValidationError

class ServiceController:
    def __init__(self, con=None):
        self.con = con or db.connect()
        self.pantry = PantryModel(self.con)
        self.plan = MealPlanModel(self.con)

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
