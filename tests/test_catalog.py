"""The sourced parts catalog must validate (schema, parameter ranges, sources)."""
import json

import pytest

import framewright.geometry.clearance  # noqa: F401  (registers parameters)
import framewright.geometry.solver  # noqa: F401
from framewright.model import catalog, library

FILES = catalog.catalog_files()


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_catalog_file_validates(path):
    assert catalog.validate_file(path) == []


def test_catalog_items_load_and_apply():
    from framewright.model.design import Design
    library.reload()
    for path in FILES:
        doc = json.loads(path.read_text(encoding="utf-8"))
        items = library.items(doc["category"])
        ids = {it.id for it in items}
        sample = doc["items"][:: max(1, len(doc["items"]) // 10)]
        for raw in sample:
            assert raw["id"] in ids
            it = next(i for i in items if i.id == raw["id"])
            d = Design()
            library.apply(d, it)               # must not raise


def test_validator_rejects_bad_items():
    bad = {"id": "X Bad", "name": "", "values": {"fork_length": "long", "stack": 1},
           "meta": {"sources": [], "status": "maybe"}}
    errs = catalog.validate_item(bad, "forks")
    assert len(errs) >= 5
