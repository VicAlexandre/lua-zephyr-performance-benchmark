cmake_minimum_required(VERSION 3.20.0)

set(BENCH_EXP B CACHE STRING "Experiment: CAL, A, B or C")
set(BENCH_MODEL MT CACHE STRING "Model: MT, MC, BASE or NONE")
set(BENCH_N 1 CACHE STRING "Exp. A: replicas of T1, or FULL")
set(BENCH_PAYLOAD 8 CACHE STRING "Exp. B: T4 payload, in bytes")
set(BENCH_SLICE_US 1000 CACHE STRING "Exp. C: slice duration S, in us")
set(BENCH_PRIO EQUAL CACHE STRING "Exp. C, MT: EQUAL or SPLIT")
set(BENCH_HEAP 32768 CACHE STRING "Heap of each Lua state, in bytes")
set(BENCH_DIAG "" CACHE STRING "Diagnostics (list): GC, COLS")

include(${CMAKE_CURRENT_SOURCE_DIR}/../../modules/lang/lua_zephyr/luaz.cmake)
include(cmake/bench.cmake)

list(APPEND EXTRA_CONF_FILE ${CMAKE_CURRENT_SOURCE_DIR}/calibration.conf)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(bench)

luaz_add_bytecode_file(lua/tasks.lua)
luaz_generate_threads()

target_include_directories(app PRIVATE src)
target_sources(app PRIVATE
  src/main.c
  src/probe.c
  src/channels.c
  src/stimulus.c
  src/lua_bench.c
  ${BENCH_GEN_DIR}/bench_glue.c
)
target_sources_ifdef(CONFIG_BENCH_MODEL_BASE app PRIVATE src/baseline.c)
