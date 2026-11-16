import json, time, pytest
from culinarymind import db
from culinarymind.controller import ServiceController
from culinarymind.models import ValidationError
from culinarymind.llm import LLMError
from culinarymind.adapt import scan

class FakeLLM:
    def __init__(self, replies): self.replies = list(replies)
    def generate(self, messages, tools=None, system=None):
        r = self.replies.pop(0)
        if isinstance(r, Exception): raise r
        return {"text": r, "tool_calls": []}
def mk(tmp, llm=None): return ServiceController(db.connect(str(tmp / "f.db")), llm=llm or FakeLLM([LLMError("off")] * 20))

def test_receipt_regex_flags_garbled(tmp_path):
    items, mode = mk(tmp_path).parse_receipt("2 kg chicken breast\nmilk 1 l\n#@!$ ??\nbananas", use_llm=False)
    by = {i["raw"]: i for i in items}
    assert mode == "regex" and by["2 kg chicken breast"]["category"] == "Meat" and by["#@!$ ??"]["review"]

def test_receipt_llm_and_import(tmp_path):
    reply = json.dumps({"items": [{"name": "Spinach", "qty": 200, "unit": "g", "category": "Produce", "shelf_life_days": 4}, {"name": "mystery", "qty": 1, "unit": "bunch"}]})
    c = mk(tmp_path, FakeLLM([reply])); items, mode = c.parse_receipt("x")
    assert mode == "llm" and items[1]["review"]
    r = c.confirm_import(items); assert r["added"] == 1 and len(r["skipped"]) == 1 and c.list_pantry()[0]["name"] == "spinach"

def test_feedback_rule_and_conflict_and_agent_reads_it(tmp_path):
    c = mk(tmp_path)
    r = c.submit_feedback("lentil_soup", 5, notes="love it", use_llm=False); assert r["ok"]
    r = c.submit_feedback("lentil_soup", 1, notes="too salty", use_llm=False); assert r["conflict"]
    r = c.submit_feedback("lentil_soup", 1, notes="too salty", use_llm=False, confirm=True); assert r["ok"]
    assert any("too salty" in p for p in c.preferences()) and not any("love it" in p for p in c.preferences())
    assert any("too salty" in p for p in c.engine.preferences())
    with pytest.raises(ValidationError): c.submit_feedback("lentil_soup", 9, use_llm=False)

def test_adapt_gluten_dairy_verified(tmp_path):
    r = mk(tmp_path).adapt_recipe("turkey_meatballs", restrictions=["gluten"], use_llm=False)
    assert r["verified"] and "gluten" not in r["recipe"]["allergens"] and any("rice noodles" in x["name"] for x in r["recipe"]["ingredients"])
    r = mk(tmp_path).adapt_recipe("salmon_bowl", restrictions=["fish"], use_llm=False)
    assert not r["verified"] and r["warnings"]

def test_adapt_vegan_and_save_then_plannable(tmp_path):
    c = mk(tmp_path); r = c.adapt_recipe("chicken_stirfry", restrictions=["vegan"], use_llm=False)
    assert r["verified"] and not scan(r["recipe"], ["vegan"]); c.save_recipe(r["recipe"])
    c.set_meal(1, "dinner", r["recipe"]["id"])
    assert r["recipe"]["id"] in mk(tmp_path).plan.recipes          # persisted

def test_nutrition(tmp_path):
    c = mk(tmp_path); c.generate_plan(days=2, use_llm=False)
    r = c.nutrition({"age": 22, "weight_kg": 70, "activity": "moderate", "goal": "maintain"}, use_llm=False)
    assert r["ok"] and r["compliance_pct"]["kcal"] > 0 and r["narrative_mode"] == "template"

def test_cooking_timer_ack_rag_and_finish(tmp_path):
    c = mk(tmp_path); c.add_pantry_item(name="rice", qty=2, unit="cup")
    s = c.start_cooking("chicken_stirfry", seconds_per_min=0.01, use_llm=False)
    events = []; s.attach(type("O", (), {"update": lambda self, sub, e, p=None: events.append(e)})())
    assert s.current()["index"] == 1
    s.start_timer(1); time.sleep(0.3); assert "timer_done" in events and s.awaiting_ack
    with pytest.raises(ValidationError): s.next()
    s.acknowledge(); s.next()
    a = s.ask("my cream sauce is separating", use_llm=False); assert a["sources"] == ["cream_sauce_fix"]
    assert "rice" in s.finish()["deducted"] and c.list_pantry()[0]["qty"] < 2
