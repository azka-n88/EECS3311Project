"""F05: interactive cooking session (Observer Subject) with async timers and RAG+LLM assistant."""
import re, threading, time, itertools
from .llm import LLMError
from .models import ValidationError
from .observer import Subject
from .units import UnitError

class CookingSession(Subject):
    def __init__(self, recipe, tools, pantry, llm=None, seconds_per_min=60):
        super().__init__(); self.recipe, self.tools, self.pantry, self.llm = recipe, tools, pantry, llm
        self.steps, self.i, self.spm = recipe["steps"], 0, seconds_per_min
        self.timers, self._ids, self.awaiting_ack, self.completed = {}, itertools.count(1), False, False

    def current(self): return {"index": self.i + 1, "total": len(self.steps), "text": self.steps[self.i], "suggested_minutes": self.suggest_timer()}
    def suggest_timer(self):
        m = re.search(r"(\d+)\s*min", self.steps[self.i]); return int(m.group(1)) if m else None
    def next(self):
        if self.awaiting_ack: raise ValidationError("A timer has expired - acknowledge it first")
        if self.i < len(self.steps) - 1: self.i += 1; self.notify_observers("step_changed", self.current())
        return self.current()
    def prev(self):
        if self.i > 0: self.i -= 1; self.notify_observers("step_changed", self.current())
        return self.current()

    def start_timer(self, minutes=None, label=None):
        minutes = minutes or self.suggest_timer()
        if not minutes or minutes <= 0: raise ValidationError("No timer length given and none found in this step")
        tid = next(self._ids); t = threading.Timer(minutes * self.spm, self._expire, [tid]); t.daemon = True
        self.timers[tid] = {"label": label or f"Step {self.i + 1} ({minutes} min)", "end": time.time() + minutes * self.spm, "done": False, "t": t}
        t.start(); self.notify_observers("timer_started", {"id": tid, "label": self.timers[tid]["label"]}); return tid
    def remaining(self):
        return {tid: max(0, round(v["end"] - time.time())) for tid, v in self.timers.items() if not v["done"]}
    def _expire(self, tid):
        self.timers[tid]["done"] = True; self.awaiting_ack = True
        self.notify_observers("timer_done", {"id": tid, "label": self.timers[tid]["label"]})
    def acknowledge(self): self.awaiting_ack = False; self.notify_observers("timer_ack", None)

    def ask(self, query, use_llm=True):
        """Hybrid: retrieve technique docs (RAG) then let the LLM answer in context; falls back to retrieved text."""
        hits = self.tools["search_techniques"].run(query=query)
        if use_llm and self.llm is not None:
            import json
            payload = {"question": query, "recipe": self.recipe["title"], "current_step": self.steps[self.i],
                       "ingredients": self.recipe["ingredients"], "servings": self.recipe["servings"], "reference_docs": hits}
            try:
                res = self.llm.generate([{"role": "user", "content": json.dumps(payload)}],
                                        system="You are a kitchen assistant. Answer briefly, scale any substitution to the recipe quantities, and prefer the reference docs.")
                if res["text"].strip(): return {"answer": res["text"].strip(), "mode": "llm+rag", "sources": [h["id"] for h in hits]}
            except LLMError: pass
        if hits: return {"answer": hits[0]["text"], "mode": "rag-only", "sources": [hits[0]["id"]]}
        return {"answer": "No guidance found for that question.", "mode": "none", "sources": []}

    def finish(self):
        for v in self.timers.values(): v["t"].cancel()
        used = []
        for ing in self.recipe["ingredients"]:
            try: self.pantry.deduct(ing["name"], ing["qty"] / max(self.recipe["servings"], 1), ing["unit"]); used.append(ing["name"])
            except UnitError: pass
        self.completed = True; self.notify_observers("completed", {"recipe_id": self.recipe["id"]})
        return {"deducted": used, "feedback_prompt": True, "recipe_id": self.recipe["id"]}
