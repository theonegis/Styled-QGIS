"""QGIS 内部运行时探针：确认 Qlementine 是最终底层 QStyle。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.PyQt.QtWidgets import QApplication, QStyleFactory
from qgis.core import QgsApplication


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


keys = QStyleFactory.keys()
chain = _style_chain()
has_factory_key = any(key.casefold() == "qlementine" for key in keys)
uses_qlementine = any(
    "qlementine" in f"{item['class']} {item['name']}".casefold()
    for item in chain
)
result = {
    "passed": has_factory_key and uses_qlementine,
    "keys": keys,
    "style_chain": chain,
    "library_paths": QCoreApplication.libraryPaths(),
}

output = os.environ.get("QGISPLUS_STYLE_PROBE_OUTPUT", "")
if output:
    Path(output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
print("QGISPLUS_STYLE_PROBE=" + json.dumps(result, ensure_ascii=False), flush=True)

def _finish_probe() -> None:
    # QGIS 首次启动可能并行下载缺失字体。立即退出会让认证/网络任务与
    # QgsApplication 析构并发，产生与 Style 无关的 teardown 崩溃。
    manager = QgsApplication.taskManager()
    manager.cancelAll()
    for task in manager.tasks():
        task.waitForFinished(15_000)
    QCoreApplication.exit(0 if result["passed"] else 23)


QTimer.singleShot(1_500, _finish_probe)
