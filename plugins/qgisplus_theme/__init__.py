"""QGIS+ theme registration plugin."""

from .plugin import QGISPlusThemePlugin


def classFactory(iface):
    """Create the plugin instance through QGIS' standard plugin loader."""
    return QGISPlusThemePlugin(iface)
