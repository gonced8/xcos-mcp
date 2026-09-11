# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from xcos_mcp import catalog


def _fake_install(tmp_path: Path) -> Path:
    root = tmp_path / "scilab"
    macros = root / "share" / "scilab" / "modules" / "scicos_blocks" / "macros"
    (macros / "Sources").mkdir(parents=True, exist_ok=True)
    (macros / "Sources" / "CONST_m.sci").write_text("function x=CONST_m(job,arg1,arg2)\nendfunction\n")
    (macros / "Sinks").mkdir(exist_ok=True)
    (macros / "Sinks" / "TOWS_c.sci").write_text("function x=TOWS_c(job,arg1,arg2)\nendfunction\n")
    return root


def test_catalog_is_discovered_from_the_runtime(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(catalog, "scilab_root", lambda: _fake_install(tmp_path))
    result = catalog.list_blocks("const", 10)
    assert result["blocks"] == [{
        "name": "CONST_m",
        "category": "Sources",
        "source_path": result["blocks"][0]["source_path"],
    }]
    assert "function x=CONST_m" in catalog.block_source("CONST_m")["source"]


@pytest.mark.parametrize("name", ["", "bad-name", "x();quit"])
def test_block_names_cannot_inject_scilab(name: str):
    with pytest.raises(ValueError):
        catalog.block_source(name)
