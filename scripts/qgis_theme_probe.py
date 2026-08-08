"""QGIS internal probe: confirm QGISPlus Material is selected and loaded."""

from __future__ import annotations

import json
import os
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.PyQt.QtWidgets import QApplication, QStyleFactory
from qgis.core import QgsApplication, QgsSettings


THEME_NAME = "QGISPlus Material"


def _style_chain() -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    current = QApplication.style()
    for _ in range(8):
        chain.append(
            {
                "class": current.metaObject().className(),
                "name": current.objectName(),
            }
        )
        if not hasattr(current, "baseStyle"):
            break
        current = current.baseStyle()
        if current is None:
            break
    return chain


settings = QgsSettings()
selected_theme = str(settings.value("UI/UITheme", ""))
style_sheet = QApplication.instance().styleSheet()
chain = _style_chain()
qlementine_active = any(
    "qlementine" in f"{item['class']} {item['name']}".casefold()
    for item in chain
)
qlementine_available = any(
    "qlementine" in key.casefold() for key in QStyleFactory.keys()
)
result = {
    "passed": (
        selected_theme == THEME_NAME
        and "QGISPlus Material" in style_sheet
        and "QgsLayerTreeView" in style_sheet
        and len(style_sheet) > 2_000
        and THEME_NAME in QgsApplication.uiThemes()
        and not qlementine_active
        and not qlementine_available
    ),
    "selected_theme": selected_theme,
    "stylesheet_length": len(style_sheet),
    "has_material_marker": "QGISPlus Material" in style_sheet,
    "has_qgis_selectors": "QgsLayerTreeView" in style_sheet,
    "style_chain": chain,
    "style_keys": QStyleFactory.keys(),
    "pkg_data_path": QgsApplication.pkgDataPath(),
    "default_themes_folder": QgsApplication.defaultThemesFolder(),
    "user_themes_folder": QgsApplication.userThemesFolder(),
    "registered_themes": QgsApplication.uiThemes(),
    "library_paths": QCoreApplication.libraryPaths(),
}

output = os.environ.get("QGISPLUS_THEME_PROBE_OUTPUT", "")
if output:
    Path(output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
print("QGISPLUS_THEME_PROBE=" + json.dumps(result, ensure_ascii=False), flush=True)


def _finish_probe() -> None:
    manager = QgsApplication.taskManager()
    manager.cancelAll()
    for task in manager.tasks():
        task.waitForFinished(15_000)
    QCoreApplication.exit(0 if result["passed"] else 23)


QTimer.singleShot(1_500, _finish_probe)
