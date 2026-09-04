cmake_minimum_required(VERSION 4.0)

if(DEFINED SKBUILD_CORE_VERSION)
    project(
        ${SKBUILD_PROJECT_NAME}
        VERSION ${SKBUILD_PROJECT_VERSION}
        LANGUAGES CXX
    )
else()
    set(SKBUILD_PROJECT_NAME smiling)
    project(${SKBUILD_PROJECT_NAME} LANGUAGES CXX)
    set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
endif()

set(CMAKE_CXX_STANDARD 23)

include(CheckIPOSupported)
check_ipo_supported()
set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)

find_package(Python 3.14.0...<3.15.0 REQUIRED Interpreter Development.Module)

if(DEFINED SKBUILD_CORE_VERSION)
    find_package(nanobind 3.0.1...<4.0.0 REQUIRED CONFIG)
else()
    find_package(
        nanobind 3.0.1...<4.0.0
        REQUIRED
        CONFIG
        PATHS "${Python_SITELIB}/nanobind"
    )
endif()

nanobind_add_module(
    _smiling
    LTO
    NB_DOMAIN ${SKBUILD_PROJECT_NAME}
    src/smiling/smiling.cpp
)

if(NOT DEFINED ENV{CONDA_BUILD})
    target_include_directories(
        _smiling
        PRIVATE
        "$ENV{CONDA_PREFIX}/Library/include"
    )
    target_link_directories(
        _smiling
        PRIVATE
        "$ENV{CONDA_PREFIX}/Library/lib"
    )
endif()

target_link_libraries(_smiling PRIVATE avutil)
install(TARGETS _smiling DESTINATION ${SKBUILD_PROJECT_NAME})
