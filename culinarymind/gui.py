"""GUI view (Tkinter): thin presentation layer over ServiceController. Refreshes via Observer events.
Long-running (LLM) work runs in a background thread; results return to the UI thread through a queue."""
import queue, threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from . import receipt
from .controller import ServiceController
from .models import ValidationError
from .observer import Observer

MEALS = ("breakfast", "lunch", "dinner", "snack")
RESTRICTIONS = [("Gluten-Free", "gluten"), ("Dairy-Free", "dairy"), ("Vegan", "vegan"), ("Egg-Free", "egg"),
                ("Soy-Free", "soy"), ("Peanut-Free", "peanut")]

class _Listener(Observer):
    """Observer adapter: marshals model/session events onto the Tk thread."""
    def __init__(self, post, fn): self.post, self.fn = post, fn
    def update(self, subject, event, payload=None): self.post(lambda: self.fn(event, payload))

class MainGUIView(tk.Tk):
    def __init__(self, controller=None):
        super().__init__()
        self.title("CulinaryMind AI"); self.geometry("1150x720")
        self.c = controller or ServiceController()
        self.q = queue.Queue(); self.busy = 0; self.dirty = False
        self.session = None; self.adapted = None; self.stock_state = {}
        self.use_llm = tk.BooleanVar(value=True); self.status = tk.StringVar(value="Ready")
        top = ttk.Frame(self); top.pack(fill="x", padx=6, pady=4)
        ttk.Checkbutton(top, text="Use LLM (uncheck for deterministic mode)", variable=self.use_llm).pack(side="left")
        ttk.Label(top, textvariable=self.status).pack(side="right")
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        for name, build in (("Pantry", self._pantry_tab), ("Meal Plan", self._plan_tab), ("Grocery List", self._grocery_tab),
                            ("Nutrition", self._nutrition_tab), ("Adapt Recipe", self._adapt_tab), ("Cooking", self._cook_tab),
                            ("Export", self._export_tab)):
            f = ttk.Frame(nb); nb.add(f, text=name); build(f)
        listener = _Listener(self.post, self._on_event)
        self.c.pantry.attach(listener); self.c.plan.attach(listener)
        self.after(100, self._poll); self.after(1000, self._tick); self.refresh_all()

    # ---------- infrastructure ----------
    def post(self, fn): self.q.put(fn)
    def _poll(self):
        self.after(100, self._poll)
        try:
            while True: self.q.get_nowait()()
        except queue.Empty: pass
        if self.dirty and self.busy == 0: self.dirty = False; self.refresh_all()
    def _on_event(self, event, payload): self.dirty = True
    def bg(self, fn, done):
        self.busy += 1; self.status.set("Working...")
        def work():
            try: res = (fn(), None)
            except Exception as e: res = (None, e)
            def finish():
                self.busy -= 1; self.status.set("Ready"); self.dirty = True
                done(*res)
            self.post(finish)
        threading.Thread(target=work, daemon=True).start()
    def err(self, e): messagebox.showerror("Error", str(e))
    def form(self, title, fields, initial=None):
        win = tk.Toplevel(self); win.title(title); win.transient(self); win.grab_set()
        vs = {}
        for r, (key, label) in enumerate(fields):
            ttk.Label(win, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=3)
            v = tk.StringVar(value=str((initial or {}).get(key, ""))); vs[key] = v
            ttk.Entry(win, textvariable=v, width=34).grid(row=r, column=1, padx=6, pady=3)
        out = {}
        def ok(): out.update({k: v.get().strip() for k, v in vs.items()}); win.destroy()
        ttk.Button(win, text="OK", command=ok).grid(row=len(fields), column=0, columnspan=2, pady=6)
        self.wait_window(win); return out or None
    @staticmethod
    def _f(var): s = var.get().strip(); return float(s) if s else None
    def refresh_all(self):
        self.refresh_pantry(); self.refresh_plan(); self.refresh_grocery()
        self.adapt_combo["values"] = sorted(self.c.plan.recipes); self.cook_combo["values"] = sorted(self.c.plan.recipes)

    # ---------- Pantry (F01, F08) ----------
    def _pantry_tab(self, f):
        bar = ttk.Frame(f); bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in (("Add Item", self.add_item), ("Edit Quantity", self.edit_qty), ("Delete", self.del_item), ("Import Receipt", self.import_receipt)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3)
        cols = ("id", "name", "qty", "unit", "category", "expiry", "status")
        self.pt = ttk.Treeview(f, columns=cols, show="headings")
        for col in cols: self.pt.heading(col, text=col.title()); self.pt.column(col, width=180 if col == "name" else 95)
        for tag, color in (("red", "#ffb3b3"), ("yellow", "#fff2b3"), ("expired", "#ff8080")): self.pt.tag_configure(tag, background=color)
        self.pt.pack(fill="both", expand=True, padx=6)
        self.exp_label = ttk.Label(f, text=""); self.exp_label.pack(anchor="w", padx=6, pady=4)
    def refresh_pantry(self):
        self.pt.delete(*self.pt.get_children())
        for i in self.c.list_pantry():
            self.pt.insert("", "end", values=(i["id"], i["name"], f"{i['qty']:g}", i["unit"], i["category"], i["expiry_date"] or "", i["status"]), tags=(i["status"],))
        self.exp_label.config(text="Expiring soon (priority for planning): " + (", ".join(i["name"] for i in self.c.expiring()) or "none"))
    def _sel_pantry(self):
        sel = self.pt.selection()
        if not sel: messagebox.showinfo("Select an item", "Select a pantry row first."); return None
        return int(self.pt.item(sel[0])["values"][0])
    def add_item(self):
        d = self.form("Add pantry item", [("name", "Name"), ("qty", "Quantity"), ("unit", "Unit (g kg ml l cup tbsp tsp pc oz lb)"), ("category", "Category"), ("expiry_date", "Expiry (YYYY-MM-DD)")])
        if not d: return
        try:
            dup = any(i["name"] == d["name"].lower() and i["unit"] == d["unit"] for i in self.c.list_pantry())
            merge = messagebox.askyesno("Duplicate item", "Merge quantities? (No = keep as a separate batch)") if dup else True
            self.c.add_pantry_item(name=d["name"], qty=d["qty"], unit=d["unit"], expiry_date=d["expiry_date"] or None, category=d["category"] or "Other", merge=merge)
        except ValidationError as e: messagebox.showerror("Invalid input", str(e))
    def edit_qty(self):
        i = self._sel_pantry()
        if i is None: return
        q = simpledialog.askfloat("Edit quantity", "New quantity:", parent=self)
        if q is None: return
        try: self.c.update_pantry_qty(i, q)
        except ValidationError as e: messagebox.showerror("Invalid input", str(e))
    def del_item(self):
        i = self._sel_pantry()
        if i is not None and messagebox.askyesno("Delete", "Delete this item?"): self.c.delete_pantry_item(i)
    def import_receipt(self):
        win = tk.Toplevel(self); win.title("Import Pantry (receipt / notes)"); win.geometry("720x520")
        txt = tk.Text(win, height=9); txt.pack(fill="x", padx=6, pady=6)
        txt.insert("1.0", "2 kg chicken breast\nmilk 1 l\nspinach 200 g\n#@!$ ??")
        cols = ("name", "qty", "unit", "category", "expiry", "flag")
        tv = ttk.Treeview(win, columns=cols, show="headings", height=9)
        for col in cols: tv.heading(col, text=col.title()); tv.column(col, width=100)
        tv.tag_configure("review", background="#ffb3b3"); tv.pack(fill="both", expand=True, padx=6)
        items = []
        def show():
            tv.delete(*tv.get_children())
            for n, it in enumerate(items):
                tv.insert("", "end", iid=str(n), tags=("review",) if it["review"] else (),
                          values=(it["name"], it["qty"], it["unit"], it["category"], it["expiry_date"] or "", "REVIEW REQUIRED" if it["review"] else ""))
        def extract():
            raw = txt.get("1.0", "end").strip()
            def done(res, e):
                if e: return self.err(e)
                items[:] = res[0]; show(); self.status.set(f"Parsed ({res[1]})")
            self.bg(lambda: self.c.parse_receipt(raw, use_llm=self.use_llm.get()), done)
        def edit(_ev):
            sel = tv.selection()
            if not sel: return
            it = items[int(sel[0])]
            d = self.form("Edit parsed item", [("name", "Name"), ("qty", "Quantity"), ("unit", "Unit"), ("category", "Category"), ("expiry_date", "Expiry")],
                          {"name": it["name"], "qty": it["qty"], "unit": it["unit"], "category": it["category"], "expiry_date": it["expiry_date"] or ""})
            if d:
                new = receipt._item(d["name"], d["qty"], d["unit"], d["category"], raw=it["raw"])
                if d["expiry_date"] and not new["review"]: new["expiry_date"] = d["expiry_date"]
                items[int(sel[0])] = new; show()
        def confirm():
            r = self.c.confirm_import(items); win.destroy()
            messagebox.showinfo("Import complete", f"Added {r['added']} item(s).\nSkipped: {r['skipped'] or 'none'}")
        tv.bind("<Double-1>", edit)
        bar = ttk.Frame(win); bar.pack(pady=6)
        ttk.Button(bar, text="Extract & Add", command=extract).pack(side="left", padx=4)
        ttk.Button(bar, text="Confirm Import", command=confirm).pack(side="left", padx=4)
        ttk.Label(bar, text="(double-click a row to edit)").pack(side="left")

    # ---------- Meal plan (F02, F03, F10) ----------
    def _plan_tab(self, f):
        left = ttk.LabelFrame(f, text="Generate Meal Plan"); left.pack(side="left", fill="y", padx=6, pady=6)
        self.p_days = tk.StringVar(value="3"); self.p_budget = tk.StringVar(); self.p_kcal = tk.StringVar(); self.p_diet = tk.StringVar()
        self.p_allerg = tk.StringVar(); self.p_strat = tk.StringVar(value="budget"); self.p_prep = tk.StringVar()
        rows = (("Days (1-7)", ttk.Spinbox(left, from_=1, to=7, textvariable=self.p_days, width=8)), ("Budget cap ($)", ttk.Entry(left, textvariable=self.p_budget, width=10)),
                ("Calories/day", ttk.Entry(left, textvariable=self.p_kcal, width=10)),
                ("Diet", ttk.Combobox(left, textvariable=self.p_diet, values=["", "vegetarian", "vegan", "keto", "high-protein"], width=12, state="readonly")),
                ("Allergens (comma)", ttk.Entry(left, textvariable=self.p_allerg, width=14)),
                ("Strategy", ttk.Combobox(left, textvariable=self.p_strat, values=["budget", "zero_waste", "protein"], width=12, state="readonly")),
                ("Max prep (min)", ttk.Entry(left, textvariable=self.p_prep, width=10)))
        for r, (label, w) in enumerate(rows): ttk.Label(left, text=label).grid(row=r, column=0, sticky="w", padx=4, pady=3); w.grid(row=r, column=1, padx=4)
        ttk.Button(left, text="Generate Plan", command=self.generate).grid(row=8, column=0, columnspan=2, pady=8, sticky="ew")
        ttk.Button(left, text="Swap Meal...", command=self.swap).grid(row=9, column=0, columnspan=2, pady=2, sticky="ew")
        ttk.Button(left, text="Rate Meal...", command=self.rate_meal).grid(row=10, column=0, columnspan=2, pady=2, sticky="ew")
        ttk.Button(left, text="Clear Plan", command=self.c.plan.clear).grid(row=11, column=0, columnspan=2, pady=2, sticky="ew")
        right = ttk.Frame(f); right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        cols = ("day",) + MEALS
        self.cal = ttk.Treeview(right, columns=cols, show="headings", height=10)
        for col in cols: self.cal.heading(col, text=col.title()); self.cal.column(col, width=60 if col == "day" else 200)
        self.cal.pack(fill="both", expand=True)
        self.plan_summary = tk.StringVar(value="No plan yet."); ttk.Label(right, textvariable=self.plan_summary, wraplength=800).pack(anchor="w", pady=6)
    def refresh_plan(self):
        self.cal.delete(*self.cal.get_children()); grid = {}
        for s in self.c.get_plan(): grid.setdefault(s["day"], {})[s["meal"]] = self.c.plan.recipes[s["recipe_id"]]["title"]
        for d in sorted(grid): self.cal.insert("", "end", values=(d,) + tuple(grid[d].get(m, "") for m in MEALS))
        if grid: self.plan_summary.set(self.plan_summary.get().split(" | Cost")[0] + f" | Cost ${self.c.plan.total_cost()}")
    def generate(self):
        try:
            kw = dict(days=int(self.p_days.get()), budget=self._f(self.p_budget), kcal=self._f(self.p_kcal), diet=self.p_diet.get() or None,
                      allergens=[a.strip().lower() for a in self.p_allerg.get().split(",") if a.strip()], strategy=self.p_strat.get(),
                      max_prep=int(self.p_prep.get()) if self.p_prep.get().strip() else None, use_llm=self.use_llm.get())
        except ValueError: return messagebox.showerror("Invalid input", "Days, budget, calories and prep time must be numbers.")
        def done(r, e):
            if e: return self.err(e)
            if not r["ok"]:
                return messagebox.showwarning("Cannot build this plan", "\n".join(r["issues"]) + "\n\nSuggestions:\n- " + "\n- ".join(r["suggestions"]))
            self.plan_summary.set(f"mode={r['mode']} | attempts={r['attempts']} | pantry use={r['pantry_utilization_pct']}%")
        self.bg(lambda: self.c.generate_plan(**kw), done)
    def _pick_slot(self, title, extra):
        sel = self.cal.selection(); day = self.cal.item(sel[0])["values"][0] if sel else 1
        d = self.form(title, [("day", "Day"), ("meal", "Meal (breakfast/lunch/dinner/snack)")] + extra, {"day": day, "meal": "dinner"})
        return d
    def swap(self):
        d = self._pick_slot("Swap meal", [("reason", "Reason / new constraint"), ("max_prep", "Max prep minutes (optional)")])
        if not d: return
        try: day, mp = int(d["day"]), (int(d["max_prep"]) if d["max_prep"] else None)
        except ValueError: return messagebox.showerror("Invalid input", "Day and prep minutes must be numbers.")
        def done(r, e):
            if e: return self.err(e)
            if r["ok"]: messagebox.showinfo("Swapped", f"New meal: {r['title']} ({r['mode']})\nGrocery total now ${r['grocery']['total_cost']}")
            else: messagebox.showwarning("No alternative found", "\n".join(r["issues"]) + "\n\nOptions:\n- " + "\n- ".join(r["suggestions"]))
        self.bg(lambda: self.c.swap_meal(day, d["meal"], reason=d["reason"], max_prep=mp, use_llm=self.use_llm.get()), done)
    def rate_meal(self):
        d = self._pick_slot("Rate which meal?", [])
        if not d: return
        slot = next((s for s in self.c.get_plan() if str(s["day"]) == d["day"] and s["meal"] == d["meal"]), None)
        if not slot: return messagebox.showinfo("Not found", "No meal in that slot.")
        self.feedback_dialog(slot["recipe_id"])
    def feedback_dialog(self, rid):
        d = self.form(f"Rate: {self.c.plan.recipes[rid]['title']}", [("rating", "Rating 1-5"), ("effort", "Effort (easy/medium/hard)"), ("notes", "Notes")])
        if not d: return
        def run(confirm=False):
            def done(r, e):
                if e: return self.err(e)
                if r.get("conflict"):
                    if messagebox.askyesno("Conflicting feedback", r["message"]): run(True)
                else: messagebox.showinfo("Preference learned", f"{r['rule']}\n(mode: {r['mode']})")
            self.bg(lambda: self.c.submit_feedback(rid, d["rating"], d["effort"], d["notes"], use_llm=self.use_llm.get(), confirm=confirm), done)
        run()

    # ---------- Grocery (F04) ----------
    def _grocery_tab(self, f):
        ttk.Label(f, text="Double-click an item to toggle To Buy / In Stock").pack(anchor="w", padx=6, pady=4)
        self.gt = ttk.Treeview(f, columns=("qty", "cost", "state"), show="tree headings")
        for col, w in (("#0", 260), ("qty", 120), ("cost", 90), ("state", 100)): self.gt.column(col, width=w)
        self.gt.heading("#0", text="Item"); self.gt.heading("qty", text="Qty"); self.gt.heading("cost", text="Est. cost"); self.gt.heading("state", text="Status")
        self.gt.pack(fill="both", expand=True, padx=6); self.gt.bind("<Double-1>", self._toggle_stock)
        self.g_total = tk.StringVar(); ttk.Label(f, textvariable=self.g_total).pack(anchor="w", padx=6, pady=4)
    def refresh_grocery(self):
        self.gt.delete(*self.gt.get_children())
        if not self.c.get_plan(): self.g_total.set("Generate a meal plan first."); return
        g = self.c.grocery_list()
        for aisle, items in g["by_aisle"].items():
            p = self.gt.insert("", "end", text=aisle, open=True)
            for i in items: self.gt.insert(p, "end", text=i["name"], values=(f"{i['qty']:g} {i['unit']}", f"${i['est_cost']}", self.stock_state.get(i["name"], "To Buy")))
        if g["needs_review"]:
            p = self.gt.insert("", "end", text="Needs review (ambiguous unit)", open=True)
            for r in g["needs_review"]: self.gt.insert(p, "end", text=r["name"], values=(f"{r['qty']:g} {r['unit']}", "?", "Confirm"))
        self.g_total.set(f"Estimated total to buy: ${g['total_cost']}")
    def _toggle_stock(self, _ev):
        sel = self.gt.selection()
        if not sel or not self.gt.parent(sel[0]): return
        name = self.gt.item(sel[0])["text"]; self.stock_state[name] = "In Stock" if self.stock_state.get(name, "To Buy") == "To Buy" else "To Buy"
        self.refresh_grocery()

    # ---------- Nutrition (F07) ----------
    def _nutrition_tab(self, f):
        bar = ttk.Frame(f); bar.pack(fill="x", padx=6, pady=6)
        self.n_age, self.n_w = tk.StringVar(value="25"), tk.StringVar(value="70")
        self.n_act, self.n_goal = tk.StringVar(value="moderate"), tk.StringVar(value="maintain")
        for label, w in (("Age", ttk.Entry(bar, textvariable=self.n_age, width=5)), ("Weight kg", ttk.Entry(bar, textvariable=self.n_w, width=6)),
                         ("Activity", ttk.Combobox(bar, textvariable=self.n_act, values=["sedentary", "light", "moderate", "active"], width=10, state="readonly")),
                         ("Goal", ttk.Combobox(bar, textvariable=self.n_goal, values=["lose", "maintain", "gain"], width=9, state="readonly"))):
            ttk.Label(bar, text=label).pack(side="left", padx=3); w.pack(side="left")
        ttk.Button(bar, text="Analyze Plan", command=self.analyze).pack(side="left", padx=8)
        self.canvas = tk.Canvas(f, height=260, bg="white"); self.canvas.pack(fill="x", padx=6)
        self.n_text = tk.Text(f, height=8, wrap="word"); self.n_text.pack(fill="both", expand=True, padx=6, pady=6)
    def analyze(self):
        try: prof = {"age": int(self.n_age.get()), "weight_kg": float(self.n_w.get()), "activity": self.n_act.get(), "goal": self.n_goal.get()}
        except ValueError: return messagebox.showerror("Invalid input", "Age and weight must be numbers.")
        def done(r, e):
            if e: return self.err(e)
            if not r["ok"]: return messagebox.showinfo("Nutrition", r["error"])
            cv = self.canvas; cv.delete("all")
            for n, (k, pct) in enumerate(r["compliance_pct"].items()):
                y = 15 + n * 40; ok = (pct <= 100) if k == "sodium_mg" else 70 <= pct <= 130
                cv.create_text(10, y + 10, text=k, anchor="w"); cv.create_rectangle(120, y, 120 + min(pct, 160) * 4, y + 22, fill="#6bbf6b" if ok else "#e8a33d")
                cv.create_text(130 + min(pct, 160) * 4, y + 10, text=f"{pct}%", anchor="w")
            cv.create_line(120 + 100 * 4, 5, 120 + 100 * 4, 250, dash=(3, 3))
            self.n_text.delete("1.0", "end")
            self.n_text.insert("end", "Warnings:\n" + ("\n".join("- " + w for w in r["warnings"]) or "none") + f"\n\nSummary ({r['narrative_mode']}):\n{r['narrative']}")
            if r["missing_data"]: self.n_text.insert("end", f"\n\nMissing micronutrient data for: {r['missing_data']}")
        self.bg(lambda: self.c.nutrition(prof, use_llm=self.use_llm.get()), done)

    # ---------- Adapt recipe (F06) ----------
    def _adapt_tab(self, f):
        bar = ttk.Frame(f); bar.pack(fill="x", padx=6, pady=6)
        self.a_id = tk.StringVar(); ttk.Label(bar, text="Library recipe:").pack(side="left")
        self.adapt_combo = ttk.Combobox(bar, textvariable=self.a_id, width=24, state="readonly"); self.adapt_combo.pack(side="left", padx=4)
        self.a_vars = {}
        for label, key in RESTRICTIONS:
            v = tk.BooleanVar(); self.a_vars[key] = v; ttk.Checkbutton(bar, text=label, variable=v).pack(side="left", padx=2)
        ttk.Label(f, text="Or paste recipe text (needs LLM):").pack(anchor="w", padx=6)
        self.a_text = tk.Text(f, height=5); self.a_text.pack(fill="x", padx=6)
        b2 = ttk.Frame(f); b2.pack(fill="x", padx=6, pady=4)
        ttk.Button(b2, text="Adapt Recipe", command=self.adapt).pack(side="left")
        self.a_save = ttk.Button(b2, text="Save to Library", command=self.save_adapted, state="disabled"); self.a_save.pack(side="left", padx=6)
        self.a_badge = tk.StringVar(); ttk.Label(b2, textvariable=self.a_badge, font=("Helvetica", 12, "bold")).pack(side="left", padx=10)
        self.a_out = tk.Text(f, wrap="word"); self.a_out.pack(fill="both", expand=True, padx=6, pady=6)
    def adapt(self):
        rs = [k for k, v in self.a_vars.items() if v.get()]; text = self.a_text.get("1.0", "end").strip() or None
        if not rs or not (text or self.a_id.get()): return messagebox.showinfo("Adapt", "Pick a recipe (or paste text) and at least one restriction.")
        def done(r, e):
            if e: return self.err(e)
            self.adapted = r["recipe"]; rec = r["recipe"]; self.a_save.config(state="normal")
            self.a_badge.set("SAFETY VERIFIED" if r["verified"] else "NOT VERIFIED: " + ", ".join(r["remaining_flags"]))
            out = f"{rec['title']}   [mode: {r['mode']}]\n\nChanges:\n" + ("\n".join("- " + c for c in r["changes"]) or "- none") + "\n\nIngredients:\n"
            out += "\n".join(f"- {i['qty']:g} {i['unit']} {i['name']}" for i in rec["ingredients"]) + "\n\nSteps:\n" + "\n".join(f"{n}. {s}" for n, s in enumerate(rec["steps"], 1))
            if r["warnings"]: out += "\n\nWARNINGS:\n" + "\n".join("! " + w for w in r["warnings"])
            self.a_out.delete("1.0", "end"); self.a_out.insert("end", out)
        self.bg(lambda: self.c.adapt_recipe(None if text else self.a_id.get(), text=text, restrictions=rs, use_llm=self.use_llm.get()), done)
    def save_adapted(self):
        if self.adapted:
            try: self.c.save_recipe(self.adapted); messagebox.showinfo("Saved", f"Saved as {self.adapted['id']}")
            except ValidationError as e: self.err(e)

    # ---------- Cooking mode (F05) ----------
    def _cook_tab(self, f):
        bar = ttk.Frame(f); bar.pack(fill="x", padx=6, pady=6)
        self.k_id = tk.StringVar(); self.k_spm = tk.StringVar(value="60")
        ttk.Label(bar, text="Recipe:").pack(side="left"); self.cook_combo = ttk.Combobox(bar, textvariable=self.k_id, width=24, state="readonly"); self.cook_combo.pack(side="left", padx=4)
        ttk.Label(bar, text="Seconds per minute (use 5 for demos):").pack(side="left", padx=4); ttk.Entry(bar, textvariable=self.k_spm, width=5).pack(side="left")
        ttk.Button(bar, text="Start Cooking", command=self.start_cook).pack(side="left", padx=8)
        self.k_step = tk.StringVar(value="Pick a recipe and press Start Cooking."); ttk.Label(f, textvariable=self.k_step, font=("Helvetica", 20), wraplength=1000, justify="left").pack(anchor="w", padx=10, pady=14)
        nav = ttk.Frame(f); nav.pack(anchor="w", padx=10)
        for text, cmd in (("< Prev", self.k_prev), ("Next >", self.k_next), ("Start Timer", self.k_timer), ("Finish Cooking", self.k_finish)): ttk.Button(nav, text=text, command=cmd).pack(side="left", padx=4)
        self.k_timers = tk.StringVar(value="No active timers"); ttk.Label(f, textvariable=self.k_timers, font=("Helvetica", 14)).pack(anchor="w", padx=10, pady=8)
        ask = ttk.LabelFrame(f, text="Ask Kitchen Assistant"); ask.pack(fill="both", expand=True, padx=10, pady=6)
        self.k_q = tk.StringVar(); e = ttk.Entry(ask, textvariable=self.k_q, width=70); e.pack(side="top", anchor="w", padx=4, pady=4); e.bind("<Return>", lambda _e: self.k_ask())
        ttk.Button(ask, text="Ask", command=self.k_ask).pack(anchor="w", padx=4)
        self.k_ans = tk.Text(ask, height=8, wrap="word"); self.k_ans.pack(fill="both", expand=True, padx=4, pady=4)
    def _show_step(self):
        d = self.session.current(); t = f"Step {d['index']}/{d['total']}: {d['text']}"
        if d["suggested_minutes"]: t += f"\n(suggested timer: {d['suggested_minutes']} min)"
        self.k_step.set(t)
    def start_cook(self):
        if not self.k_id.get(): return messagebox.showinfo("Cooking", "Pick a recipe first.")
        try: self.session = self.c.start_cooking(self.k_id.get(), float(self.k_spm.get()), use_llm=self.use_llm.get())
        except (ValueError, ValidationError) as e: return self.err(e)
        self.session.attach(_Listener(self.post, self._on_cook_event)); self._show_step(); self.k_ans.delete("1.0", "end")
    def _need(self):
        if not self.session: messagebox.showinfo("Cooking", "Press Start Cooking first."); return False
        return True
    def k_prev(self):
        if self._need(): self.session.prev(); self._show_step()
    def k_next(self):
        if self._need():
            try: self.session.next(); self._show_step()
            except ValidationError as e: messagebox.showwarning("Timer expired", str(e))
    def k_timer(self):
        if not self._need(): return
        try: self.session.start_timer()
        except ValidationError:
            m = simpledialog.askfloat("Timer", "Minutes:", parent=self)
            if m:
                try: self.session.start_timer(m)
                except ValidationError as e: self.err(e)
    def k_ask(self):
        if not self._need() or not self.k_q.get().strip(): return
        q = self.k_q.get().strip()
        def done(a, e):
            if e: return self.err(e)
            self.k_ans.delete("1.0", "end"); self.k_ans.insert("end", f"[{a['mode']}] {a['answer']}\nSources: {a['sources']}")
        self.bg(lambda: self.session.ask(q, use_llm=self.use_llm.get()), done)
    def k_finish(self):
        if not self._need(): return
        r = self.session.finish(); messagebox.showinfo("Done cooking", f"Pantry updated; used: {', '.join(r['deducted'])}")
        self.feedback_dialog(r["recipe_id"]); self.session = None; self.k_timers.set("No active timers")
    def _on_cook_event(self, event, payload):
        if event == "timer_done":
            self.bell(); messagebox.showinfo("Timer", f"{payload['label']} finished! Acknowledge to continue.")
            if self.session: self.session.acknowledge()
    def _tick(self):
        self.after(1000, self._tick)
        if self.session:
            rem = self.session.remaining()
            self.k_timers.set("Timers: " + "   ".join(f"#{t}: {s // 60}:{s % 60:02d}" for t, s in rem.items()) if rem else "No active timers")

    # ---------- Export (F09) ----------
    def _export_tab(self, f):
        ttk.Label(f, text="Export the current meal plan / grocery list").pack(anchor="w", padx=10, pady=10)
        for label, fmt, ext in (("Plan -> JSON", "json", ".json"), ("Plan -> Markdown", "md", ".md"), ("Plan -> Calendar (.ics)", "ics", ".ics"), ("Grocery -> CSV", "csv", ".csv")):
            ttk.Button(f, text=label, command=lambda fm=fmt, ex=ext: self.do_export(fm, ex)).pack(anchor="w", padx=10, pady=4)
    def do_export(self, fmt, ext):
        if not self.c.get_plan(): return messagebox.showinfo("Export", "Generate a meal plan first.")
        while True:
            path = filedialog.asksaveasfilename(defaultextension=ext, initialfile="meal_plan" + ext)
            if not path: return
            ok, err = self.c.export(fmt, path)
            if ok: return messagebox.showinfo("Export", f"Saved {path}")
            if not messagebox.askretrycancel("Cannot write file", f"{err}\n\nChoose another location?"): return

def main(): MainGUIView().mainloop()
if __name__ == "__main__": main()
