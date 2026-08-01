cmake_minimum_required(VERSION 3.16)

project(netft VERSION 0.3.2 LANGUAGES CXX)

include(CTest)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

option(NETFT_SANITIZERS "Enable address and undefined behavior sanitizers" OFF)

add_library(netft_sanitizers INTERFACE)
if(NETFT_SANITIZERS)
  if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(netft_sanitizers INTERFACE
      -fno-omit-frame-pointer
      -fsanitize=address,undefined
    )
    target_link_options(netft_sanitizers INTERFACE -fsanitize=address,undefined)
  else()
    message(FATAL_ERROR "NETFT_SANITIZERS requires a Clang or GNU-compatible compiler")
  endif()
endif()

find_package(Threads REQUIRED)
find_package(CURL 7.63.0 REQUIRED)

add_library(netft
  src/types.cpp
  src/status.cpp
  src/discovery.cpp
  src/client.cpp
  src/detail/client_impl.cpp
  src/detail/fault_latch.cpp
  src/detail/protocol.cpp
  src/detail/sequence.cpp
  src/detail/xml_config.cpp
)
if(WIN32)
  target_sources(netft PRIVATE src/detail/udp_transport_windows.cpp)
  target_link_libraries(netft PRIVATE ws2_32)
else()
  target_sources(netft PRIVATE src/detail/udp_transport_posix.cpp)
endif()
add_library(netft::netft ALIAS netft)

target_compile_definitions(netft PRIVATE NETFT_BUILDING_LIBRARY)

set_target_properties(netft PROPERTIES
  VERSION "${PROJECT_VERSION}"
  SOVERSION 1
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
)

target_compile_features(netft PUBLIC cxx_std_17)
target_include_directories(netft
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(netft
  PUBLIC
    Threads::Threads
    CURL::libcurl
    $<BUILD_INTERFACE:netft_sanitizers>
)

install(
  DIRECTORY include/netft
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)
install(
  TARGETS netft
  EXPORT netftTargets
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)
set(netft_cmake_install_dir "${CMAKE_INSTALL_LIBDIR}/cmake/netft")
configure_package_config_file(
  cmake/netftConfig.cmake.in
  "${CMAKE_CURRENT_BINARY_DIR}/netftConfig.cmake"
  INSTALL_DESTINATION "${netft_cmake_install_dir}"
)
write_basic_package_version_file(
  "${CMAKE_CURRENT_BINARY_DIR}/netftConfigVersion.cmake"
  VERSION "${PROJECT_VERSION}"
  COMPATIBILITY SameMinorVersion
)
install(
  EXPORT netftTargets
  FILE netftTargets.cmake
  NAMESPACE netft::
  DESTINATION "${netft_cmake_install_dir}"
)
install(
  FILES
    "${CMAKE_CURRENT_BINARY_DIR}/netftConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/netftConfigVersion.cmake"
  DESTINATION "${netft_cmake_install_dir}"
)

if(BUILD_TESTING)
  find_package(GTest REQUIRED)
  if(TARGET GTest::gtest_main)
    set(NETFT_GTEST_MAIN_TARGET GTest::gtest_main)
  elseif(TARGET GTest::Main)
    set(NETFT_GTEST_MAIN_TARGET GTest::Main)
  else()
    message(FATAL_ERROR "GoogleTest does not provide a main target")
  endif()
  add_subdirectory(test)
endif()
