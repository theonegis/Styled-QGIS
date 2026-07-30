// SPDX-License-Identifier: GPL-2.0-or-later

#include <QApplication>
#include <QStyle>
#include <QStyleFactory>

#include <algorithm>
#include <iostream>
#include <memory>

int main(int argc, char* argv[]) {
    QApplication app(argc, argv);

    const auto keys = QStyleFactory::keys();
    const auto found = std::ranges::any_of(keys, [](const QString& key) {
        return key.compare(QStringLiteral("Qlementine"),
                           Qt::CaseInsensitive) == 0;
    });
    if (!found) {
        std::cerr << "Qlementine was not registered in QStyleFactory\n";
        return 1;
    }

    const std::unique_ptr<QStyle> style{
        QStyleFactory::create(QStringLiteral("Qlementine"))};
    if (!style) {
        std::cerr << "QStyleFactory could not instantiate Qlementine\n";
        return 2;
    }

    return 0;
}

