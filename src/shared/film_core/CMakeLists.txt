# SPDX-License-Identifier: GPL-2.0-only
add_library(mf_core STATIC
  src/mf_look.c
  src/mf_looks_builtin.c
  src/mf_sha256.c
  src/mf_seed.c)
target_include_directories(mf_core PUBLIC include)
target_link_libraries(mf_core PUBLIC m)

foreach(t test_film_color test_seed test_noise)
  add_executable(${t} tests/${t}.c)
  target_link_libraries(${t} mf_core)
endforeach()
add_test(NAME film_color_matches_upstream
         COMMAND test_film_color ${CMAKE_CURRENT_SOURCE_DIR}/tests/golden_film_color.txt)
add_test(NAME seed_and_sha256 COMMAND test_seed)
add_test(NAME noise_tile_order_independent COMMAND test_noise)
