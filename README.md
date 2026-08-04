# QGIS+

QGIS+ 是一个独立的 QGIS 桌面发行构建工程。它自动解析并拉取最新稳定版
[QGIS](https://github.com/qgis/QGIS) 与
[Qlementine](https://github.com/oclero/qlementine)，把 Qlementine 编译为标准
Qt `QStylePlugin`，并在没有用户自定义 Style 时将其设为 QGIS 的默认界面
样式。

本工程不属于 QGIS 官方项目，也不是 Qlementine 官方发行版。

## 构建产物

GitHub Actions 默认构建：

- macOS Intel（x86_64）DMG，最低支持 macOS Monterey 12；
- macOS Apple Silicon（arm64）DMG，最低支持 macOS Monterey 12；
- Windows x64 Qt Installer Framework 离线安装包（`.exe`）。

Linux 不构建 Qlementine 版本。Linux 用户可直接使用发行版提供的 QGIS，
并通过 Kvantum 或桌面 Qt Style 统一外观。

工作流每周一自动检查上游，也可在 Actions 页面手动运行。普通运行会跟踪
最新稳定版本，结果保存在 Actions Artifacts；推送形如 `v4.2.1` 或
`v4.2.1-r1` 的标签时，构建固定使用对应的 QGIS 版本，三个安装包还会自动
上传到同名 GitHub Release，避免 Release 标签与安装包版本不一致。

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
- 标签构建从 `v4.2.1[-rN]` 固定出 QGIS `final-4_2_1`，手动和定时构建
  才自动跟踪最新 QGIS 4.x。

不能直接使用 GitHub `/releases/latest`：QGIS 最新版和 LTR 经常在同一天
发布，当前接口可能把发布时间晚一秒的 3.x LTR 当成 latest，而不是版本号
更高的 QGIS 4.x。

手动查看当前解析结果：

```bash
python3 scripts/resolve_versions.py
```

模拟标签构建并核对固定版本：

```bash
python3 scripts/resolve_versions.py --build-tag v4.2.1-r1
```

准备完整、已打补丁的上游源码：

```bash
python3 scripts/prepare_source.py --output upstream
```

脚本执行以下操作：

1. 浅克隆选中的 QGIS Release；
2. 浅克隆选中的 Qlementine Release；
3. 对 QGIS 应用带锚点校验的幂等修改，包括默认 Style、安装目录、
   macOS 12 triplet、SIP 启动脚本和 Windows Fortran 配置；
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

- `scripts/preflight.sh` 统一执行 Bash/Python/YAML 静态检查、Python 单元测试
  和 `git diff --check`；提交前可在本地运行同一命令；
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

Windows 与 macOS 都把直接依赖拆为 `base`、`geo`、`python`、`qt` 四个并行
分片。分片内的 vcpkg 安装会在保留现有 buildtree 和二进制缓存的前提下最多
尝试三次，以承受 GitHub Runner 的短时 DNS/下载故障。失败分片会上传已经生成
的部分缓存；在同一 Actions 运行中选择“重新运行失败的任务”时，会先恢复这些
缓存再继续。恢复缓存与本次新缓存使用独立目录：缓存不存在或下载失败时直接从
源码构建；缓存存在但导致安装失败时，会自动禁用它、重置本次安装状态并从源码
重新构建，缓存故障不会成为构建的硬依赖。成功和失败分片的依赖归档均保留 7 天，
避免稍晚重跑时已失去可恢复状态。

依赖安装和正式 CMake 配置都由无输出看门狗保护：子进程连续 30 分钟没有任何
输出时，只终止该进程树并返回可识别的超时状态，而不是等待整项 Job 达到数小时
上限。重试会保留已经生成的 binary cache 和 buildtree；若卡住时启用了 vcpkg
公共 asset cache，则自动绕过该缓存并改从上游权威源下载。正常编译仍可持续数
小时，只有连续无输出才触发恢复流程。

对于已经由构建日志和 PyPI 元数据确认的上游 Python 端口缺陷，工程使用受
registry baseline 保护的 overlay 显式修复依赖图：`py-libpysal` 补充
`py-beautifulsoup4`，`py-referencing` 补充 `py-typing-extensions`，
`py-rasterio` 补充 `py-attrs`、`py-pyparsing` 和本工程锁定的 `py-cligj`。
这些依赖会进入 vcpkg ABI 哈希，不依赖分片的偶然安装顺序。

依赖矩阵使用 fail-fast；任一分片或后续平台编译、打包步骤失败时，工作流会
使用仅限 Actions 的 `GITHUB_TOKEN` 取消整个运行。因此一个平台已经确认失败
后，其他 Windows/macOS Runner 不会继续占用数小时。失败 Job 会先上传其部分
依赖缓存或诊断文件，再发出全局取消请求，避免取消动作本身丢失排错与续跑材料。

### 离线依赖审计与正式编译

持续从临时 Runner 下载和现场构建所有依赖，只能固定“版本”，不能固定
“环境”。本工程将可靠构建拆为两个明确阶段：

1. **联网制备阶段**：在目标平台上准备已打补丁源码、vcpkg registry、源码
   asset cache 和完整 binary cache；该阶段允许访问上游，但不是发布编译。
2. **离线验证与编译阶段**：只读取上述平台依赖包，vcpkg 同时使用
   `--only-binarycaching`、`--no-downloads` 和 `x-block-origin`。任何缺失归档
   会立即失败，绝不会临时访问源站或悄悄退回数小时源码构建。

`packaging/python-runtime-lock.json` 保存 QGIS 4.2.1 锁定闭包中 85 个 Python
端口的 PyPI 运行时元数据。更新 QGIS/Python registry 时，先运行
`scripts/audit_python_runtime_dependencies.py --refresh` 更新一次；平时审计
直接读取该锁，不访问 PyPI。针对确认过的上游端口问题，本工程使用带 registry
baseline 防护的 overlay 明确补上依赖边，而不是依赖安装顺序。

平台二进制缓存制备完成后，可在断网前执行以下验证（`--binary-cache` 可重复
提供四个分片目录）：

```bash
python3 scripts/verify_offline_vcpkg.py \
  --vcpkg /absolute/path/to/vcpkg \
  --manifest upstream/QGIS/vcpkg/vcpkg.json \
  --triplet arm64-osx-dynamic-release \
  --binary-cache /absolute/path/to/binary-cache \
  --registries-cache /absolute/path/to/registries \
  --work-dir build-offline-verify \
  --feature recommended-features --feature auth \
  --feature bindings --feature exiv2 --feature gui \
  --feature proj-data --feature qtpositioning --feature sfcgal
```

只有该命令对目标 triplet 的四个分片全部成功，依赖包才可标记为可发布输入。
Windows x64、macOS Intel 和 macOS Apple Silicon 的缓存 ABI 不同，必须各制备
一份；它们可以在本机、虚拟机或自托管 Runner 上生成，不能跨平台混用。

验证通过后，正式配置 QGIS 时设置 `QGISPLUS_OFFLINE=1`，并传入仅含本地
`files` 源的 `VCPKG_BINARY_SOURCES`、带 `x-block-origin` 的
`X_VCPKG_ASSET_SOURCES` 及本地 `X_VCPKG_REGISTRIES_CACHE`。Windows 和 macOS
配置脚本会自动加入 `--only-binarycaching` 与 `--no-downloads`；任一离线变量
缺失、二进制源不是本地目录或没有阻断源站时，会在 CMake 开始前退出。这样
“缓存没命中就联网重编”只允许出现在联网制备阶段，发布编译不会发生该退化。

本工程定位是二维桌面 GIS 美化版，Windows 和 macOS 均明确关闭 QGIS 3D、
PDAL 点云和 Draco 点云压缩支持，并且不再启用 vcpkg 的 `3d`、`pdal`
features。QGIS 4.2.1 的 `WITH_DRACO` 默认开启，但其 vcpkg manifest 没有声明
Draco，必须与其他三维/点云功能一起显式关闭。这样不仅减少 QGIS 自身的相关
源码编译，还从依赖图中去掉 Qt3D、PDAL 与 Draco；二维地图、矢量、栅格、
PyQGIS 和 Processing 不受影响。如未来确实需要三维场景或点云，再将这些选项
和对应依赖 feature 成对恢复，避免只启用一半造成配置错误。

Windows triplet 会显式设置 vcpkg 当前版本要求的
`VCPKG_PROVIDED_FORTRAN=ON`，并屏蔽 hosted runner 上可能被旧版 CMake
逻辑误选、但无法完成 LAPACK 探测的 LLVM Flang。因此新旧 vcpkg 都会使用
其自带的 MinGW gfortran。该路径同时通过 `vcpkg-gfortran` 安装所需运行时
DLL，避免“依赖编译通过、安装后的程序却缺少 Fortran DLL”的隐患。缓存的
恢复与保存只作为加速项，服务临时不可用不会阻断正式构建；正式配置完成后
还会再次保存完整缓存。

当前 Actions 的 macOS vcpkg 二进制包只在同一次工作流中通过文件 artifact
传递，不依赖 GitHub Packages/NuGet 的写入权限。跨运行复用由联网制备阶段
导出的平台依赖包负责；离线正式编译只读该依赖包。

macOS 不再调用会跟随 `latest` 漂移的上游 `vcpkg-init.sh`，而是从所选 QGIS
Release 的 `vcpkg.json` 读取 40 位 baseline，检出并启动同一提交的 vcpkg。
下载带三次有限重试；工具版本、端口版本和 ABI 哈希因此可以随标签复现。

Intel 与 Apple Silicon 均把 QGIS 顶层构建和 vcpkg triplet 的最低部署版本
固定为 macOS Monterey 12。只设置 `CMAKE_OSX_DEPLOYMENT_TARGET` 不足以覆盖
QGIS triplet 自带的 10.15/11.0 值，因此源码准备阶段会同时修改两个 triplet，
并在耗时构建开始前进行校验。

macOS Runner 使用系统 Bash 3.2。配置脚本使用始终非空的 CMake 参数数组，并
分别测试联网和离线配置路径，避免 `set -u` 展开空数组时触发
`unbound variable` 并连带取消其他平台。

QGIS 4.2.1 所用 Python registry 的 SIP shebang 修复不是幂等的：对已经使用
`/bin/sh` 的包装器再次处理后，会生成指向工作目录之外的相对路径，最终让
PyQt6 在 `sip-distinfo` 阶段失败。工程通过窄范围 `py-sip` overlay port 在
macOS/Linux 写入相对 `tools/python3` 的可迁移模块包装器；Windows 继续使用
已经验证成功的上游实现。overlay 内容会参与 vcpkg ABI 哈希，因此旧缓存中的
错误 SIP 包不会被复用。
overlay 只对当前已审查的 Python registry baseline 生效；未来 QGIS 更新该
baseline 时，快速检查会要求重新核对 `py-sip`，不会静默固定到旧依赖。

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
│   ├── setup_macos_vcpkg.sh         # 按 QGIS baseline 固定 macOS vcpkg
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
