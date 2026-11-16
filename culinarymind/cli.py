"""CLI view: python -m culinarymind.cli <command>"""
import argparse, sys
from .llm import LLMError
from .controller import ServiceController
from .models import ValidationError
from .observer import Observer

class CLIView(Observer):
    def update(self, subject, event, payload=None):
        if event == "timer_done": print(f"\a\n*** TIMER DONE: {payload['label']} -- type 'ack' ***")
        elif event not in ("step_changed", "timer_ack"): print(f"[event] {event}")

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
    sub.add_parser("recipes"); sub.add_parser("preferences")
    ir = sub.add_parser("import-receipt"); ir.add_argument("--text"); ir.add_argument("--file"); ir.add_argument("--confirm", action="store_true"); ir.add_argument("--no-llm", action="store_true")
    fb = sub.add_parser("feedback"); fb.add_argument("recipe_id"); fb.add_argument("rating", type=int); fb.add_argument("--effort", default="")
    fb.add_argument("--notes", default=""); fb.add_argument("--confirm", action="store_true"); fb.add_argument("--no-llm", action="store_true")
    ad = sub.add_parser("adapt"); ad.add_argument("recipe_id"); ad.add_argument("--restrict", action="append", required=True)
    ad.add_argument("--save", action="store_true"); ad.add_argument("--no-llm", action="store_true")
    nu = sub.add_parser("nutrition"); nu.add_argument("--age", type=int, default=25); nu.add_argument("--weight", type=float, default=70)
    nu.add_argument("--activity", default="moderate", choices=["sedentary", "light", "moderate", "active"])
    nu.add_argument("--goal", default="maintain", choices=["lose", "maintain", "gain"]); nu.add_argument("--no-llm", action="store_true")
    ck = sub.add_parser("cook"); ck.add_argument("recipe_id"); ck.add_argument("--seconds-per-min", type=float, default=60); ck.add_argument("--no-llm", action="store_true")
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
        elif args.cmd == "recipes":
            for r in c.plan.recipes.values(): print(f"{r['id']:<20}{r['title']:<32}{r['prep_min']:>3} min  {','.join(r['meals'])}")
        elif args.cmd == "preferences":
            for p in c.preferences() or ["(none yet)"]: print("-", p)
        elif args.cmd == "import-receipt":
            text = open(args.file).read() if args.file else (args.text or "").replace("\\n", "\n")
            items, mode = c.parse_receipt(text, use_llm=not args.no_llm); print(f"Parsed with mode={mode}")
            for i in items:
                flag = "  <-- REVIEW REQUIRED (Uncategorized)" if i["review"] else ""
                print(f"  {i['name']:<20}{i['qty']:>7g} {i['unit']:<5}{i['category']:<10} exp={i['expiry_date']}{flag}")
            if args.confirm: print(c.confirm_import(items))
            else: print("(preview only; add --confirm to import)")
        elif args.cmd == "feedback":
            r = c.submit_feedback(args.recipe_id, args.rating, args.effort, args.notes, use_llm=not args.no_llm, confirm=args.confirm)
            print(r.get("message") if r.get("conflict") else f"Saved. Preference rule ({r['mode']}): {r['rule']}")
        elif args.cmd == "adapt":
            r = c.adapt_recipe(args.recipe_id, restrictions=args.restrict, use_llm=not args.no_llm); rec = r["recipe"]
            print(f"{rec['title']}  [mode={r['mode']}]  safety: {'VERIFIED' if r['verified'] else 'NOT VERIFIED ' + str(r['remaining_flags'])}")
            for ch in r["changes"]: print("  swap:", ch)
            for i in rec["ingredients"]: print(f"  - {i['qty']:g} {i['unit']} {i['name']}")
            for n, st in enumerate(rec["steps"], 1): print(f"  {n}. {st}")
            for w_ in r["warnings"]: print("  WARNING:", w_)
            if args.save: c.save_recipe(rec); print("Saved to library as", rec["id"])
        elif args.cmd == "nutrition":
            r = c.nutrition({"age": args.age, "weight_kg": args.weight, "activity": args.activity, "goal": args.goal}, use_llm=not args.no_llm)
            if not r["ok"]: print(r["error"]); return 1
            print("Targets:", r["targets"]); print("Avg/day:", r["average_daily"])
            for k, v in r["compliance_pct"].items(): print(f"  {k:<11}{v:>4}%  " + "#" * min(v // 5, 30))
            for w_ in r["warnings"]: print("  !", w_)
            print(f"Summary ({r['narrative_mode']}):", r["narrative"])
            if r["missing_data"]: print("Missing micronutrient data for:", r["missing_data"])
        elif args.cmd == "cook":
            sess = c.start_cooking(args.recipe_id, args.seconds_per_min, use_llm=not args.no_llm); sess.attach(CLIView())
            def show(): d = sess.current(); print(f"\n== Step {d['index']}/{d['total']}: {d['text']}" + (f"   [t = start {d['suggested_minutes']} min timer]" if d["suggested_minutes"] else ""))
            print(f"Cooking {sess.recipe['title']}. Commands: n(ext) p(rev) t [min] timers ack ask <question> done quit"); show()
            while True:
                try: cmd = input("cook> ").strip()
                except EOFError: break
                if cmd in ("q", "quit"): break
                try:
                    if cmd in ("n", "next"): sess.next(); show()
                    elif cmd in ("p", "prev"): sess.prev(); show()
                    elif cmd.startswith("t"): sess.start_timer(float(cmd.split()[1]) if len(cmd.split()) > 1 else None)
                    elif cmd == "timers": print(sess.remaining() or "no active timers")
                    elif cmd == "ack": sess.acknowledge()
                    elif cmd.startswith("ask "): a = sess.ask(cmd[4:], use_llm=not args.no_llm); print(f"[{a['mode']}] {a['answer']}")
                    elif cmd == "done": print(sess.finish(), "\nLog feedback with: feedback", sess.recipe["id"], "<1-5>"); break
                except ValidationError as ex: print("Error:", ex)
        elif args.cmd == "export":
            ok, err = c.export(args.fmt, args.path); print("saved" if ok else f"failed: {err}")
    except (ValidationError, ValueError) as ex:
        print("Error:", ex); return 1
    except LLMError as ex:
        print("LLM error:", ex, "(try --no-llm)"); return 1
if __name__ == "__main__": sys.exit(main())
