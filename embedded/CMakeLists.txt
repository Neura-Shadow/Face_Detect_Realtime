cmake_minimum_required(VERSION 3.16)
project(ma_vlna_safety_mcu_sil C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

set(MA_VLNA_SAFETY_MCU_INCLUDE_DIRS
    ${CMAKE_CURRENT_SOURCE_DIR}/protocol
    ${CMAKE_CURRENT_SOURCE_DIR}/safety_mcu/include
)

if(MSVC)
    set(MA_VLNA_C_WARNING_FLAGS /W4 /WX)
else()
    set(MA_VLNA_C_WARNING_FLAGS -Wall -Wextra -Werror -pedantic)
endif()

# Phase 13A portable reference library (frozen contract).
add_library(ma_vlna_safety_mcu STATIC
    safety_mcu/src/safety_fsm.c
    safety_mcu/src/protocol_parser.c
)
target_include_directories(ma_vlna_safety_mcu PUBLIC ${MA_VLNA_SAFETY_MCU_INCLUDE_DIRS})
target_compile_options(ma_vlna_safety_mcu PRIVATE ${MA_VLNA_C_WARNING_FLAGS})

# Phase 13B shared library exposing the same parser/FSM through a narrow C ABI.
# The runtime Virtual Safety MCU loads this library with ctypes; it is the
# Phase 13B runtime source of truth. Build artifacts are never committed.
add_library(ma_vlna_safety_mcu_ffi SHARED
    safety_mcu/src/safety_fsm.c
    safety_mcu/src/protocol_parser.c
    safety_mcu/src/safety_mcu_ffi.c
)
target_include_directories(ma_vlna_safety_mcu_ffi PUBLIC ${MA_VLNA_SAFETY_MCU_INCLUDE_DIRS})
target_compile_options(ma_vlna_safety_mcu_ffi PRIVATE ${MA_VLNA_C_WARNING_FLAGS})
target_compile_definitions(ma_vlna_safety_mcu_ffi PRIVATE MA_VLNA_SAFETY_MCU_FFI_BUILD)
set_target_properties(ma_vlna_safety_mcu_ffi PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    C_VISIBILITY_PRESET hidden
)
if(WIN32)
    # Produce ma_vlna_safety_mcu_ffi.dll instead of libma_vlna_safety_mcu_ffi.dll.
    set_target_properties(ma_vlna_safety_mcu_ffi PROPERTIES PREFIX "")
endif()

enable_testing()

add_executable(phase13a_safety_mcu_tests safety_mcu/tests/test_safety_mcu.c)
target_link_libraries(phase13a_safety_mcu_tests PRIVATE ma_vlna_safety_mcu)
add_test(NAME phase13a_safety_mcu_tests COMMAND phase13a_safety_mcu_tests)

add_executable(phase13b_safety_mcu_ffi_tests
    safety_mcu/tests/test_safety_mcu_ffi.c
    safety_mcu/src/safety_mcu_ffi.c
)
target_link_libraries(phase13b_safety_mcu_ffi_tests PRIVATE ma_vlna_safety_mcu)
target_compile_options(phase13b_safety_mcu_ffi_tests PRIVATE ${MA_VLNA_C_WARNING_FLAGS})
target_compile_definitions(phase13b_safety_mcu_ffi_tests PRIVATE MA_VLNA_SAFETY_MCU_FFI_STATIC)
add_test(NAME phase13b_safety_mcu_ffi_tests COMMAND phase13b_safety_mcu_ffi_tests)
