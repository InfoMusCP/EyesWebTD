cmake_minimum_required(VERSION 3.20)

# One version for the whole package, in the VERSION file (MAJOR.MINOR.PATCH). TouchDesigner compares MAJOR and MINOR of the
# operators saved in a .toe with the installed ones: a MAJOR change is for changes that break saved projects (a renamed
# parameter or channel), MINOR for new operators or parameters, PATCH for fixes.
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/VERSION" EW_TD_VERSION_TEXT LIMIT_COUNT 1)
project(EyesWebTD_CHOP VERSION ${EW_TD_VERSION_TEXT} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The directory with CPlusPlus_Common.h and CHOP_CPlusPlusBase.h. By default the copy in third_party/touchdesigner_sdk (the
# files of TouchDesigner 2025.32280, unmodified, under Derivative's Shared Use License); point it at the CHOP sample
# directory of an installed TouchDesigner to build against that instead.
set(TD_CHOP_SDK "${CMAKE_CURRENT_SOURCE_DIR}/third_party/touchdesigner_sdk" CACHE PATH "Path to TouchDesigner C++ CHOP SDK headers")
set(EW_TD_BUILT_FOR "TouchDesigner 2025.32280 (CHOP C++ API 10)" CACHE STRING "Text for the package notes: the TouchDesigner the SDK headers come from")

# ew_td/version.h (MAJOR, MINOR, PATCH, text) and the Windows version resource of each DLL are generated in the build tree.
set(EW_TD_GENERATED "${CMAKE_BINARY_DIR}/generated")
configure_file(cmake/version.h.in "${EW_TD_GENERATED}/ew_td/version.h" @ONLY)

# If built as a standalone project, build the core library
if(NOT TARGET ew_core)
  set(EW_CORE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../EyesWebCore" CACHE PATH "Checkout of the EyesWebCore C++ core")
  if(NOT EXISTS "${EW_CORE_DIR}/core/src")
    message(FATAL_ERROR "EW_CORE_DIR must point to a checkout of EyesWebCore (got ${EW_CORE_DIR})")
  endif()
  set(REPO_ROOT "${EW_CORE_DIR}")
  file(GLOB_RECURSE EW_CORE_SOURCES CONFIGURE_DEPENDS "${REPO_ROOT}/core/src/*.cpp")
  add_library(ew_core STATIC ${EW_CORE_SOURCES})
  target_include_directories(ew_core PUBLIC "${REPO_ROOT}/core/include")
  target_include_directories(ew_core SYSTEM PRIVATE "${REPO_ROOT}/third_party/pocketfft")
  if(MSVC)
    target_compile_options(ew_core PRIVATE /W4)
    target_compile_definitions(ew_core PUBLIC _USE_MATH_DEFINES)
  endif()
endif()
# One folder per layer of the PyEyesWeb model under chops/, one DLL per operator (TouchDesigner loads one operator
# per DLL). The DLLs are collected in Plugins/EyesWeb/<layer>/ of the build tree. A new .cpp in a layer folder is
# picked up at the next configure.
set(EW_LAYERS physical_signals low_level mid_level high_level analysis_primitives)

foreach(LAYER IN LISTS EW_LAYERS)
  file(GLOB LAYER_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/chops/${LAYER}/*.cpp")
  foreach(SRC IN LISTS LAYER_SOURCES)
    get_filename_component(NAME_WE ${SRC} NAME_WE)
    set(TARGET_NAME "Ew_${NAME_WE}")
    add_library(${TARGET_NAME} SHARED ${SRC})
    target_link_libraries(${TARGET_NAME} PRIVATE ew_core)
    target_include_directories(${TARGET_NAME} PRIVATE ${TD_CHOP_SDK} "${CMAKE_CURRENT_SOURCE_DIR}/common" "${EW_TD_GENERATED}")
    if(WIN32)
      # File properties of the DLL (version, product), the same for every operator.
      set(EW_TD_DLL_NAME "Ew_${NAME_WE}.dll")
      configure_file(cmake/version.rc.in "${EW_TD_GENERATED}/rc/${TARGET_NAME}.rc" @ONLY)
      target_sources(${TARGET_NAME} PRIVATE "${EW_TD_GENERATED}/rc/${TARGET_NAME}.rc")
    endif()
    # TouchDesigner does not load DLLs from subfolders of Plugins: the package is flat (the build tree keeps the layer folders).
    install(TARGETS ${TARGET_NAME} RUNTIME DESTINATION Plugins)
    string(REGEX REPLACE "CHOP$" "" OP_FEATURE "${NAME_WE}")
    string(TOLOWER "${OP_FEATURE}" NAME_LOWER)
    list(APPEND EW_TD_OPERATOR_LIST "${LAYER} Ew${NAME_LOWER}")
    # The generator expression keeps Visual Studio from adding a per-configuration subfolder.
    set_target_properties(${TARGET_NAME} PROPERTIES
      RUNTIME_OUTPUT_DIRECTORY "$<1:${CMAKE_BINARY_DIR}/Plugins/EyesWeb/${LAYER}>")
    if(MSVC)
      target_compile_definitions(${TARGET_NAME} PRIVATE _USE_MATH_DEFINES)
    endif()
  endforeach()
endforeach()

# Tests of the base layer that need no TouchDesigner (schema, labels, status): ctest -C Release
enable_testing()
add_executable(ew_td_tests tests/test_base.cpp)
target_include_directories(ew_td_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/common")
add_test(NAME ew_td_tests COMMAND ew_td_tests)

# Mock TouchDesigner host (tests/host): loads an operator DLL with LoadLibrary and cooks it like TouchDesigner does, for
# the Python tests in tests/host (ewhost.py). It does not link the operators. The fixture is a CHOP that exists only to
# test the host. Both are built in the default output folder of the generator (<build>/Release/).
add_library(ew_td_host SHARED tests/host/ew_td_host.cpp)
target_include_directories(ew_td_host PRIVATE ${TD_CHOP_SDK} "${CMAKE_CURRENT_SOURCE_DIR}/tests/host")
add_library(ew_td_fixture SHARED tests/host/fixture/ew_fixture_chop.cpp)
target_include_directories(ew_td_fixture PRIVATE ${TD_CHOP_SDK})
add_library(ew_td_fixture_top SHARED tests/host/fixture/ew_fixture_top_chop.cpp)
target_include_directories(ew_td_fixture_top PRIVATE ${TD_CHOP_SDK})

# ---- Package (cmake --install <build> --config Release --prefix <dir>, or cpack -C Release) -----------------------------
# <prefix>/Plugins/Ew_<Feature>CHOP.dll (flat), the palette builder with the list of operators per layer, the notices and the
# changelog.
list(JOIN EW_TD_OPERATOR_LIST "
" EW_TD_OPERATOR_LINES)
file(WRITE "${EW_TD_GENERATED}/operators.txt" "${EW_TD_OPERATOR_LINES}
")
install(FILES "${EW_TD_GENERATED}/operators.txt" DESTINATION palette)
install(FILES README.md CHANGELOG.md THIRD_PARTY_NOTICES.md VERSION DESTINATION .)
install(DIRECTORY palette/ DESTINATION palette FILES_MATCHING PATTERN "*.py" PATTERN "*.md" PATTERN "*.tox")
configure_file(cmake/PACKAGE_INFO.txt.in "${EW_TD_GENERATED}/PACKAGE_INFO.txt" @ONLY)
install(FILES "${EW_TD_GENERATED}/PACKAGE_INFO.txt" DESTINATION .)

set(CPACK_PACKAGE_NAME "EyesWebTD")
set(CPACK_PACKAGE_VERSION "${PROJECT_VERSION}")
set(CPACK_PACKAGE_VENDOR "InfoMus Lab")
set(CPACK_GENERATOR ZIP)
set(CPACK_PACKAGE_FILE_NAME "EyesWebTD-${PROJECT_VERSION}-win64")
set(CPACK_INCLUDE_TOPLEVEL_DIRECTORY OFF)
include(CPack)
