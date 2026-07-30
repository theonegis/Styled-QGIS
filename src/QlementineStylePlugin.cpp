// SPDX-License-Identifier: GPL-2.0-or-later

#include "QlementineStylePlugin.hpp"

#include <oclero/qlementine/style/QlementineStyle.hpp>

#include <Qt>

QStyle* QlementineStylePlugin::create(const QString& key) {
    if (key.compare(QStringLiteral("Qlementine"), Qt::CaseInsensitive) != 0) {
        return nullptr;
    }

    // 所有权由 QApplication/QgsAppStyle 接管，不在插件对象中保存裸指针。
    return new oclero::qlementine::QlementineStyle;
}

