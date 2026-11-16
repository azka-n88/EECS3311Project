"""F08: receipt / unstructured text -> structured pantry items (LLM NER with regex fallback)."""
import json, re
from datetime import date, timedelta
from .llm import LLMError
from .units import to_base, UnitError

SHELF = {"Produce": 5, "Dairy": 10, "Meat": 3, "Bakery": 5, "Pantry": 180}
CAT_WORDS = {"Meat": "chicken beef pork turkey salmon tuna shrimp steak fish bacon", "Dairy": "milk yogurt cheese egg eggs butter cream",
             "Produce": "apple banana spinach tomato onion carrot lettuce potato avocado berries broccoli cucumber pepper garlic lemon",
             "Bakery": "bread tortilla bagel bun", "Pantry": "rice pasta flour oil sugar beans lentils oats sauce salt cereal"}
UNITS = {"kg": "kg", "g": "g", "gram": "g", "grams": "g", "lb": "lb", "lbs": "lb", "oz": "oz", "l": "l", "litre": "l", "liter": "l",
         "ml": "ml", "cup": "cup", "cups": "cup", "tbsp": "tbsp", "tsp": "tsp", "pc": "pc", "pcs": "pc"}
_U = "|".join(sorted(UNITS, key=len, reverse=True))

def guess_category(name):
    words = set(re.findall(r"[a-z]+", name.lower()))
    for cat, ws in CAT_WORDS.items():
        if words & set(ws.split()): return cat
    return "Other"

def _item(name, qty, unit, category=None, shelf=None, raw=""):
    name = (name or "").strip().lower(); review = False
    try:
        qty = float(qty); to_base(1, unit)
        if qty <= 0 or not name: raise ValueError
    except (TypeError, ValueError, UnitError): review = True
    category = category if category in ("Produce", "Dairy", "Meat", "Bakery", "Pantry", "Other") else guess_category(name)
    days = shelf if isinstance(shelf, (int, float)) and shelf > 0 else SHELF.get(category)
    exp = (date.today() + timedelta(days=int(days))).isoformat() if days and not review else None
    if review: category = "Uncategorized"
    return {"name": name or raw, "qty": qty if not review else 0, "unit": unit if not review else "", "category": category,
            "expiry_date": exp, "review": review, "raw": raw}

def regex_parse(text):
    items = []
    for raw in text.splitlines():
        line = re.sub(r"\$?\s*\d+\.\d{2}\s*$", "", raw).strip(" -*•\t")
        if not line: continue
        if len(re.findall(r"[A-Za-z]", line)) < 3: items.append(_item("", 0, "", raw=raw.strip())); continue
        m = re.match(rf"^(\d+(?:\.\d+)?)\s*({_U})?\b\s*(?:of\s+)?(.+)$", line, re.I)
        n = re.match(rf"^(.+?)\s*[x@:\-]?\s*(\d+(?:\.\d+)?)\s*({_U})?$", line, re.I)
        if m: items.append(_item(m.group(3), m.group(1), UNITS.get((m.group(2) or "pc").lower(), "pc"), raw=raw.strip()))
        elif n: items.append(_item(n.group(1), n.group(2), UNITS.get((n.group(3) or "pc").lower(), "pc"), raw=raw.strip()))
        elif re.fullmatch(r"[A-Za-z][A-Za-z ]+", line): items.append(_item(line, 1, "pc", raw=raw.strip()))
        else: items.append(_item("", 0, "", raw=raw.strip()))
    return items

def parse_receipt(text, llm=None, use_llm=True):
    """Returns (items, mode). mode: 'llm' or 'regex' / 'regex-fallback'."""
    if use_llm and llm is not None:
        payload = {"task": "Extract grocery items from this receipt or notes.", "text": text,
                   "output_format": {"items": [{"name": "", "qty": 1, "unit": "g|kg|ml|l|cup|tbsp|tsp|pc|oz|lb",
                                                "category": "Produce|Dairy|Meat|Bakery|Pantry|Other", "shelf_life_days": 7}]}}
        try:
            res = llm.generate([{"role": "user", "content": json.dumps(payload)}], system="You extract structured data. Reply with ONLY a JSON object.")
            m = re.search(r"\{.*\}", res["text"], re.S)
            data = json.loads(m.group(0))["items"]
            return [_item(i.get("name"), i.get("qty"), i.get("unit", ""), i.get("category"), i.get("shelf_life_days"), raw=str(i.get("name"))) for i in data], "llm"
        except (LLMError, ValueError, KeyError, AttributeError, TypeError):
            return regex_parse(text), "regex-fallback"
    return regex_parse(text), "regex"
