# SPDX-License-Identifier: GPL-2.0-only
set(MF_CORE_SOURCES
  src/mf_look.c
  src/mf_looks_builtin.c
  src/mf_sha256.c
  src/mf_seed.c
  src/mf_bundle.c
  src/mf_table.c
  src/mf_develop.c
  src/mf_api.c)
# content hash of the film core sources: the "film_core_version" in render
# identities, stable across commits that do not touch the core
set(_mf_hashes "")
foreach(f include/mf_core.h ${MF_CORE_SOURCES})
  file(SHA256 ${CMAKE_CURRENT_SOURCE_DIR}/${f} _h)
  string(APPEND _mf_hashes "${f}:${_h}\n")
endforeach()
string(SHA256 MF_CORE_SOURCE_HASH "${_mf_hashes}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS include/mf_core.h ${MF_CORE_SOURCES})
add_compile_definitions(MF_CORE_SOURCE_HASH="${MF_CORE_SOURCE_HASH}")
add_library(mf_core STATIC ${MF_CORE_SOURCES})
target_include_directories(mf_core PUBLIC include)
target_link_libraries(mf_core PUBLIC m)
# the same sources as a shared library for the Linux worker (ctypes)
add_library(mf_core_shared SHARED ${MF_CORE_SOURCES})
set_target_properties(mf_core_shared PROPERTIES OUTPUT_NAME mf_core C_VISIBILITY_PRESET default)
target_include_directories(mf_core_shared PUBLIC include)
target_link_libraries(mf_core_shared PUBLIC m)

foreach(t test_film_color test_seed test_noise test_bundle test_develop)
  add_executable(${t} tests/${t}.c)
  target_link_libraries(${t} mf_core)
endforeach()
add_test(NAME film_color_matches_upstream
         COMMAND test_film_color ${CMAKE_CURRENT_SOURCE_DIR}/tests/golden_film_color.txt)
add_test(NAME seed_and_sha256 COMMAND test_seed)
add_test(NAME noise_tile_order_independent COMMAND test_noise)
add_test(NAME bundle_parses_all_films
         COMMAND test_bundle ${PROJECT_SOURCE_DIR}/profiles/mfilm-films.bin)
add_test(NAME develop_frame_properties COMMAND test_develop ${PROJECT_SOURCE_DIR}/profiles/mfilm-films.bin)
