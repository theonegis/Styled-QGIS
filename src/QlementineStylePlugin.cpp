// SPDX-License-Identifier: GPL-2.0-or-later

#include "QlementineStylePlugin.hpp"

#include <oclero/qlementine/style/QlementineStyle.hpp>

#include <QAbstractItemView>
#include <QColor>
#include <QComboBox>
#include <QEvent>
#include <QLayout>
#include <QMenu>
#include <QPalette>
#include <QPointer>
#include <QStyleOptionViewItem>
#include <QTimer>
#include <Qt>

#include <algorithm>

namespace {

class SafeComboPopupFilter final : public QObject {
public:
    SafeComboPopupFilter(QComboBox* comboBox, QAbstractItemView* view,
                         const QStyle* style)
        : QObject{view}, comboBox_{comboBox}, view_{view}, style_{style} {
        view->installEventFilter(this);
        if (auto* popup = view->parentWidget(); popup != nullptr) {
            popup->installEventFilter(this);
        }
    }

protected:
    bool eventFilter(QObject* watched, QEvent* event) override {
        Q_UNUSED(watched)
        if (event->type() == QEvent::Show || event->type() == QEvent::Resize) {
            // 等当前 show/resize 事件完成后再调整，避免 QGIS 的 QgsAppStyle
            // 在 polish 阶段重入 QComboBox::view()。
            QTimer::singleShot(0, this, [this] { updatePopupWidth(); });
        }
        return false;
    }

private:
    void updatePopupWidth() const {
        if (view_.isNull() || style_.isNull()) {
            return;
        }

        const auto spacing = style_->pixelMetric(QStyle::PM_MenuHMargin);
        const auto indicator = style_->pixelMetric(QStyle::PM_IndicatorWidth);
        const auto comboWidth = comboBox_.isNull() ? 0 : comboBox_->width();
        const auto contentWidth = view_->sizeHintForColumn(0);
        const auto requiredWidth = std::max(
            comboWidth,
            contentWidth + indicator + std::max(8, spacing * 2));

        if (requiredWidth <= view_->width()) {
            return;
        }
        view_->setMinimumWidth(requiredWidth);
        view_->resize(requiredWidth, view_->height());
        if (auto* popup = view_->parentWidget(); popup != nullptr) {
            if (popup->layout() != nullptr) {
                popup->layout()->activate();
            }
            popup->adjustSize();
        }
    }

    QPointer<QComboBox> comboBox_;
    QPointer<QAbstractItemView> view_;
    QPointer<const QStyle> style_;
};

QComboBox* findOwningComboBox(QWidget* widget) {
    for (auto* current = widget; current != nullptr;
         current = current->parentWidget()) {
        if (auto* comboBox = qobject_cast<QComboBox*>(current);
            comboBox != nullptr) {
            return comboBox;
        }
    }
    return nullptr;
}

// QGIS 的 QgsLocatorResultsView 会在没有关联 QWidget 的情况下调用
// QStyle::sizeFromContents(CT_ItemViewItem, ...)。Qlementine 1.4.2 在若干
// sizeFromContents 分支中直接解引用 widget，违反 QStyle 接口允许 nullptr
// 的约定并导致启动崩溃。无 widget 时退回 QCommonStyle 的安全尺寸计算；
// 绘制和真实控件仍完整使用 Qlementine。
class QgisCompatibleQlementineStyle final
    : public oclero::qlementine::QlementineStyle {
public:
    QgisCompatibleQlementineStyle() {
        auto qgisTheme = theme();

        // Qlementine 默认禁用文字为 #d4d4d4，在 QGIS 大面积的浅灰/白色
        // 设置页面上对比度过低。保持 Qlementine 的色相与布局，仅把禁用文字
        // 提升到 WCAG AA 正文阈值附近，保证选项说明仍可辨认。
        const QColor readableDisabledText{QStringLiteral("#767676")};
        qgisTheme.secondaryColorDisabled = readableDisabledText;
        qgisTheme.secondaryAlternativeColorDisabled = readableDisabledText;
        qgisTheme.secondaryColorForegroundDisabled = readableDisabledText;
        for (const auto role : {
                 QPalette::Text,
                 QPalette::WindowText,
                 QPalette::PlaceholderText,
                 QPalette::Link,
                 QPalette::LinkVisited,
                 QPalette::BrightText,
                 QPalette::ButtonText,
             }) {
            qgisTheme.palette.setColor(
                QPalette::Disabled, role, readableDisabledText);
        }
        setTheme(qgisTheme);
    }

    QSize sizeFromContents(ContentsType type, const QStyleOption* option,
                           const QSize& contentsSize,
                           const QWidget* widget = nullptr) const override {
        if (widget == nullptr) {
            return QCommonStyle::sizeFromContents(
                type, option, contentsSize, widget);
        }
        return QlementineStyle::sizeFromContents(
            type, option, contentsSize, widget);
    }

    void drawControl(ControlElement element, const QStyleOption* option,
                     QPainter* painter,
                     const QWidget* widget = nullptr) const override {
        if (element == CE_ItemViewItem) {
            if (const auto* item =
                    qstyleoption_cast<const QStyleOptionViewItem*>(option);
                item != nullptr) {
                auto compatibleItem = *item;
                const auto palette = standardPalette();
                const auto selected = item->state.testFlag(State_Selected);
                const auto enabled = item->state.testFlag(State_Enabled);
                const auto group = enabled
                    ? QPalette::Active
                    : QPalette::Disabled;
                const auto role = selected
                    ? QPalette::HighlightedText
                    : QPalette::Text;

                // QGIS 的模型/delegate 可能把原生 Style 的前景色写入 option。
                // 由 Qlementine 绘制时统一使用当前主题对应颜色，避免旧调色板
                // 产生白底白字；这里只改 ItemView 文本，不覆盖数据表的背景色。
                compatibleItem.palette.setColor(
                    group, QPalette::Text, palette.color(group, role));
                QlementineStyle::drawControl(
                    element, &compatibleItem, painter, widget);
                return;
            }
        }
        QlementineStyle::drawControl(element, option, painter, widget);
    }

    void polish(QWidget* widget) override {
        auto* itemView = qobject_cast<QAbstractItemView*>(widget);
        const auto* popup = itemView != nullptr ? itemView->parentWidget() : nullptr;
        const bool isComboPopup = popup != nullptr &&
            popup->inherits("QComboBoxPrivateContainer");

        // Qlementine 的 MenuEventFilter 会吞掉真实 MouseButtonRelease，
        // 播放动画后再向 QMenu 发送一枚人工 release。在 QgsAppStyle 包装下
        // 该事件不会可靠触发 checkable QAction，表现为菜单复选框无法切换。
        // 保留透明圆角窗口属性和 Qlementine 绘制，点击交还 Qt/QGIS 原生逻辑。
        if (auto* menu = qobject_cast<QMenu*>(widget); menu != nullptr) {
            QCommonStyle::polish(widget);
            menu->setBackgroundRole(QPalette::NoRole);
            menu->setAutoFillBackground(false);
            menu->setAttribute(Qt::WA_TranslucentBackground, true);
            menu->setAttribute(Qt::WA_OpaquePaintEvent, false);
            menu->setAttribute(Qt::WA_NoSystemBackground, true);
            menu->setWindowFlag(Qt::FramelessWindowHint, true);
            menu->setWindowFlag(Qt::NoDropShadowWindowHint, true);
            menu->setProperty("_q_windowsDropShadow", false);
            return;
        }

        // Qlementine 的 ComboboxItemViewFilter 在 ChildAdded 期间调用
        // QComboBox::view()。QGIS 的 QgsAppStyle 又会在同一期间 polish 新建
        // 的 popup，二者形成无限递归。跳过 Qlementine 对 ComboBox/popup 的
        // 事件过滤器安装，但保留 Qlementine 的 draw/metric/palette 实现。
        if (auto* comboBox = qobject_cast<QComboBox*>(widget);
            comboBox != nullptr) {
            QCommonStyle::polish(widget);
            comboBox->setSizeAdjustPolicy(QComboBox::AdjustToContents);
            return;
        }
        if (isComboPopup) {
            QCommonStyle::polish(widget);
            new SafeComboPopupFilter(
                findOwningComboBox(widget), itemView, this);
            return;
        }
        QlementineStyle::polish(widget);
    }
};

}  // namespace

QStyle* QlementineStylePlugin::create(const QString& key) {
    if (key.compare(QStringLiteral("Qlementine"), Qt::CaseInsensitive) != 0) {
        return nullptr;
    }

    // 所有权由 QApplication/QgsAppStyle 接管，不在插件对象中保存裸指针。
    return new QgisCompatibleQlementineStyle;
}
