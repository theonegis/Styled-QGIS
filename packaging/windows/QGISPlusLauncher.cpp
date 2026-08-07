// SPDX-License-Identifier: GPL-2.0-or-later

#include <windows.h>
#include <shellapi.h>

#include <algorithm>
#include <cstdlib>
#include <cwctype>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace {

namespace fs = std::filesystem;

[[nodiscard]] std::wstring windowsErrorMessage(const DWORD error) {
    wchar_t* buffer = nullptr;
    const auto length = FormatMessageW(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
            FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr, error, 0, reinterpret_cast<wchar_t*>(&buffer), 0, nullptr);
    std::wstring message = length != 0 && buffer != nullptr
        ? std::wstring{buffer, length}
        : L"Unknown Windows error";
    if (buffer != nullptr) {
        LocalFree(buffer);
    }
    return message;
}

void showError(const std::wstring_view message) {
    MessageBoxW(nullptr, std::wstring{message}.c_str(), L"QGIS+",
                MB_OK | MB_ICONERROR);
}

[[nodiscard]] std::optional<fs::path> moduleDirectory() {
    std::vector<wchar_t> buffer(32768);
    const auto length = GetModuleFileNameW(
        nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (length == 0 || length >= buffer.size()) {
        return std::nullopt;
    }
    return fs::path{std::wstring_view{buffer.data(), length}}.parent_path();
}

[[nodiscard]] std::wstring lowercase(std::wstring value) {
    std::ranges::transform(value, value.begin(), [](const wchar_t character) {
        return static_cast<wchar_t>(std::towlower(character));
    });
    return value;
}

[[nodiscard]] std::optional<fs::path> findQgisLauncher(const fs::path& root) {
    std::ifstream configuration{root / "qgisplus-launcher.txt"};
    std::string relativePath;
    if (std::getline(configuration, relativePath) && !relativePath.empty()) {
        const auto configured = root / fs::u8path(relativePath);
        if (fs::is_regular_file(configured)) {
            return configured;
        }
    }

    // 配置文件丢失时再扫描，避免正常启动遍历整个 QGIS 安装目录。
    std::vector<fs::path> launchers;
    std::error_code error;
    for (fs::recursive_directory_iterator iterator{
             root, fs::directory_options::skip_permission_denied, error};
         iterator != fs::recursive_directory_iterator{};
         iterator.increment(error)) {
        if (error) {
            error.clear();
            continue;
        }
        if (!iterator->is_regular_file(error)) {
            continue;
        }
        const auto filename = lowercase(iterator->path().filename().wstring());
        if (filename == L"qgis.bat" || filename == L"qgis-ltr.bat" ||
            filename == L"qgis-bin.exe") {
            launchers.push_back(iterator->path());
        }
    }
    if (launchers.empty()) {
        return std::nullopt;
    }
    std::ranges::sort(launchers, [](const fs::path& left, const fs::path& right) {
        const auto rank = [](const fs::path& path) {
            const auto name = lowercase(path.filename().wstring());
            if (name == L"qgis.bat") {
                return 0;
            }
            if (name == L"qgis-ltr.bat") {
                return 1;
            }
            return 2;
        };
        return rank(left) < rank(right);
    });
    return launchers.front();
}

[[nodiscard]] std::wstring quoteArgument(const std::wstring_view argument) {
    std::wstring quoted{L"\""};
    std::size_t backslashes = 0;
    for (const auto character : argument) {
        if (character == L'\\') {
            ++backslashes;
            continue;
        }
        if (character == L'\"') {
            quoted.append(backslashes * 2 + 1, L'\\');
            quoted.push_back(L'\"');
            backslashes = 0;
            continue;
        }
        quoted.append(backslashes, L'\\');
        backslashes = 0;
        quoted.push_back(character);
    }
    quoted.append(backslashes * 2, L'\\');
    quoted.push_back(L'\"');
    return quoted;
}

[[nodiscard]] std::wstring forwardedArguments(const bool nativeStyle) {
    std::wstring arguments;
    if (!nativeStyle) {
        arguments = L"-style Qlementine";
    }
    for (int index = nativeStyle ? 2 : 1; index < __argc; ++index) {
        if (!arguments.empty()) {
            arguments.push_back(L' ');
        }
        arguments += quoteArgument(__wargv[index]);
    }
    return arguments;
}

}  // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    const auto root = moduleDirectory();
    if (!root) {
        showError(L"无法确定 QGIS+ 安装目录。\n\n" +
                  windowsErrorMessage(GetLastError()));
        return 2;
    }

    const auto qgisLauncher = findQgisLauncher(*root);
    if (!qgisLauncher) {
        showError(L"QGIS+ 安装不完整：找不到官方 QGIS 启动程序。\n"
                  L"请重新运行安装包进行修复。");
        return 3;
    }

    const bool nativeStyle = __argc > 1 &&
        _wcsicmp(__wargv[1], L"--native-style") == 0;
    if (nativeStyle) {
        SetEnvironmentVariableW(L"QT_STYLE_OVERRIDE", nullptr);
    } else if (!SetEnvironmentVariableW(L"QT_STYLE_OVERRIDE", L"Qlementine")) {
        showError(L"无法设置 Qlementine 环境。\n\n" +
                  windowsErrorMessage(GetLastError()));
        return 4;
    }

    auto file = qgisLauncher->wstring();
    auto parameters = forwardedArguments(nativeStyle);
    auto directory = qgisLauncher->parent_path().wstring();
    SHELLEXECUTEINFOW executeInfo{
        .cbSize = sizeof(SHELLEXECUTEINFOW),
        .fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI,
        .hwnd = nullptr,
        .lpVerb = L"open",
        .lpFile = file.c_str(),
        .lpParameters = parameters.empty() ? nullptr : parameters.c_str(),
        .lpDirectory = directory.c_str(),
        .nShow = SW_SHOWNORMAL,
    };
    if (!ShellExecuteExW(&executeInfo) || executeInfo.hProcess == nullptr) {
        showError(L"无法启动官方 QGIS。\n\n" +
                  windowsErrorMessage(GetLastError()));
        return 5;
    }

    WaitForSingleObject(executeInfo.hProcess, INFINITE);
    DWORD exitCode = 1;
    GetExitCodeProcess(executeInfo.hProcess, &exitCode);
    CloseHandle(executeInfo.hProcess);
    return static_cast<int>(exitCode);
}
