"""CLI view: python -m culinarymind.cli <command>"""
import argparse, sys
from .llm import LLMError
from .controller import ServiceController
from .models import ValidationError
from .observer import Observer

class CLIView(Observer):
    def update(self, subject, event, payload=None): print(f"[event] {event}")

def main(argv=None):
    ap = argparse.ArgumentParser(prog="culinarymind")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("pantry-add"); a.add_argument("name"); a.add_argument("qty"); a.add_argument("unit")
    a.add_argument("--expiry"); a.add_argument("--category", default="Other")
    sub.add_parser("pantry-list"); sub.add_parser("pantry-expiring")
    d = sub.add_parser("pantry-delete"); d.add_argument("id", type=int)
    s = sub.add_parser("plan-set"); s.add_argument("day", type=int); s.add_argument("meal"); s.add_argument("recipe_id")
    sub.add_parser("plan-show"); sub.add_parser("grocery"); sub.add_parser("macros")
    g = sub.add_parser("plan-generate"); g.add_argument("--days", type=int, default=3); g.add_argument("--budget", type=float)
    g.add_argument("--kcal", type=float); g.add_argument("--diet"); g.add_argument("--allergen", action="append", default=[])
    g.add_argument("--strategy", default="budget", choices=["budget", "zero_waste", "protein"]); g.add_argument("--max-prep", type=int)
    g.add_argument("--no-llm", action="store_true", help="use deterministic planner only")
    w = sub.add_parser("plan-swap"); w.add_argument("day", type=int); w.add_argument("meal"); w.add_argument("--reason", default="")
    w.add_argument("--max-prep", type=int); w.add_argument("--no-llm", action="store_true")
    e = sub.add_parser("export"); e.add_argument("fmt"); e.add_argument("path")
    args = ap.parse_args(argv)
    c = ServiceController(); c.pantry.attach(CLIView()); c.plan.attach(CLIView())
    try:
        if args.cmd == "pantry-add":
            print("added id", c.add_pantry_item(name=args.name, qty=args.qty, unit=args.unit, expiry_date=args.expiry, category=args.category))
        elif args.cmd in ("pantry-list", "pantry-expiring"):
            for i in (c.list_pantry() if args.cmd == "pantry-list" else c.expiring()):
                print(f"{i['id']:>3} {i['name']:<18}{i['qty']:>8g} {i['unit']:<5} exp={i['expiry_date']} [{i['status']}]")
        elif args.cmd == "pantry-delete": c.delete_pantry_item(args.id)
        elif args.cmd == "plan-set": c.set_meal(args.day, args.meal, args.recipe_id)
        elif args.cmd == "plan-show":
            for p in c.get_plan(): print(f"Day {p['day']} {p['meal']:<9} {c.plan.recipes[p['recipe_id']]['title']}")
        elif args.cmd == "grocery":
            g = c.grocery_list()
            for aisle, items in g["by_aisle"].items():
                print(f"== {aisle}")
                for i in items: print(f"  [ ] {i['name']}: {i['qty']} {i['unit']}  (${i['est_cost']})")
            for r in g["needs_review"]: print(f"  [?] {r['name']} {r['qty']} {r['unit']} - {r['reason']}")
            print(f"Estimated total: ${g['total_cost']}")
        elif args.cmd == "plan-generate":
            r = c.generate_plan(days=args.days, budget=args.budget, kcal=args.kcal, diet=args.diet, allergens=args.allergen,
                                strategy=args.strategy, max_prep=args.max_prep, use_llm=not args.no_llm)
            if r["ok"]:
                for p in r["plan"]: print(f"Day {p['day']} {p['meal']:<9} {c.plan.recipes[p['recipe_id']]['title']}")
                print(f"mode={r['mode']} attempts={r['attempts']} cost=${r['total_cost']} pantry_use={r['pantry_utilization_pct']}%")
                for n in r["notes"]: print("  note:", n)
            else:
                print("Could not build a plan:"); [print(" -", i) for i in r["issues"]]
                print("Suggestions:"); [print(" *", x) for x in r["suggestions"]]
        elif args.cmd == "plan-swap":
            r = c.swap_meal(args.day, args.meal, reason=args.reason, max_prep=args.max_prep, use_llm=not args.no_llm)
            if r["ok"]: print(f"Swapped -> {r['title']} (mode={r['mode']}); grocery total now ${r['grocery']['total_cost']}")
            else: print("No swap:", "; ".join(r["issues"]), "| try:", "; ".join(r["suggestions"]))
        elif args.cmd == "macros":
            m = c.macros(); print("Average per day:", m["average_daily"])
            for d, v in m["daily"].items(): print(f"  Day {d}: {v}")
        elif args.cmd == "export":
            ok, err = c.export(args.fmt, args.path); print("saved" if ok else f"failed: {err}")
    except (ValidationError, ValueError) as ex:
        print("Error:", ex); return 1
    except LLMError as ex:
        print("LLM error:", ex, "(try --no-llm)"); return 1
if __name__ == "__main__": sys.exit(main())
