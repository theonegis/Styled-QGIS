// SPDX-License-Identifier: GPL-2.0-or-later

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QPluginLoader>
#include <QStyleFactory>
#include <QStylePlugin>

#include <algorithm>
#include <iostream>

int main(int argc, char* argv[]) {
    QCoreApplication app(argc, argv);

    if (argc != 2) {
        std::cerr << "Expected the style plugin path as the only argument\n";
        return 1;
    }

    const QFileInfo pluginFile{QString::fromLocal8Bit(argv[1])};
    QDir pluginRoot = pluginFile.dir();
    if (!pluginRoot.cdUp()) {
        std::cerr << "Could not resolve the Qt plugin root directory\n";
        return 2;
    }
    QCoreApplication::addLibraryPath(pluginRoot.absolutePath());

    // 直接加载插件即可验证二进制兼容性，无需初始化 macOS QPA 图形后端。
    QPluginLoader loader{pluginFile.absoluteFilePath()};
    if (qobject_cast<QStylePlugin*>(loader.instance()) == nullptr) {
        std::cerr << "Could not load Qlementine style plugin: "
                  << loader.errorString().toStdString() << '\n';
        return 3;
    }

    const auto keys = QStyleFactory::keys();
    const auto found = std::ranges::any_of(keys, [](const QString& key) {
        return key.compare(QStringLiteral("Qlementine"),
                           Qt::CaseInsensitive) == 0;
    });
    if (!found) {
        std::cerr << "Qlementine was not registered in QStyleFactory\n";
        return 4;
    }

    return 0;
}
