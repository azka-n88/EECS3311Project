"""F09: deterministic exporters (JSON, Markdown, CSV, .ics)."""
import csv, json
from datetime import date, timedelta
from pathlib import Path

def export_plan_json(plan, recipes, path):
    Path(path).write_text(json.dumps([{**s, "recipe": recipes[s["recipe_id"]]["title"]} for s in plan], indent=2))

def export_plan_markdown(plan, recipes, path):
    lines = ["# Meal Plan", ""]; day = None
    for s in plan:
        if s["day"] != day: day = s["day"]; lines += [f"## Day {day}"]
        lines.append(f"- **{s['meal'].title()}**: {recipes[s['recipe_id']]['title']}")
    Path(path).write_text("\n".join(lines) + "\n")

def export_grocery_csv(grocery, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["aisle", "item", "qty", "unit", "est_cost"])
        for aisle, items in grocery["by_aisle"].items():
            for i in items: w.writerow([aisle, i["name"], i["qty"], i["unit"], i["est_cost"]])

def export_plan_ics(plan, recipes, path, start=None):
    start = start or date.today(); hours = {"breakfast": 8, "lunch": 12, "dinner": 18, "snack": 15}
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CulinaryMind AI//EN"]
    for n, s in enumerate(plan):
        d = start + timedelta(days=s["day"] - 1); r = recipes[s["recipe_id"]]
        L += ["BEGIN:VEVENT", f"UID:cm-{n}-{s['day']}-{s['meal']}@culinarymind",
              f"DTSTAMP:{date.today():%Y%m%d}T000000Z",
              f"DTSTART:{d:%Y%m%d}T{hours[s['meal']]:02d}0000", f"SUMMARY:{s['meal'].title()}: {r['title']}",
              f"DESCRIPTION:Prep {r.get('prep_min', '?')} min", "END:VEVENT"]
    L.append("END:VCALENDAR"); Path(path).write_text("\r\n".join(L) + "\r\n")

def safe_export(fn, *args):
    """Catch OS errors (permission denied) so the UI can ask for another folder."""
    try: fn(*args); return True, None
    except OSError as e: return False, str(e)
