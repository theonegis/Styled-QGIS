# QGIS+

QGIS+ 是一个独立的 QGIS 桌面发行构建工程。它自动解析并拉取最新稳定版
[QGIS](https://github.com/qgis/QGIS) 与
[Qlementine](https://github.com/oclero/qlementine)，把 Qlementine 编译为标准
Qt `QStylePlugin`，并在没有用户自定义 Style 时将其设为 QGIS 的默认界面
样式。

本工程不属于 QGIS 官方项目，也不是 Qlementine 官方发行版。

## 构建产物

GitHub Actions 默认构建：

- macOS Intel（x86_64）DMG；
- macOS Apple Silicon（arm64）DMG；
- Windows x64 Qt Installer Framework 离线安装包（`.exe`）。

Linux 不构建 Qlementine 版本。Linux 用户可直接使用发行版提供的 QGIS，
并通过 Kvantum 或桌面 Qt Style 统一外观。

工作流每周一自动检查上游，也可在 Actions 页面手动运行。普通运行的结果
保存在 Actions Artifacts；推送本工程的 `v*` 标签时，三个安装包还会自动
上传到对应的 GitHub Release。

> macOS CI 产出的 DMG 默认未签名、未公证。公开分发前，需要配置 Apple
> Developer ID、签名和 notarization；否则 Gatekeeper 会提示来源未知。

## 为什么不是简单的 QSS

Qlementine 是完整的 `QStyle` C++ 实现，而不是一份 QSS。Qt 官方支持通过
`QStylePlugin` 将自定义样式动态提供给现有应用。QGIS 本身又使用
`QgsAppStyle` 代理层修正复杂控件行为，所以本工程采用：

```text
QGIS Widgets
    ↓
QgsAppStyle（保留 QGIS 自身兼容修正）
    ↓
QlementineStyle（现代控件绘制、尺寸、动画和 Palette）
```

不直接在启动后调用 `QApplication::setStyle(new QlementineStyle)`，因为那样
会绕过 `QgsAppStyle`，更容易让属性表、停靠面板和 Processing 对话框出现
细节回归。

## 自动跟踪 Release

`scripts/resolve_versions.py` 通过 GitHub Releases API 解析版本：

- QGIS 只选择稳定的 `final-4_x_y`；
- Qlementine 只选择稳定的 `vX.Y.Z`；
- 两者均按语义版本号取最大值，不依赖发布时间。

不能直接使用 GitHub `/releases/latest`：QGIS 最新版和 LTR 经常在同一天
发布，当前接口可能把发布时间晚一秒的 3.x LTR 当成 latest，而不是版本号
更高的 QGIS 4.x。

手动查看当前解析结果：

```bash
python3 scripts/resolve_versions.py
```

准备完整、已打补丁的上游源码：

```bash
python3 scripts/prepare_source.py --output upstream
```

脚本执行以下操作：

1. 浅克隆选中的 QGIS Release；
2. 浅克隆选中的 Qlementine Release；
3. 对 QGIS 应用两处带锚点校验的幂等修改；
4. 写出 `upstream/versions.json`，便于审计和复现。

如果未来 QGIS 修改了相关初始化代码，补丁会明确失败，而不会模糊匹配后
继续生成一个默认样式失效的安装包。

## 样式接入和默认值

适配器位于 `src/QlementineStylePlugin.*`，向 `QStyleFactory` 注册
`Qlementine` key。构建 QGIS 时，它和 QGIS 使用同一套 vcpkg Qt，因此避免
Qt 插件 ABI、编译器和运行库不一致。

QGIS 源码补丁只负责：

- 在 QGIS 自己完成 UI Theme/Adwaita 回退判断后选择 Qlementine；
- 仅当用户没有保存其他 Style 时应用默认值；
- 插件不存在时安全回退到 QGIS 原有 Style；
- 在安装阶段把插件放入 macOS `Contents/PlugIns/styles`，以及 Windows
  的 Qt plugins 目录；
- Windows 使用 Qt Installer Framework 生成可交互安装、卸载的离线
  `.exe`，不发布 ZIP。

用户随后在 QGIS 设置中选择其他 Style 时，该选择优先于 QGIS+ 默认值。

## 本地只编译样式适配器

要求：

- CMake 3.25+；
- Ninja；
- Qt 6.8+ 的 Core、Gui、Svg、Widgets；
- C++20 编译器。

macOS：

```bash
./scripts/build_style.sh
```

Windows PowerShell：

```powershell
.\scripts\build_style.ps1
```

默认使用 Qlementine `v1.4.2`。本地临时指定其他版本：

```bash
QLEMENTINE_TAG=v1.4.2 ./scripts/build_style.sh
```

只编译适配器主要用于开发和冒烟测试；不要把它直接复制到使用另一套 Qt
构建的 QGIS 中。正式包始终由 `build.yml` 在 QGIS 的 vcpkg 环境内编译。

## GitHub Actions

`.github/workflows/check.yml` 是快速检查：

- Python 单元测试；
- 最新 Release 解析；
- 在最新 QGIS 4.x 源码上验证补丁锚点。

`.github/workflows/build.yml` 是完整发行构建，主要步骤为：

1. 解析上游稳定版本；
2. 准备并修补 QGIS；
3. Windows 先在独立 Job 中预热 Qt6/vcpkg 二进制依赖缓存，再由正式编译
   Job 恢复缓存；macOS 直接使用 QGIS 官方 Qt6/vcpkg 依赖配置；
4. 用同一 Qt 编译 Qlementine Style 插件并运行发现测试；
5. 完整编译 QGIS；
6. 安装到独立的运行时暂存目录并验证关键程序与 Style 插件；
7. Windows 编译 Job 上传暂存运行时，由独立 Job 生成 QtIFW 离线 EXE；
8. 对 Windows 安装包执行静默安装、命令行启动和卸载测试；
9. 对 macOS App 执行无界面启动检查后生成分架构 DMG。

完整 QGIS 编译通常需要数小时。Windows 冷缓存下的 330 个 vcpkg 包无法稳定
地在单个 GitHub-hosted runner 时限内完成，因此 Windows 使用三阶段流水线：
依赖预热、QGIS 正式编译、QtIFW 打包。预热阶段即使达到时间上限，也会保存
已经完成的二进制包；正式编译阶段在同一次工作流中自动恢复并继续，不再要求
用户手动重跑。Windows 的源码、vcpkg、Python `TEMP/TMP` 和缓存统一位于
runner 的 `D:` 工作盘，避免 Python Versioneer 跨盘计算相对路径失败。如果
安装器阶段失败，可以仅重跑失败的打包 Job，复用同一次运行已上传的暂存运行时。

macOS 显式关闭上游用于开发阶段生成 QScintilla API/PAP 文件的
`WITH_QSCIAPI`。这不会关闭 Python、PyQGIS 或 Processing，可避免 vcpkg
Python 在生成 PAP 时同时加载多个 Qt6Core 兼容名导致的构建期崩溃。

## 目录

```text
.
├── CMakeLists.txt                  # QStylePlugin 独立构建
├── src/                            # 极薄的 Qlementine 插件适配层
├── scripts/
│   ├── resolve_versions.py         # 稳定 Release 解析
│   ├── prepare_source.py           # 拉取上游并生成可构建源码
│   ├── apply_qgis_patch.py         # 幂等、锚点校验的 QGIS 补丁
│   ├── configure_windows_qgis.sh    # Windows 两阶段共用的 QGIS 配置参数
│   └── prepare_ifw_package.py      # 生成并校验 Windows QtIFW 元数据
├── packaging/ifw/                  # Windows 安装器组件脚本
├── tests/                          # 版本选择、补丁和插件发现测试
└── .github/workflows/
    ├── check.yml                   # 快速集成检查
    └── build.yml                   # Windows/macOS 完整发行构建
```

## 许可与商标

- 本工程的适配和集成代码采用 GPL-2.0-or-later；
- QGIS 继续遵循其 GPL 许可证；
- Qlementine 继续遵循 MIT License。

修改后的完整 QGIS 二进制仍必须按 GPL 提供对应源码和许可证。`QGIS` 名称
与标识还涉及 QGIS 项目的品牌规范；公开发行前应改用清晰的衍生发行名称与
图标，并明确说明“非 QGIS 官方版本”。
