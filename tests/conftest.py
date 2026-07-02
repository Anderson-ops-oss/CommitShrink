"""Shared fixture: build the demo repo once and run the full pipeline on it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]


def _load_fixture_builder():
    spec = importlib.util.spec_from_file_location(
        "make_fixture", REPO_ROOT / "scripts" / "make_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_fixture"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def assessment(tmp_path_factory):
    from commit_shrink.pipeline import assess_repo

    builder = _load_fixture_builder()
    repo = tmp_path_factory.mktemp("fixture") / "demo-repo"
    _, period_end = builder.build_fixture(repo)
    return assess_repo(repo, days=7, until=period_end)


def by_id(assessment, symptom_id):
    for d in assessment.diagnoses:
        if d.id == symptom_id:
            return d
    return None
