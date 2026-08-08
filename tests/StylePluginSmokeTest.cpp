// SPDX-License-Identifier: GPL-2.0-or-later

#include <QApplication>
#include <QAbstractItemView>
#include <QByteArray>
#include <QComboBox>
#include <QDir>
#include <QFileInfo>
#include <QMenu>
#include <QMouseEvent>
#include <QPalette>
#include <QPluginLoader>
#include <QStyle>
#include <QStylePlugin>
#include <Qt>

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
    std::unique_ptr<QStyle> style{plugin->create(
        QStringLiteral("Qlementine"))};
    if (!style) {
        std::cerr << "Qlementine plugin could not create its style\n";
        return 4;
    }

    app.setStyle(style.release());

    // QGIS 的 Options 页面包含大量禁用说明文字。Qlementine 上游默认色
    // 与浅灰背景过于接近；适配主题必须提供明确可读的禁用文字颜色。
    const auto disabledText = app.palette().color(
        QPalette::Disabled, QPalette::Text);
    if (disabledText.red() > 160 || disabledText.green() > 160 ||
        disabledText.blue() > 160) {
        std::cerr << "Disabled Qlementine text is too light for QGIS\n";
        return 5;
    }

    // 样式列表的条目带 CheckStateRole，需同时容纳指示器与完整文字。
    // 该检查覆盖曾出现的 “Qlem...” 下拉框截断回归。
    QComboBox comboBox;
    comboBox.addItem(QStringLiteral("macOS"));
    comboBox.addItem(QStringLiteral("Qlementine"));
    comboBox.addItem(QStringLiteral("Windows"));
    comboBox.addItem(QStringLiteral("Fusion"));
    for (auto index = 0; index < comboBox.count(); ++index) {
        comboBox.setItemData(index, Qt::Unchecked, Qt::CheckStateRole);
    }
    comboBox.setItemData(1, Qt::Checked, Qt::CheckStateRole);
    comboBox.setCurrentIndex(1);
    comboBox.resize(96, comboBox.sizeHint().height());
    comboBox.show();
    comboBox.showPopup();
    app.processEvents();
    app.processEvents();

    const auto textWidth = comboBox.fontMetrics().horizontalAdvance(
        QStringLiteral("Qlementine"));
    const auto indicatorWidth = app.style()->pixelMetric(
        QStyle::PM_IndicatorWidth);
    if (comboBox.view()->width() < textWidth + indicatorWidth + 16) {
        std::cerr << "Qlementine ComboBox popup clips item text\n";
        return 6;
    }

    // Qlementine 上游通过吞掉 release、延迟动画、再伪造 release 来点击
    // QMenu。QGIS 的 QgsAppStyle 包装会使这条链路失效。真实 press/release
    // 必须直接切换 checkable QAction，覆盖 Panels/Toolbars 菜单回归。
    QMenu menu;
    auto* const checkableAction = menu.addAction(
        QStringLiteral("Layers Panel"));
    checkableAction->setCheckable(true);
    checkableAction->setChecked(false);
    menu.show();
    app.processEvents();

    const auto actionCenter = menu.actionGeometry(checkableAction).center();
    const auto globalCenter = menu.mapToGlobal(actionCenter);
    QMouseEvent press{
        QEvent::MouseButtonPress,
        QPointF{actionCenter},
        QPointF{globalCenter},
        Qt::LeftButton,
        Qt::LeftButton,
        Qt::NoModifier};
    QApplication::sendEvent(&menu, &press);
    QMouseEvent release{
        QEvent::MouseButtonRelease,
        QPointF{actionCenter},
        QPointF{globalCenter},
        Qt::LeftButton,
        Qt::NoButton,
        Qt::NoModifier};
    QApplication::sendEvent(&menu, &release);
    app.processEvents();
    if (!checkableAction->isChecked()) {
        std::cerr << "Qlementine menu did not toggle a checkable action\n";
        return 7;
    }

    return 0;
}
