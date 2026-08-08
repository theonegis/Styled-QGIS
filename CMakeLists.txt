cmake_minimum_required(VERSION 3.25)

project(QGISPlusOverlay VERSION 0.2.0 LANGUAGES CXX)

include(GNUInstallDirs)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(WIN32)
    if(NOT MSVC)
        message(FATAL_ERROR
            "QGIS+ Windows launcher must use MSVC to match the official runtime")
    endif()

    # 启动器只依赖 Win32 API。QSS 主题不再链接 Qt，也不存在 Qt ABI 风险。
    add_executable(QGISPlusLauncher WIN32
        packaging/windows/QGISPlusLauncher.cpp
    )
    target_compile_features(QGISPlusLauncher PRIVATE cxx_std_20)
    target_compile_definitions(QGISPlusLauncher PRIVATE
        UNICODE
        _UNICODE
        WIN32_LEAN_AND_MEAN
        NOMINMAX
    )
    target_compile_options(QGISPlusLauncher PRIVATE /W4 /permissive-)
    target_link_libraries(QGISPlusLauncher PRIVATE Shell32)
    set_target_properties(QGISPlusLauncher PROPERTIES
        OUTPUT_NAME "QGIS+"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/launcher"
    )
elseif(APPLE)
    add_executable(QGISPlusLauncher
        packaging/macos/QGISPlusLauncher.cpp
    )
    target_compile_features(QGISPlusLauncher PRIVATE cxx_std_20)
    target_compile_options(QGISPlusLauncher PRIVATE
        -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion
    )
    set_target_properties(QGISPlusLauncher PROPERTIES
        OUTPUT_NAME "QGISPlusLauncher"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/launcher"
    )
else()
    message(STATUS "QGIS+ installer overlay is built only on Windows and macOS")
endif()

install(DIRECTORY "themes/QGISPlus Material"
    DESTINATION "${CMAKE_INSTALL_DATADIR}/qgisplus/themes"
)
