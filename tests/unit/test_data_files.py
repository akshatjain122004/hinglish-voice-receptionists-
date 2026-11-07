import pathlib
import re

import yaml

DATA = pathlib.Path("data")


def test_clinic_yaml_has_required_keys():
    c = yaml.safe_load((DATA / "clinic.yaml").read_text())
    for key in ["name", "hours", "services", "slot_minutes", "weekly_off"]:
        assert key in c


def test_at_least_15_faqs():
    text = (DATA / "faqs.md").read_text()
    assert len(re.findall(r"^##\s", text, re.MULTILINE)) >= 15


def test_golden_calls_well_formed():
    cases = yaml.safe_load((DATA / "test_calls.yaml").read_text())
    assert len(cases) >= 20
    for c in cases:
        assert {"id", "turns", "expected"} <= c.keys()
