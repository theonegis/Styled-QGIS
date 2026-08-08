# QGIS+

QGIS+ 是面向 Windows 与 macOS 的 QGIS 外观增强发行工程。它自动获取最新稳定版
[QGIS](https://github.com/qgis/QGIS) 官方安装包，加入紧凑的
`QGISPlus Material` UI Theme，再生成可安装的 EXE 和 DMG。

主题基于 [Qt Advanced Stylesheets](https://github.com/githubuser0xFFFF/Qt-Advanced-Stylesheets)
中的 `qt_material` 设计语言，但不加载第三方 `QStylePlugin`，不会改变 QGIS 的地图、
插件、Processing 或控件事件行为。本项目不是 QGIS 官方发行版。

## 主题设计

- 使用 QGIS 原生 UI Theme、QSS、Palette 和 SVG；
- 仅用一个无界面的轻量 Python 插件完成主题注册与启用；
- 使用系统字体、4–5 px 小圆角和紧凑桌面间距；
- 默认以 Fusion 作为稳定的跨平台基础 Style；
- 针对图层树、属性表、消息栏、定位器、数字化浮窗、字段/投影选择器及自绘预览按钮
  提供 QGIS 专用选择器；
- 不覆盖地图画布和自绘预览区域的绘制逻辑。

`main` 为 QSS 版本；最后一个 Qlementine 实现在 `Qlementine` 归档分支。

## 构建产物

GitHub Actions 生成：

- Windows x64 离线安装包（EXE）；
- macOS Intel DMG；
- macOS Apple Silicon DMG。

macOS 最低版本为 Monterey 12。Linux 用户可直接安装发行版 QGIS，并使用 Kvantum
调整界面。

## 架构

```text
QGIS Releases ──解析最新稳定版──> 官方 MSI / DMG ──SHA-256 校验──┐
QGISPlus Material QSS + SVG + 主题注册器 ─────────────────────────┼─> EXE / DMG
C++20 轻量启动器 ──设置默认 UI Theme 与独立 profile──────────────┘
```

主题位于 `themes/QGISPlus Material/`。打包阶段将它复制到 QGIS 原生主题目录，并安装
`plugins/qgisplus_theme/` 注册器，再通过全局设置默认启用。构建不再下载 Qt SDK 或编译
Qlementine，因此不存在 Qt ABI 绑定问题。

## 本地检查

需要 CMake 3.25、C++20 编译器和 Python 3.11：

```bash
cmake -S . -B build -D CMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
python3 -m unittest tests/test_scripts.py
bash scripts/preflight.sh
```

macOS 完整 DMG 仍需提供官方 `QGIS.app`：

```bash
bash scripts/package_macos_binary.sh \
  /path/to/QGIS.app \
  build/launcher/QGISPlusLauncher \
  "$(uname -m)" 4.2.1 dist/QGISPlus-4.2.1-macos.dmg
```

临时禁用自定义主题：

```bash
/Applications/QGIS+.app/Contents/MacOS/QGISPlusLauncher --native-theme
```

## GitHub Actions

构建并在三平台成功后自动发布 Release：

```bash
gh workflow run build.yml \
  --repo theonegis/Styled-QGIS \
  --ref main \
  -f publish_release=true \
  -f build_windows=true \
  -f build_macos_intel=true \
  -f build_macos_arm64=true
```

也可以增加 `-f release_tag=v4.2.1-r18` 指定发布标签。缓存只用于加速，未命中或校验
失败时会重新下载官方安装包。

## 许可证

本仓库的 overlay 代码采用 GPL-2.0-or-later，见 [LICENSE](LICENSE)。QGIS 保留其
GPL-2.0-or-later 许可证。`qt_material` 样式与所用 SVG 采用 BSD 2-Clause License，
归属与许可证见 `third_party/qt_material/` 和主题目录中的 `LICENSE.qt_material`。
