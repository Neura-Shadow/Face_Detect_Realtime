cmake_minimum_required(VERSION 3.16)
project(ma_vlna_safety_mcu_sil C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(ma_vlna_safety_mcu STATIC
    safety_mcu/src/safety_fsm.c
    safety_mcu/src/protocol_parser.c
)
target_include_directories(ma_vlna_safety_mcu PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/protocol
    ${CMAKE_CURRENT_SOURCE_DIR}/safety_mcu/include
)
if(MSVC)
    target_compile_options(ma_vlna_safety_mcu PRIVATE /W4 /WX)
else()
    target_compile_options(ma_vlna_safety_mcu PRIVATE -Wall -Wextra -Werror -pedantic)
endif()

enable_testing()
add_executable(phase13a_safety_mcu_tests safety_mcu/tests/test_safety_mcu.c)
target_link_libraries(phase13a_safety_mcu_tests PRIVATE ma_vlna_safety_mcu)
add_test(NAME phase13a_safety_mcu_tests COMMAND phase13a_safety_mcu_tests)
