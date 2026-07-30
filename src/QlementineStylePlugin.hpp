// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <QStylePlugin>

class QlementineStylePlugin final : public QStylePlugin {
    Q_OBJECT
    Q_PLUGIN_METADATA(
        IID "org.qt-project.Qt.QStyleFactoryInterface"
        FILE "qlementinestyle.json"
    )

public:
    [[nodiscard]] QStyle* create(const QString& key) override;
};

