cmake_minimum_required(VERSION 3.16)
project(devtrack_core CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-Wall -Wextra)

add_library(devtrack_core
  core/src/sha256.cpp
  core/src/diff.cpp
  core/src/validate.cpp)
target_include_directories(devtrack_core PUBLIC core/include)

add_executable(dtcore core/src/main.cpp)
target_link_libraries(dtcore PRIVATE devtrack_core)

option(DEVTRACK_BUILD_TESTS "Build GoogleTest unit tests" ON)
if(DEVTRACK_BUILD_TESTS)
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.zip
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)

  enable_testing()
  add_executable(core_tests core/tests/test_core.cpp)
  target_link_libraries(core_tests PRIVATE devtrack_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(core_tests)
endif()
