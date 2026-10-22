import re

import pytest

from rootsignal_agent.rag.chunking import RUNBOOK_DIR, chunk_dir, chunk_markdown
from rootsignal_agent.sim.models import RemediationAction

ROOT_CAUSE = {
    "oom.md",
    "data_skew.md",
    "upstream_late.md",
    "auth_expired.md",
    "schema_change.md",
    "disk_full.md",
    "resource_starvation.md",
    "network_timeout.md",
}
GENERIC = {"general_triage.md", "escalation_policy.md"}
HEADINGS = ["Symptoms", "Diagnosis", "Remediation", "Escalate when", "Commonly confused with"]


def test_folder_has_exactly_the_expected_runbooks():
    assert {p.name for p in RUNBOOK_DIR.glob("*.md")} == ROOT_CAUSE | GENERIC


@pytest.mark.parametrize("name", sorted(ROOT_CAUSE | GENERIC))
def test_runbook_structure(name):
    text = (RUNBOOK_DIR / name).read_text()
    chunks = chunk_markdown(name, text)
    assert len(chunks) >= 3
    assert [c.section for c in chunks] == HEADINGS
    assert text.startswith("# ")


@pytest.mark.parametrize("name", sorted(ROOT_CAUSE))
def test_root_cause_runbook_length(name):
    assert 250 <= len((RUNBOOK_DIR / name).read_text().split()) <= 400


@pytest.mark.parametrize("name", sorted(ROOT_CAUSE))
def test_platform_action_is_allowlisted(name):
    match = re.search(r"^Platform action: `(\w+)`", (RUNBOOK_DIR / name).read_text(), re.M)
    assert match, f"{name} has no Platform action line"
    assert match.group(1) in {a.value for a in RemediationAction}


def test_chunks_are_non_empty_and_bounded():
    chunks = chunk_dir()
    assert chunks
    for c in chunks:
        assert c.text.strip()
        assert len(c.embed_text) <= 2000
        assert c.embed_text.startswith(f"{c.title} - {c.section}: ")


def test_empty_sections_are_dropped():
    chunks = chunk_markdown("x.md", "# T\n\n## A\n\n## B\nbody\n")
    assert [c.section for c in chunks] == ["B"]
