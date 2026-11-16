"""F10: post-meal feedback -> long-term preference rules (LLM extraction, deterministic fallback)."""
import json, re
from datetime import datetime
from .llm import LLMError
from .models import ValidationError

def _extract(recipe, rating, notes, llm, use_llm):
    if use_llm and llm is not None and notes.strip():
        payload = {"task": "Extract ONE long-term cooking preference rule from this feedback.", "recipe": recipe["title"],
                   "rating": rating, "notes": notes, "output_format": {"rule": "Dislike: <x> / Action: <y>", "sentiment": "positive|negative|neutral"}}
        try:
            res = llm.generate([{"role": "user", "content": json.dumps(payload)}], system="Reply with ONLY a JSON object.")
            d = json.loads(re.search(r"\{.*\}", res["text"], re.S).group(0))
            if d.get("rule"): return d["rule"], d.get("sentiment", "neutral"), "llm"
        except (LLMError, ValueError, AttributeError, KeyError): pass
    sentiment = "negative" if rating <= 2 else "positive" if rating >= 4 else "neutral"
    base = notes.strip() or recipe["title"]
    rule = {"negative": f"Dislike: {base} / Action: reduce or avoid in future plans",
            "positive": f"Like: {base} / Action: favour similar meals", "neutral": f"Note: {base}"}[sentiment]
    return rule, sentiment, "heuristic"

def submit_feedback(con, recipes, recipe_id, rating, effort="", notes="", llm=None, use_llm=True, confirm=False):
    if recipe_id not in recipes: raise ValidationError(f"Unknown recipe {recipe_id!r}")
    try: rating = int(rating)
    except (TypeError, ValueError): raise ValidationError("Rating must be 1-5")
    if not 1 <= rating <= 5: raise ValidationError("Rating must be 1-5")
    prev = [r["rating"] for r in con.execute("SELECT rating FROM feedback WHERE recipe_id=?", (recipe_id,))]
    if prev and abs(prev[-1] - rating) >= 2 and not confirm:        # Alternative flow A1: contradictory feedback
        return {"ok": False, "conflict": True, "previous_rating": prev[-1],
                "message": f"You rated this {prev[-1]} before and {rating} now. Confirm to override your earlier preference (recent feedback wins)."}
    rule, sentiment, mode = _extract(recipes[recipe_id], rating, notes, llm, use_llm)
    now = datetime.now().isoformat(timespec="seconds")
    if prev and confirm: con.execute("DELETE FROM preferences WHERE source=?", (f"recipe:{recipe_id}",))
    con.execute("INSERT INTO feedback(recipe_id,rating,effort,notes,created) VALUES(?,?,?,?,?)", (recipe_id, rating, effort, notes, now))
    con.execute("INSERT INTO preferences(rule,source,created) VALUES(?,?,?)", (rule, f"recipe:{recipe_id}", now))
    con.commit()
    return {"ok": True, "rule": rule, "sentiment": sentiment, "mode": mode}

def list_preferences(con): return [r["rule"] for r in con.execute("SELECT rule FROM preferences ORDER BY id")]
