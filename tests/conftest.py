import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def qapp():
    from bikebox.qt import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def design():
    from bikebox.model.design import Design
    return Design()


@pytest.fixture
def geometry(design):
    from bikebox.geometry.solver import solve
    return solve(design)
