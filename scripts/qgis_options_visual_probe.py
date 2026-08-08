"""打开 QGIS Options 并检查 QSS 可读性、菜单交互与主题下拉框。"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPointF, QTimer, Qt
from qgis.PyQt.QtGui import QColor, QMouseEvent, QPalette
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QMenu,
)
from qgis.core import QgsApplication
from qgis.utils import iface


def _color(color: QColor) -> str:
    return color.name(QColor.NameFormat.HexArgb)


def _palette(widget) -> dict[str, str]:
    palette = widget.palette()
    group = QPalette.ColorGroup.Active
    role = QPalette.ColorRole
    return {
        "text": _color(palette.color(group, role.Text)),
        "base": _color(palette.color(group, role.Base)),
        "window_text": _color(
            palette.color(group, role.WindowText)
        ),
        "window": _color(palette.color(group, role.Window)),
        "highlighted_text": _color(
            palette.color(group, role.HighlightedText)
        ),
        "highlight": _color(
            palette.color(group, role.Highlight)
        ),
    }


def _relative_luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        component = value / 255.0
        return (
            component / 12.92
            if component <= 0.04045
            else ((component + 0.055) / 1.055) ** 2.4
        )

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def _contrast(first: QColor, second: QColor) -> float:
    light = max(_relative_luminance(first), _relative_luminance(second))
    dark = min(_relative_luminance(first), _relative_luminance(second))
    return (light + 0.05) / (dark + 0.05)


def _finish(exit_code: int) -> None:
    manager = QgsApplication.taskManager()
    manager.cancelAll()
    for task in manager.tasks():
        task.waitForFinished(15_000)
    QCoreApplication.exit(exit_code)


def _capture() -> None:
    try:
        _capture_impl()
    except Exception:  # pragma: no cover - 仅供真实 QGIS 运行时诊断
        error = traceback.format_exc()
        result_path = Path(
            os.environ.get(
                "QGISPLUS_OPTIONS_PROBE_OUTPUT",
                "/tmp/qgisplus-options-probe.json",
            )
        )
        result_path.with_suffix(".error.log").write_text(
            error, encoding="utf-8"
        )
        print(error, flush=True)
        _finish(32)


def _capture_impl() -> None:
    QApplication.processEvents()
    dialogs = [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, QDialog)
        and widget.findChild(QComboBox, "cmbStyle") is not None
    ]
    if not dialogs:
        print("QGISPLUS_OPTIONS_PROBE=no-options-dialog", flush=True)
        _finish(31)
        return

    dialog = dialogs[0]
    menu = QMenu(dialog)
    checkable_action = menu.addAction("QGIS+ checkable action probe")
    checkable_action.setCheckable(True)
    checkable_action.setChecked(False)
    menu.show()
    QApplication.processEvents()
    action_center = menu.actionGeometry(checkable_action).center()
    global_center = menu.mapToGlobal(action_center)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(action_center),
        QPointF(global_center),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(menu, press)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(action_center),
        QPointF(global_center),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(menu, release)
    QApplication.processEvents()
    menu_checkable_toggle = checkable_action.isChecked()

    style_combo = dialog.findChild(QComboBox, "cmbStyle")
    if style_combo is None:
        raise RuntimeError("QGIS Style ComboBox was not found")
    style_combo.showPopup()
    QApplication.processEvents()
    QApplication.processEvents()

    style_view = style_combo.view()
    style_popup = style_view.parentWidget()
    style_content_width = max(
        (
            style_combo.fontMetrics().horizontalAdvance(
                style_combo.itemText(index)
            )
            for index in range(style_combo.count())
        ),
        default=0,
    )
    style_popup_info = {
        "combo_width": style_combo.width(),
        "view_width": style_view.width(),
        "content_width": style_content_width,
        "items": [
            style_combo.itemText(index)
            for index in range(style_combo.count())
        ],
    }
    # 下拉框隐藏后 Qt 可能只截到空白；在可见状态保存快照。
    style_popup_capture = style_popup.grab()
    style_combo.hidePopup()

    theme_combo = dialog.findChild(QComboBox, "cmbUITheme")
    if theme_combo is None:
        raise RuntimeError("QGIS UI Theme ComboBox was not found")
    theme_combo.showPopup()
    QApplication.processEvents()
    QApplication.processEvents()
    theme_view = theme_combo.view()
    theme_popup = theme_view.parentWidget()
    theme_content_width = max(
        (
            theme_combo.fontMetrics().horizontalAdvance(
                theme_combo.itemText(index)
            )
            for index in range(theme_combo.count())
        ),
        default=0,
    )
    theme_popup_info = {
        "combo_width": theme_combo.width(),
        "view_width": theme_view.width(),
        "content_width": theme_content_width,
        "items": [
            theme_combo.itemText(index)
            for index in range(theme_combo.count())
        ],
    }
    theme_popup_capture = theme_popup.grab()

    item_views = []
    for view in dialog.findChildren(QAbstractItemView):
        if not view.isVisible():
            continue
        item_views.append(
            {
                "class": view.metaObject().className(),
                "name": view.objectName(),
                "visible": view.isVisible(),
                "size": [view.width(), view.height()],
                "palette": _palette(view),
            }
        )

    combo_boxes = []
    for combo in dialog.findChildren(QComboBox):
        if not combo.isVisible():
            continue
        combo_boxes.append(
            {
                "name": combo.objectName(),
                "visible": combo.isVisible(),
                "text": combo.currentText(),
                "size": [combo.width(), combo.height()],
                "content_width": max(
                    (
                        combo.fontMetrics().horizontalAdvance(
                            combo.itemText(index)
                        )
                        for index in range(combo.count())
                    ),
                    default=0,
                ),
                "palette": _palette(combo),
            }
        )

    palette = dialog.palette()
    group = QPalette.ColorGroup.Active
    disabled = QPalette.ColorGroup.Disabled
    role = QPalette.ColorRole
    active_contrast = _contrast(
        palette.color(group, role.Text), palette.color(group, role.Base)
    )
    disabled_contrast = _contrast(
        palette.color(disabled, role.Text),
        palette.color(disabled, role.Window),
    )
    selected_contrast = _contrast(
        palette.color(group, role.HighlightedText),
        palette.color(group, role.Highlight),
    )
    style_popup_has_full_width = (
        style_view.width() >= style_combo.width()
        and style_view.width() >= style_content_width + 32
    )
    theme_popup_has_full_width = (
        theme_view.width() >= theme_combo.width()
        and theme_view.width() >= theme_content_width + 32
    )
    result = {
        "passed": (
            active_contrast >= 4.5
            and disabled_contrast >= 4.0
            and selected_contrast >= 4.5
            and style_popup_has_full_width
            and theme_popup_has_full_width
            and "QGISPlus Material" in theme_popup_info["items"]
            and menu_checkable_toggle
        ),
        "active_text_contrast": round(active_contrast, 3),
        "disabled_text_contrast": round(disabled_contrast, 3),
        "selected_text_contrast": round(selected_contrast, 3),
        "style_popup": style_popup_info,
        "theme_popup": theme_popup_info,
        "menu_checkable_toggle": menu_checkable_toggle,
        "dialog_palette": _palette(dialog),
        "item_views": item_views,
        "combo_boxes": combo_boxes,
    }
    output = Path(
        os.environ.get(
            "QGISPLUS_OPTIONS_PROBE_OUTPUT", "/tmp/qgisplus-options-probe.json"
        )
    )
    screenshot = Path(
        os.environ.get(
            "QGISPLUS_OPTIONS_SCREENSHOT", "/tmp/qgisplus-options-probe.png"
        )
    )
    combo_screenshot = Path(
        os.environ.get(
            "QGISPLUS_COMBO_SCREENSHOT", "/tmp/qgisplus-combo-probe.png"
        )
    )
    theme_combo_screenshot = Path(
        os.environ.get(
            "QGISPLUS_THEME_COMBO_SCREENSHOT",
            "/tmp/qgisplus-theme-combo-probe.png",
        )
    )
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dialog.grab().save(str(screenshot))
    style_popup_capture.save(str(combo_screenshot))
    theme_popup_capture.save(str(theme_combo_screenshot))
    print(
        "QGISPLUS_OPTIONS_PROBE="
        + json.dumps(
            {
                "passed": result["passed"],
                "active_text_contrast": result["active_text_contrast"],
                "disabled_text_contrast": result["disabled_text_contrast"],
                "selected_text_contrast": result["selected_text_contrast"],
                "style_popup": result["style_popup"],
                "theme_popup": result["theme_popup"],
                "menu_checkable_toggle": result["menu_checkable_toggle"],
            }
        ),
        flush=True,
    )
    QTimer.singleShot(500, lambda: _finish(0 if result["passed"] else 33))


def _open_options() -> None:
    # showOptionsDialog() 是同步模态调用；先安排采集任务，等窗口进入自己的
    # 事件循环后再读取控件和截图，避免探针被对话框阻塞。
    capture_timer.start(1_500)
    iface.showOptionsDialog()


app = QApplication.instance()
capture_timer = QTimer(app)
capture_timer.setSingleShot(True)
capture_timer.timeout.connect(_capture)
open_timer = QTimer(app)
open_timer.setSingleShot(True)
open_timer.timeout.connect(_open_options)
open_timer.start(1_500)
