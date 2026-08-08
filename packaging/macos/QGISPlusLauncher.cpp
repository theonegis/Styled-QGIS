// SPDX-License-Identifier: GPL-2.0-or-later

#include <mach-o/dyld.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

namespace fs = std::filesystem;

[[nodiscard]] fs::path executablePath() {
    std::uint32_t size = 0;
    _NSGetExecutablePath(nullptr, &size);
    std::vector<char> buffer(size);
    if (_NSGetExecutablePath(buffer.data(), &size) != 0) {
        throw std::runtime_error{"Could not resolve the QGIS+ executable path"};
    }
    return fs::weakly_canonical(buffer.data());
}

[[nodiscard]] fs::path qgisExecutable(const fs::path& contents) {
    const auto macosDirectory =
        contents / "Resources" / "QGIS.app" / "Contents" / "MacOS";
    std::ifstream configuration{
        contents / "Resources" / "qgisplus-executable.txt"};
    std::string executableName;
    if (!std::getline(configuration, executableName) || executableName.empty() ||
        executableName == "." || executableName == ".." ||
        executableName.find('/') != std::string::npos) {
        throw std::runtime_error{"Bundled QGIS executable metadata is invalid"};
    }
    const auto executable = macosDirectory / executableName;
    const auto permissions = fs::status(executable).permissions();
    if (!fs::is_regular_file(executable) ||
        (permissions & fs::perms::owner_exec) == fs::perms::none) {
        throw std::runtime_error{"Bundled QGIS executable is missing"};
    }
    return executable;
}

[[nodiscard]] bool hasOption(const int argc, char* argv[],
                             const int firstForwarded,
                             const std::string_view shortOption,
                             const std::string_view longOption) {
    for (auto index = firstForwarded; index < argc; ++index) {
        const std::string_view argument{argv[index]};
        if (argument == shortOption || argument == longOption ||
            argument.starts_with(std::string{shortOption} + "=") ||
            argument.starts_with(std::string{longOption} + "=")) {
            return true;
        }
    }
    return false;
}

[[nodiscard]] fs::path qgisPlusProfilesPath() {
    const auto home = std::getenv("HOME");
    if (home == nullptr || std::string_view{home}.empty()) {
        throw std::runtime_error{"HOME is unavailable"};
    }
    return fs::path{home} / "Library" / "Application Support" / "QGISPlus";
}

}  // namespace

int main(int argc, char* argv[]) {
    try {
        const auto contents = executablePath().parent_path().parent_path();
        const auto qgis = qgisExecutable(contents);
        // QGIS 会重建自己的 Qt library paths。把插件根目录指向内层官方
        // QGIS.app，确保 QApplication 初始化时能从原生 styles 目录发现主题。
        const auto pluginRoot = (contents / "Resources" / "QGIS.app" /
                                 "Contents" / "PlugIns").string();
        const auto existingPluginPath = std::getenv("QT_PLUGIN_PATH");
        const auto pluginPath = existingPluginPath != nullptr
            ? pluginRoot + ":" + existingPluginPath
            : pluginRoot;
        if (setenv("QT_PLUGIN_PATH", pluginPath.c_str(), 1) != 0) {
            throw std::runtime_error{std::strerror(errno)};
        }

        const bool nativeStyle = argc > 1 &&
            std::string_view{argv[1]} == "--native-style";
        if (nativeStyle) {
            unsetenv("QT_STYLE_OVERRIDE");
        } else if (setenv("QT_STYLE_OVERRIDE", "Qlementine", 1) != 0) {
            throw std::runtime_error{std::strerror(errno)};
        }

        const auto firstForwarded = nativeStyle ? 2 : 1;
        std::vector<std::string> arguments;
        arguments.emplace_back(qgis.string());
        // Qt 6 的命令行形式是 -style=<name>。分成两个参数会只消费
        // -style，并让 QGIS 把 Qlementine 误认为待打开的数据源。
        // QT_STYLE_OVERRIDE 已经是更稳定的跨平台设置方式，不再重复传参。
        if (!nativeStyle) {
            const auto globalSettings =
                contents / "Resources" / "qgisplus-global-settings.ini";
            if (!fs::is_regular_file(globalSettings)) {
                throw std::runtime_error{
                    "Bundled QGIS+ global settings are missing"};
            }
            if (!hasOption(argc, argv, firstForwarded, "-g",
                           "--globalsettingsfile")) {
                arguments.emplace_back("--globalsettingsfile");
                arguments.emplace_back(globalSettings.string());
            }
            if (!hasOption(argc, argv, firstForwarded, "-S",
                           "--profiles-path")) {
                arguments.emplace_back("--profiles-path");
                arguments.emplace_back(qgisPlusProfilesPath().string());
            }
        }
        for (auto index = firstForwarded; index < argc; ++index) {
            arguments.emplace_back(argv[index]);
        }
        std::vector<char*> rawArguments;
        rawArguments.reserve(arguments.size() + 1);
        for (auto& argument : arguments) {
            rawArguments.push_back(argument.data());
        }
        rawArguments.push_back(nullptr);
        execv(qgis.c_str(), rawArguments.data());
        throw std::runtime_error{std::strerror(errno)};
    } catch (const std::exception& error) {
        std::cerr << "QGIS+ could not start QGIS: " << error.what() << '\n';
        return 2;
    }
}
