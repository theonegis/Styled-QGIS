// SPDX-License-Identifier: GPL-2.0-or-later

#include <QApplication>
#include <QByteArray>
#include <QDir>
#include <QFileInfo>
#include <QPluginLoader>
#include <QStyle>
#include <QStylePlugin>

#include <iostream>
#include <memory>

int main(int argc, char* argv[]) {
    // CI runner 没有可用显示器；offscreen 仍会初始化字体、调色板等
    // QStyle 所需的 GUI 上下文，同时不会打开窗口。
    qputenv("QT_QPA_PLATFORM", QByteArrayLiteral("offscreen"));
    const QApplication app(argc, argv);

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
    auto* const plugin = qobject_cast<QStylePlugin*>(loader.instance());
    if (plugin == nullptr) {
        std::cerr << "Could not load Qlementine style plugin: "
                  << loader.errorString().toStdString() << '\n';
        return 3;
    }

    // QStyleFactory 会缓存已扫描的插件。Windows 上若先通过 QPluginLoader
    // 显式加载同一个 DLL，工厂缓存不会在当前进程中重新注册该实例。
    // 直接调用 QStylePlugin 接口既验证二进制兼容性，也验证样式确实可创建。
    const std::unique_ptr<QStyle> style{plugin->create(
        QStringLiteral("Qlementine"))};
    if (!style) {
        std::cerr << "Qlementine plugin could not create its style\n";
        return 4;
    }

    return 0;
}
