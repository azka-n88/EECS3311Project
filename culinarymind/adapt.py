"""F06: recipe adaptation & allergen sanitizer (deterministic substitution table + optional LLM refinement
+ deterministic safety verification)."""
import copy, json, re
from .llm import LLMError
from .models import ValidationError

FREE = ("free", "vegan", "plant", "flax", "coconut aminos", "oat milk", "rice noodles", "sunflower", "chickpeas (mashed)")
MEATS = ["chicken", "beef", "turkey", "steak", "salmon", "tuna", "shrimp"]
KW = {"gluten": ["pasta", "bread", "tortilla", "flour", "granola", "soy sauce", "noodle"],
      "dairy": ["milk", "yogurt", "cheese", "butter", "cream"], "egg": ["egg", "mayonnaise"],
      "soy": ["tofu", "soy sauce"], "peanut": ["peanut"], "fish": ["salmon", "tuna"], "shellfish": ["shrimp"],
      "vegan": MEATS + ["egg", "milk", "yogurt", "cheese", "mayonnaise", "butter"]}
SUBS = {"gluten": {"pasta": "rice noodles", "bread": "gluten-free bread", "tortilla": "corn tortilla", "granola": "gluten-free granola", "soy sauce": "coconut aminos", "flour": "gluten-free flour", "noodle": "rice noodles"},
        "dairy": {"milk": "oat milk", "yogurt": "coconut yogurt", "cheese": "dairy-free cheese", "butter": "vegan butter", "cream": "coconut cream"},
        "egg": {"egg": "flax egg (1 tbsp ground flax + 3 tbsp water)", "mayonnaise": "vegan mayonnaise"},
        "soy": {"tofu": "chickpeas", "soy sauce": "coconut aminos"}, "peanut": {"peanut": "sunflower seed butter"},
        "fish": {}, "shellfish": {},
        "vegan": {"chicken": "firm tofu", "beef": "brown lentils", "turkey": "brown lentils", "steak": "portobello mushroom", "salmon": "marinated tofu",
                  "tuna": "chickpeas (mashed)", "shrimp": "hearts of palm", "egg": "flax egg (1 tbsp ground flax + 3 tbsp water)", "milk": "oat milk",
                  "yogurt": "coconut yogurt", "cheese": "vegan cheese", "mayonnaise": "vegan mayonnaise", "butter": "vegan butter"}}
LABEL = {"gluten": "Gluten-Free", "dairy": "Dairy-Free", "egg": "Egg-Free", "soy": "Soy-Free", "peanut": "Peanut-Free",
         "fish": "Fish-Free", "shellfish": "Shellfish-Free", "vegan": "Vegan"}

def _flag(name, restriction):
    n = name.lower()
    if any(f in n for f in FREE): return None
    return next((k for k in KW[restriction] if k in n), None)

def scan(recipe, restrictions):
    """Return ingredient names still violating a restriction."""
    return [i["name"] for i in recipe["ingredients"] for r in restrictions if _flag(i["name"], r)]

def _deterministic(recipe, restrictions):
    new = copy.deepcopy(recipe); warns, changes = [], []
    for ing in new["ingredients"]:
        for r in restrictions:
            k = _flag(ing["name"], r)
            if not k: continue
            sub = SUBS[r].get(k)
            if sub: changes.append(f"{ing['name']} -> {sub}"); ing["name"] = sub; break
            warns.append(f"No safe substitute for {ing['name']} ({LABEL[r]}); this is a core ingredient - remove or choose another recipe.")
    if len(changes) >= 3 or any("tofu" in c or "lentils" in c for c in changes):
        warns.append("Several core ingredients were replaced; texture and flavour will change noticeably.")
    if any("noodles" in c or "gluten-free bread" in c for c in changes):
        new["steps"] = list(new["steps"]) + ["Check the gluten-free product's package for cooking time; it may differ from the original."]
    return new, warns, changes

def adapt_recipe(recipe, restrictions, llm=None, use_llm=True):
    restrictions = [r for r in restrictions if r in KW]
    if not restrictions: raise ValidationError(f"Choose at least one restriction from {list(KW)}")
    new, warns, changes = _deterministic(recipe, restrictions); mode = "deterministic"
    if use_llm and llm is not None:
        payload = {"task": "Refine this adapted recipe: keep flavour balance, fix quantities/steps/cook times affected by substitutions.",
                   "restrictions": restrictions, "original": {"title": recipe["title"], "ingredients": recipe["ingredients"], "steps": recipe["steps"]},
                   "draft": {"ingredients": new["ingredients"], "steps": new["steps"], "warnings": warns},
                   "output_format": {"ingredients": [{"name": "", "qty": 1, "unit": ""}], "steps": [""], "warnings": [""]}}
        try:
            res = llm.generate([{"role": "user", "content": json.dumps(payload)}], system="You are a culinary expert. Reply with ONLY a JSON object.")
            d = json.loads(re.search(r"\{.*\}", res["text"], re.S).group(0))
            ings = [{**(new["ingredients"][i] if i < len(new["ingredients"]) else {"category": "Other", "cost": 0.5}),
                     "name": x["name"], "qty": float(x["qty"]), "unit": x["unit"]} for i, x in enumerate(d["ingredients"])]
            if ings and d["steps"]:
                cand = {**new, "ingredients": ings, "steps": d["steps"]}
                if not scan(cand, restrictions): new, mode = cand, "hybrid"; warns = d.get("warnings", warns)
        except (LLMError, ValueError, KeyError, TypeError, AttributeError): pass
    remaining = scan(new, restrictions); verified = not remaining
    suffix = ", ".join(LABEL[r] for r in restrictions)
    new["id"] = recipe["id"] + "_" + "_".join(restrictions); new["title"] = f"{recipe['title']} ({suffix})"
    new["tags"] = sorted(set(new["tags"]) | {LABEL[r].lower() for r in restrictions} | ({"vegan", "vegetarian"} if "vegan" in restrictions else set()))
    allergens = set(new["allergens"])
    if verified: allergens -= set(restrictions) | ({"egg", "dairy", "fish", "shellfish"} if "vegan" in restrictions else set())
    new["allergens"] = sorted(allergens)
    if "vegan" in restrictions and verified: new["tags"] = [t for t in new["tags"] if t != "high-protein"] if False else new["tags"]
    return {"recipe": new, "changes": changes, "warnings": warns, "verified": verified, "remaining_flags": remaining, "mode": mode}

def parse_recipe_text(text, llm):
    """Free pasted recipe text -> structured recipe (LLM required)."""
    if llm is None: raise ValidationError("Pasting free text needs the LLM; pick a library recipe instead.")
    payload = {"task": "Convert this recipe text to JSON.", "text": text,
               "output_format": {"title": "", "servings": 2, "prep_min": 20, "ingredients": [{"name": "", "qty": 1, "unit": "g|ml|cup|tbsp|tsp|pc"}], "steps": [""]}}
    res = llm.generate([{"role": "user", "content": json.dumps(payload)}], system="Reply with ONLY a JSON object.")
    d = json.loads(re.search(r"\{.*\}", res["text"], re.S).group(0))
    slug = re.sub(r"[^a-z0-9]+", "_", d["title"].lower()).strip("_")[:30]
    return {"id": "custom_" + slug, "title": d["title"], "prep_min": d.get("prep_min", 20), "servings": d.get("servings", 2),
            "meals": ["lunch", "dinner"], "tags": [], "allergens": [], "macros": {"kcal": 450, "protein": 20, "carbs": 50, "fat": 15},
            "ingredients": [{**i, "category": "Other", "cost": 0.5} for i in d["ingredients"]], "steps": d["steps"]}
