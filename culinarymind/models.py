"""MODEL layer of MVC. PantryModel and MealPlanModel are Observer Subjects."""
import json
from datetime import date, datetime
from .observer import Subject
from .units import to_base, UnitError
from . import config

class ValidationError(ValueError): pass

def _parse_date(s):
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError): raise ValidationError(f"Invalid date {s!r}, use YYYY-MM-DD")

class PantryModel(Subject):
    def __init__(self, con):
        super().__init__(); self.con = con

    def add_item(self, name, qty, unit, expiry_date=None, category="Other",
                 purchase_date=None, merge=True):
        name = (name or "").strip().lower()
        if not name: raise ValidationError("Name is required")
        try: qty = float(qty)
        except (TypeError, ValueError): raise ValidationError("Quantity must be a number")
        if qty <= 0: raise ValidationError("Quantity must be positive")
        try: to_base(1, unit)
        except UnitError as e: raise ValidationError(str(e))
        if expiry_date: _parse_date(expiry_date)
        purchase_date = purchase_date or date.today().isoformat()
        dup = self.con.execute("SELECT * FROM pantry WHERE name=? AND unit=?", (name, unit)).fetchone()
        if dup and merge:
            self.con.execute("UPDATE pantry SET qty=qty+?, expiry_date=COALESCE(?,expiry_date) WHERE id=?",
                             (qty, expiry_date, dup["id"]))
            item_id = dup["id"]
        else:
            cur = self.con.execute(
                "INSERT INTO pantry(name,qty,unit,category,purchase_date,expiry_date) VALUES(?,?,?,?,?,?)",
                (name, qty, unit, category, purchase_date, expiry_date))
            item_id = cur.lastrowid
        self.con.commit()
        self.notify_observers("pantry_changed", {"id": item_id})
        return item_id

    def update_quantity(self, item_id, qty):
        if float(qty) < 0: raise ValidationError("Quantity cannot be negative")
        self.con.execute("UPDATE pantry SET qty=? WHERE id=?", (float(qty), item_id))
        self.con.commit(); self.notify_observers("pantry_changed", {"id": item_id})

    def delete_item(self, item_id):
        self.con.execute("DELETE FROM pantry WHERE id=?", (item_id,))
        self.con.commit(); self.notify_observers("pantry_changed", {"id": item_id})

    def deduct(self, name, qty, unit):
        """Decrement stock (used after cooking). Works across compatible units."""
        need, dim = to_base(qty, unit)
        for row in self.con.execute("SELECT * FROM pantry WHERE name=? ORDER BY expiry_date", (name.lower(),)).fetchall():
            have, d = to_base(row["qty"], row["unit"])
            if d != dim or need <= 0: continue
            take = min(have, need); need -= take
            factor = to_base(1, row["unit"])[0]
            self.con.execute("UPDATE pantry SET qty=? WHERE id=?", ((have - take) / factor, row["id"]))
        self.con.commit(); self.notify_observers("pantry_changed", {"name": name})

    @staticmethod
    def status(row, today=None):
        """red <=2 days, yellow <=5 days, ok otherwise, none if no expiry."""
        if not row["expiry_date"]: return "none"
        days = (_parse_date(row["expiry_date"]) - (today or date.today())).days
        return "expired" if days < 0 else "red" if days <= 2 else "yellow" if days <= 5 else "ok"

    def list_items(self):
        return [dict(r, status=self.status(r)) for r in
                self.con.execute("SELECT * FROM pantry ORDER BY expiry_date IS NULL, expiry_date")]

    def expiring_soon(self, days=5):
        return [i for i in self.list_items() if i["status"] in ("expired", "red", "yellow")]

class MealPlanModel(Subject):
    MEALS = ("breakfast", "lunch", "dinner", "snack")
    def __init__(self, con):
        super().__init__(); self.con = con
        self.recipes = {r["id"]: r for r in json.loads(config.RECIPES_PATH.read_text())}

    def set_slot(self, day, meal, recipe_id):
        if meal not in self.MEALS: raise ValidationError(f"meal must be one of {self.MEALS}")
        if recipe_id not in self.recipes: raise ValidationError(f"Unknown recipe {recipe_id!r}")
        self.con.execute("INSERT OR REPLACE INTO plan VALUES(?,?,?)", (day, meal, recipe_id))
        self.con.commit(); self.notify_observers("plan_changed", {"day": day, "meal": meal})

    def clear(self):
        self.con.execute("DELETE FROM plan"); self.con.commit(); self.notify_observers("plan_changed")

    def get_plan(self):
        return [dict(r) for r in self.con.execute("SELECT * FROM plan ORDER BY day, meal")]

    def total_cost(self):
        return round(sum(i.get("cost", 0) for s in self.get_plan() for i in self.recipes[s["recipe_id"]]["ingredients"]), 2)
