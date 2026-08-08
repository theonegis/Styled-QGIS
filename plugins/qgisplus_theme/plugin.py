"""Register the bundled QSS directory as a native QGIS UI theme."""

from __future__ import annotations

from pathlib import Path

from qgis.core import QgsApplication, QgsSettings


THEME_NAME = "QGISPlus Material"


class QGISPlusThemePlugin:
    """A deliberately small theme registrar with no widgets or event filters."""

    def __init__(self, iface) -> None:
        self._iface = iface

    def initGui(self) -> None:
        # QGIS scans themes before Python plugins are loaded. The packaged theme
        # therefore needs one explicit registry entry before it can be selected.
        theme_directory = Path(QgsApplication.defaultThemesFolder()) / THEME_NAME
        if not (theme_directory / "style.qss").is_file():
            print(f"QGIS+ theme is missing: {theme_directory}", flush=True)
            return

        registry = QgsApplication.applicationThemeRegistry()
        registry.addTheme(THEME_NAME, str(theme_directory))

        requested_theme = str(
            QgsSettings().value("UI/UITheme", THEME_NAME)
        )
        if requested_theme == THEME_NAME:
            QgsApplication.setUITheme(THEME_NAME)

    def unload(self) -> None:
        """The registry entry may safely live until QGIS exits."""
