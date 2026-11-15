"""CLI view: python -m culinarymind.cli <command>"""
import argparse, sys
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
    sub.add_parser("plan-show"); sub.add_parser("grocery")
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
        elif args.cmd == "export":
            ok, err = c.export(args.fmt, args.path); print("saved" if ok else f"failed: {err}")
    except ValidationError as ex:
        print("Error:", ex); return 1
if __name__ == "__main__": sys.exit(main())
