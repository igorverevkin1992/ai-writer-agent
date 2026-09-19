import shutil
from importlib import resources
from pathlib import Path

import pytest

from ugar import exporter, guard
from ugar.paths import Workspace

DEMO = Path(str(resources.files("ugar").joinpath("data/демо")))


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    """Рабочая область с демо-библиотекой и стартовым регрессионным корпусом."""
    shutil.copytree(DEMO / "УГАР_Библиотека", tmp_path / "УГАР_Библиотека")
    (tmp_path / "config.yaml").write_text("library_dir: УГАР_Библиотека\n", encoding="utf-8")
    golden = tmp_path / "regression" / "golden"
    golden.mkdir(parents=True)
    for f in (DEMO / "регрессия").glob("*.json"):
        shutil.copyfile(f, golden / f.name)
    workspace = Workspace(tmp_path)
    guard.set_library_dir(tmp_path / "УГАР_Библиотека")
    exporter.run_export(tmp_path / "УГАР_Библиотека", workspace.exports, workspace.logs)
    return workspace


@pytest.fixture
def library(ws: Workspace) -> Path:
    return ws.root / "УГАР_Библиотека"
