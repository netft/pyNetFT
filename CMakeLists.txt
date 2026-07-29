cmake_minimum_required(VERSION 3.16)
project(pynetft VERSION 2.1.0 LANGUAGES CXX)

option(PYNETFT_BUILD_TESTING "Build pyNetFT native tests" OFF)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(NETFT_BUILD_CLI OFF CACHE BOOL "" FORCE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

add_subdirectory(core EXCLUDE_FROM_ALL)
if(WIN32)
  target_compile_definitions(netft PRIVATE CURL_STATICLIB)
  target_link_libraries(netft PRIVATE
    advapi32
    bcrypt
    crypt32
    iphlpapi
    secur32
    ws2_32
  )
endif()

pybind11_add_module(_native MODULE
  bindings/python/bind_types.cpp
  bindings/python/module.cpp
  bindings/python/native_client.cpp
  bindings/python/sample_queue.cpp
)
target_compile_features(_native PRIVATE cxx_std_17)
target_compile_definitions(_native PRIVATE PYNETFT_VERSION="${PROJECT_VERSION}")
target_link_libraries(_native PRIVATE netft::netft)

install(TARGETS _native LIBRARY DESTINATION pynetft)

if(PYNETFT_BUILD_TESTING)
  enable_testing()
  find_package(GTest REQUIRED)

  if(TARGET GTest::gtest_main)
    set(PYNETFT_GTEST_MAIN_TARGET GTest::gtest_main)
  elseif(TARGET GTest::Main)
    set(PYNETFT_GTEST_MAIN_TARGET GTest::Main)
  else()
    message(FATAL_ERROR "GoogleTest does not provide a main target")
  endif()

  add_executable(test_sample_queue
    tests/native/test_sample_queue.cpp
    bindings/python/sample_queue.cpp
  )
  target_compile_features(test_sample_queue PRIVATE cxx_std_17)
  target_compile_definitions(test_sample_queue PRIVATE PYNETFT_SAMPLE_QUEUE_TESTING)
  target_include_directories(test_sample_queue PRIVATE bindings/python)
  target_link_libraries(test_sample_queue PRIVATE
    "${PYNETFT_GTEST_MAIN_TARGET}"
    netft::netft
  )
  add_test(NAME sample_queue COMMAND test_sample_queue)

  add_executable(test_native_client
    tests/native/test_native_client.cpp
    bindings/python/native_client.cpp
    bindings/python/sample_queue.cpp
  )
  target_compile_features(test_native_client PRIVATE cxx_std_17)
  target_compile_definitions(test_native_client PRIVATE PYNETFT_NATIVE_CLIENT_TESTING)
  target_include_directories(test_native_client PRIVATE bindings/python)
  target_link_libraries(test_native_client PRIVATE
    "${PYNETFT_GTEST_MAIN_TARGET}"
    netft::netft
  )
  add_test(NAME native_client COMMAND test_native_client)

  pybind11_add_module(_exception_probe MODULE tests/native/exception_probe.cpp)
  target_compile_features(_exception_probe PRIVATE cxx_std_17)
  target_link_libraries(_exception_probe PRIVATE netft::netft)
  add_test(
    NAME exception_locality
    COMMAND
      "${Python_EXECUTABLE}"
      -S
      "${CMAKE_CURRENT_SOURCE_DIR}/tests/native/exception_locality_check.py"
  )
  set_tests_properties(
    exception_locality
    PROPERTIES
      ENVIRONMENT
        "PYTHONPATH=$<TARGET_FILE_DIR:_native>:$<TARGET_FILE_DIR:_exception_probe>"
  )
endif()
