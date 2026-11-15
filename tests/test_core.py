import pytest
from datetime import date, timedelta
from culinarymind import db
from culinarymind.controller import ServiceController
from culinarymind.models import ValidationError
from culinarymind.observer import Observer
from culinarymind.units import convert, UnitError

class Spy(Observer):
    def __init__(self): self.events = []
    def update(self, s, e, p=None): self.events.append(e)

@pytest.fixture
def c(tmp_path): return ServiceController(db.connect(str(tmp_path / "t.db")))

def test_convert():
    assert convert(3, "tbsp", "cup") == pytest.approx(0.1875, rel=1e-2)
    with pytest.raises(UnitError): convert(1, "g", "ml")

def test_pantry_validation_and_observer(c):
    spy = Spy(); c.pantry.attach(spy)
    with pytest.raises(ValidationError): c.add_pantry_item(name="milk", qty="abc", unit="l")
    with pytest.raises(ValidationError): c.add_pantry_item(name="milk", qty=-1, unit="l")
    c.add_pantry_item(name="milk", qty=1, unit="l"); c.add_pantry_item(name="milk", qty=1, unit="l")
    assert c.list_pantry()[0]["qty"] == 2 and spy.events == ["pantry_changed"] * 2

def test_expiry_status(c):
    soon = (date.today() + timedelta(days=1)).isoformat()
    c.add_pantry_item(name="spinach", qty=100, unit="g", expiry_date=soon)
    assert c.list_pantry()[0]["status"] == "red" and len(c.expiring()) == 1

def test_grocery_deducts_pantry(c):
    c.add_pantry_item(name="rice", qty=1, unit="cup")
    c.set_meal(1, "dinner", "chicken_stirfry")
    names = [i["name"] for v in c.grocery_list()["by_aisle"].values() for i in v]
    assert "rice" not in names and "chicken breast" in names

def test_ambiguous_unit_flagged(c):
    c.set_meal(1, "dinner", "pasta_tomato")
    assert c.grocery_list()["needs_review"][0]["name"] == "basil"

def test_export(c, tmp_path):
    c.set_meal(1, "dinner", "lentil_soup")
    for fmt in ("json", "md", "ics", "csv"):
        assert c.export(fmt, str(tmp_path / f"o.{fmt}")) == (True, None)
    assert c.export("json", "/nonexistent_dir/x.json")[0] is False
