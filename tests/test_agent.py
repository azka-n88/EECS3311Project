import json, pytest
from culinarymind import db
from culinarymind.controller import ServiceController
from culinarymind.llm import LLMError
from culinarymind.models import recipe_cost
from culinarymind.strategies import get_strategy
from culinarymind.tools import SystemToolFactory
from culinarymind.validation import build_default_chain

class FakeLLM:  # test double for the LLM API
    def __init__(self, replies): self.replies = list(replies); self.calls = 0
    def generate(self, messages, tools=None, system=None):
        self.calls += 1; r = self.replies.pop(0)
        if isinstance(r, Exception): raise r
        return {"text": r, "tool_calls": []}

def mk(tmp_path, llm=None): return ServiceController(db.connect(str(tmp_path / "a.db")), llm=llm)
def P(*rows): return json.dumps({"plan": [{"day": d, "meal": m, "recipe_id": r} for d, m, r in rows]})

def test_self_reflection_retries_after_allergen_violation(tmp_path):
    bad = P((1, "breakfast", "oats_banana"), (1, "lunch", "chicken_stirfry"), (1, "dinner", "salmon_bowl"))
    good = P((1, "breakfast", "oats_banana"), (1, "lunch", "lentil_soup"), (1, "dinner", "salmon_bowl"))
    llm = FakeLLM([bad, good]); c = mk(tmp_path, llm)
    r = c.generate_plan(days=1, allergens=["soy"])
    assert r["ok"] and r["mode"] == "llm" and r["attempts"] == 2 and llm.calls == 2

def test_llm_failure_falls_back_to_greedy(tmp_path):
    c = mk(tmp_path, FakeLLM([LLMError("no key")]))
    r = c.generate_plan(days=2, budget=40)
    assert r["ok"] and r["mode"] == "greedy-fallback" and r["total_cost"] <= 40

def test_infeasible_budget_gives_suggestions(tmp_path):
    r = mk(tmp_path).generate_plan(days=7, budget=5, use_llm=False)
    assert not r["ok"] and r["suggestions"]

def test_greedy_respects_allergen_and_diet(tmp_path):
    r = mk(tmp_path).generate_plan(days=3, diet="vegan", allergens=["gluten"], use_llm=False)
    c = mk(tmp_path); assert r["ok"]
    for s in r["plan"]:
        rec = c.plan.recipes[s["recipe_id"]]; assert "gluten" not in rec["allergens"] and "vegan" in rec["tags"]

def test_swap_respects_max_prep_and_refreshes_grocery(tmp_path):
    c = mk(tmp_path); c.generate_plan(days=2, use_llm=False)
    r = c.swap_meal(2, "dinner", reason="Need a quick option", max_prep=10, use_llm=False)
    assert r["ok"] and c.plan.recipes[r["new"]]["prep_min"] <= 10 and "grocery" in r

def test_swap_no_alternative(tmp_path):
    c = mk(tmp_path); c.generate_plan(days=1, use_llm=False)
    r = c.swap_meal(1, "dinner", max_prep=1, use_llm=False)
    assert not r["ok"] and r["suggestions"]

def test_chain_early_exit():
    c = mk.__globals__["ServiceController"](db.connect(":memory:"))
    plan = [{"day": 1, "meal": "lunch", "recipe_id": "chicken_stirfry"}, {"day": 1, "meal": "dinner", "recipe_id": "salmon_bowl"}]
    ctx = {"recipes": c.plan.recipes, "allergens": {"soy"}, "diet": None, "budget": 1, "kcal": None}
    issues = build_default_chain().handle(plan, ctx)
    assert any("allergen" in i for i in issues) and not any("budget" in i for i in issues)

def test_strategies_rank_differently():
    c = ServiceController(db.connect(":memory:")); pool = list(c.plan.recipes.values())
    ctx = {"expiring": {"spinach"}}
    assert recipe_cost(get_strategy("budget").rank(pool, ctx)[0]) == min(map(recipe_cost, pool))
    assert "spinach" in [i["name"] for i in get_strategy("zero_waste").rank(pool, ctx)[0]["ingredients"]]
    assert get_strategy("protein").rank(pool, ctx)[0]["macros"]["protein"] == max(r["macros"]["protein"] for r in pool)

def test_factory_and_rag():
    c = ServiceController(db.connect(":memory:")); f = SystemToolFactory(c.pantry, c.plan)
    assert len(f.create_all()) == 4
    with pytest.raises(KeyError): f.create_tool("nope")
    assert f.create_tool("search_techniques").run(query="my cream sauce is separating")[0]["id"] == "cream_sauce_fix"
