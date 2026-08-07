# QGIS+

QGIS+ 是一个面向 Windows 与 macOS 的 QGIS 外观增强发行工程。它跟踪最新
稳定版 [QGIS](https://github.com/qgis/QGIS) 和
[Qlementine](https://github.com/oclero/qlementine)，将 Qlementine 编译为标准
Qt `QStylePlugin`，再与 QGIS 官方二进制安装包组合。QGIS+ 启动器会默认启用
Qlementine，但不修改 QGIS 的地图、插件、Processing 或数据处理代码。

本项目不是 QGIS 或 Qlementine 的官方发行版。

## 构建产物

GitHub Actions 默认生成三个可安装包：

- Windows x64 离线安装包（`.exe`）；
- macOS Intel 安装映像（`.dmg`），最低 macOS Monterey 12；
- macOS Apple Silicon 安装映像（`.dmg`），最低 macOS Monterey 12。

Linux 不打包 Qlementine 版本。Ubuntu、Fedora 和 CachyOS 用户可以安装发行版
提供的 QGIS，并使用 Kvantum 统一 Qt Widgets 外观。

## 为什么改用官方二进制重打包

旧工作流会在每个平台重新编译完整 QGIS。macOS Intel 冷构建仅依赖准备就需要
约 5 小时 36 分钟，随后触及 GitHub 托管 Runner 单 Job 的 6 小时上限，因此
即使没有任何人手动操作也会被平台取消。

QGIS+ 的 Style 插件没有链接 QGIS C++ 库，只依赖 Qt 6 和 Qlementine。重新编译
完整 QGIS 并不能提高样式插件的兼容性，因此当前架构改为：

```text
GitHub Releases API ──解析版本──┐
                               ├─> 官方 QGIS MSI / DMG ──SHA-256 校验──┐
Qlementine Release ──编译插件──┘                                      │
                                                                      ├─> EXE / DMG
原生 QGIS+ 启动器 ──设置 Qlementine 默认样式───────────────────────────┘
```

Windows 对官方 MSI 执行 administrative extraction，把 Win32 启动器与
`qgisplusstyle.dll` 放入运行时，再由 Qt Installer Framework 生成离线 EXE。
macOS 创建一个轻量的外层 `QGIS+.app`，内部保留未经修改的官方 `QGIS.app`，
样式插件和原生启动器位于外层 App 中。

这使主要耗时从“编译整个 QGIS 及其数百个依赖”变成“下载官方安装包、编译一个
小插件并重新打包”。

## 默认样式与原生样式

适配器位于 `src/QlementineStylePlugin.*`，向 `QStyleFactory` 注册
`Qlementine`。启动器在 QGIS 初始化前设置 `QT_STYLE_OVERRIDE=Qlementine`，
并传递 `-style Qlementine`，因此第一次启动和已有用户配置都使用同一主题。

排查第三方插件兼容性时，可以临时使用原生样式：

```bash
# macOS
/Applications/QGIS+.app/Contents/MacOS/QGISPlusLauncher --native-style
```

Windows 可在命令提示符中执行：

```powershell
"C:\Program Files\QGIS+\QGIS+.exe" --native-style
```

## Release 与版本解析

`scripts/resolve_versions.py` 从 GitHub Releases API 中：

- 选择最高稳定 `final-4_x_y` QGIS Release；
- 选择最高稳定 `vX.Y.Z` Qlementine Release；
- 对 `v4.2.1` 或 `v4.2.1-r16` 这类发布标签固定 QGIS 版本。

随后 `scripts/resolve_binary_packages.py` 将 QGIS 版本映射到 QGIS 官方下载服务器
上的 Windows MSI 和 macOS DMG。安装包由 `scripts/download_verified.py` 使用官方
`.sha256sum` 文件校验，校验不通过的缓存或下载会被删除。

查看当前解析结果：

```bash
python3 scripts/resolve_versions.py
python3 scripts/resolve_binary_packages.py --qgis-version 4.2.1
```

## 缓存与失败回退

Actions 缓存以下可复用内容：

- Qt 6.8.3 SDK；
- Qt Installer Framework 4.7；
- QGIS 官方 MSI/DMG。

缓存只是加速项。每次使用前都会检查关键文件，官方安装包还会重新计算
SHA-256。缓存未命中、恢复失败、内容不完整或校验错误时，工作流会删除无效内容
并重新下载，而不是让缓存成为构建的单点故障。

矩阵使用 `fail-fast: false`：某个平台失败时，其他平台仍会完成并上传各自产物，
便于独立诊断，也不会丢失已经成功的平台包。Release 仍要求三个目标平台全部
成功，因此不会发布残缺版本。工作流没有调用 `gh run cancel`，且并发策略为
`cancel-in-progress: false`，所以新提交也不会取消已经开始的旧构建。

Windows 固定使用 `windows-2022` 与 Visual Studio 17 2022 x64 生成器，和
`win64_msvc2022_64` Qt SDK 保持一致，避免 Runner `PATH` 中的 MinGW 被 Ninja
自动误选。

## 本地开发与检查

项目要求 CMake 3.25、C++20、Qt 6.8、Ninja 和可用的 C++ 编译器。仅构建样式
插件与当前平台启动器：

```bash
git clone https://github.com/oclero/qlementine.git upstream/qlementine
git -C upstream/qlementine checkout v1.4.2

cmake -S . -B build-style -G Ninja \
  -D CMAKE_BUILD_TYPE=Release \
  -D CMAKE_PREFIX_PATH=/path/to/Qt/6.8.x \
  -D QGISPLUS_QLEMENTINE_SOURCE_DIR="$PWD/upstream/qlementine"
cmake --build build-style --parallel 2
ctest --test-dir build-style --output-on-failure
```

也可以让 CMake 自动获取 `QGISPLUS_QLEMENTINE_TAG` 指定的 Qlementine：

```bash
bash scripts/build_style.sh
```

运行不下载 QGIS 的本地预检：

```bash
bash scripts/preflight.sh
```

预检包括 Bash/Python 语法、Actions YAML、脚本单元测试和 Git 空白错误。完整 MSI
解包、DMG 挂载和最终安装启动仍需分别在 Windows 与 macOS Runner 上验证。

## 触发 Actions

普通三平台构建只生成 Artifacts：

```bash
gh workflow run build.yml \
  --repo theonegis/Styled-QGIS \
  --ref main \
  -f build_windows=true \
  -f build_macos_intel=true \
  -f build_macos_arm64=true
```

指定 `release_tag` 时，三个包全部成功后自动创建或更新 GitHub Release：

```bash
gh workflow run build.yml \
  --repo theonegis/Styled-QGIS \
  --ref main \
  -f release_tag=v4.2.1-r16 \
  -f build_windows=true \
  -f build_macos_intel=true \
  -f build_macos_arm64=true
```

发布时不要关闭任一平台；Release 校验会要求一个 Windows EXE、一个 Intel DMG
和一个 Apple Silicon DMG。

## 安全与签名说明

- Windows QGIS 主体来自 QGIS 官方 MSI，但外层 QGIS+ 安装器和样式插件尚未使用
  项目的 Authenticode 证书签名。
- macOS 内层官方 QGIS.app 保持不变；外层 QGIS+.app 使用 ad-hoc 签名，DMG 未
  notarize。公开分发前应配置 Developer ID Application 签名和 Apple 公证。
- `--native-style` 是主题导致启动问题时的恢复入口。

## 目录结构

```text
.
├── .github/workflows/
│   ├── build.yml                    # 官方二进制重打包与 Release
│   └── check.yml                    # 快速集成检查
├── packaging/
│   ├── ifw/                         # Windows QtIFW 元数据
│   ├── macos/                       # macOS 外层 App 与启动器
│   └── windows/                     # Windows 原生启动器
├── scripts/
│   ├── download_verified.py         # 下载与 SHA-256 校验
│   ├── extract_official_macos.sh    # 从官方 DMG 提取 QGIS.app
│   ├── package_macos_binary.sh      # 生成架构专用 DMG
│   ├── prepare_ifw_package.py       # 生成 QtIFW 元数据
│   ├── resolve_binary_packages.py   # 官方安装包 URL
│   ├── resolve_package_matrix.py    # 三平台构建矩阵
│   ├── resolve_versions.py          # 上游 Release 解析
│   └── stage_windows_binary.py      # Windows 运行时注入
├── src/                             # Qlementine QStylePlugin 适配器
└── tests/                           # 无网络单元测试
```

## 许可证

本仓库的 QGIS+ overlay 与集成代码采用 GPL-2.0-or-later，见 [LICENSE](LICENSE)。
QGIS 本身采用 GPL-2.0-or-later，Qlementine 采用 MIT License，Qt 和随官方 QGIS
分发的第三方组件保留各自许可证。Release 应明确列出对应的 QGIS/Qlementine
版本及源代码地址，并保留官方安装包中的许可证文件。
