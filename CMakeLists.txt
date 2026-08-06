cmake_minimum_required(VERSION 3.25)

project(QGISPlusStyle VERSION 0.1.0 LANGUAGES CXX)

include(FetchContent)
include(GNUInstallDirs)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_AUTOMOC ON)

set(QGISPLUS_QLEMENTINE_TAG "v1.4.2" CACHE STRING
    "Qlementine Git tag used when no local source directory is supplied")
set(QGISPLUS_QLEMENTINE_SOURCE_DIR "" CACHE PATH
    "Optional local Qlementine source tree prepared by scripts/prepare_source.py")
option(QGISPLUS_BUILD_TESTS "Build the style discovery smoke test" ON)

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Svg Widgets)

# CI 会提前拉取精确 Release；本地构建时仍允许 CMake 自行获取指定 tag。
if(QGISPLUS_QLEMENTINE_SOURCE_DIR)
    if(NOT EXISTS "${QGISPLUS_QLEMENTINE_SOURCE_DIR}/CMakeLists.txt")
        message(FATAL_ERROR
            "QGISPLUS_QLEMENTINE_SOURCE_DIR does not contain Qlementine sources")
    endif()
    add_subdirectory(
        "${QGISPLUS_QLEMENTINE_SOURCE_DIR}"
        "${CMAKE_CURRENT_BINARY_DIR}/qlementine"
        EXCLUDE_FROM_ALL
    )
else()
    FetchContent_Declare(qlementine_upstream
        GIT_REPOSITORY https://github.com/oclero/qlementine.git
        GIT_TAG "${QGISPLUS_QLEMENTINE_TAG}"
        GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(qlementine_upstream)
endif()

add_library(QGISPlusStyle MODULE
    src/QlementineStylePlugin.cpp
    src/QlementineStylePlugin.hpp
    src/qlementinestyle.json
)

target_link_libraries(QGISPlusStyle PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Svg
    Qt6::Widgets
    qlementine
)

target_compile_definitions(QGISPlusStyle PRIVATE
    QT_NO_CAST_FROM_ASCII
    QT_NO_CAST_TO_ASCII
)

if(MSVC)
    target_compile_options(QGISPlusStyle PRIVATE /W4 /permissive-)
else()
    target_compile_options(QGISPlusStyle PRIVATE
        -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
endif()

# Qt 只会在插件根目录下的 styles 子目录中发现 QStylePlugin。
set_target_properties(QGISPlusStyle PROPERTIES
    OUTPUT_NAME qgisplusstyle
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/styles"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/styles"
)

install(TARGETS QGISPlusStyle
    LIBRARY DESTINATION styles
    RUNTIME DESTINATION styles
)

if(QGISPLUS_BUILD_TESTS)
    enable_testing()
    add_executable(QGISPlusStyleSmokeTest tests/StylePluginSmokeTest.cpp)
    target_link_libraries(QGISPlusStyleSmokeTest PRIVATE Qt6::Widgets)
    add_dependencies(QGISPlusStyleSmokeTest QGISPlusStyle)

    add_test(
        NAME style-plugin-discovery
        COMMAND QGISPlusStyleSmokeTest $<TARGET_FILE:QGISPlusStyle>
    )

    # Windows 必须在创建测试进程前找到 Qt DLL。直接在 Git Bash 的 PATH
    # 中拼接 D:/... 会把盘符冒号误判为列表分隔符，因此由 CTest 从导入的
    # Qt 目标解析真实运行时目录，保证本地构建和 CI 使用同一规则。
    if(WIN32)
        set_tests_properties(style-plugin-discovery PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:$<TARGET_FILE_DIR:Qt6::Core>"
        )
    endif()
endif()
