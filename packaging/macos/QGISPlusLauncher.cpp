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

}  // namespace

int main(int argc, char* argv[]) {
    try {
        const auto contents = executablePath().parent_path().parent_path();
        const auto qgis = qgisExecutable(contents);
        const auto pluginRoot = (contents / "PlugIns").string();
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

        std::vector<std::string> arguments;
        arguments.emplace_back(qgis.string());
        if (!nativeStyle) {
            arguments.emplace_back("-style");
            arguments.emplace_back("Qlementine");
        }
        const auto firstForwarded = nativeStyle ? 2 : 1;
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
