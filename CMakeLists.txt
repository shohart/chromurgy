# SPDX-License-Identifier: GPL-2.0-only
cmake_minimum_required(VERSION 3.20)
project(mfilm C)
set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)        # -O3: ~1.8x faster film stage than -O2, same bytes (checked)
endif()
# Same float semantics as the camera build: no fast-math, no FMA contraction
add_compile_options(-Wall -Wextra -Wdouble-promotion -ffp-contract=off)
enable_testing()
add_subdirectory(src/shared/film_core)
