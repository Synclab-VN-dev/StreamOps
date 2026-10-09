cmake_minimum_required(VERSION 3.28...3.30)

include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/common/bootstrap.cmake" NO_POLICY_SCOPE)

project(${_name} VERSION ${_version})

option(ENABLE_FRONTEND_API "Use obs-frontend-api for UI functionality" OFF)
option(ENABLE_QT "Use Qt functionality" OFF)
option(ENABLE_WEBSOCKET "Enable obs-websocket API vendor support" ON)

include(compilerconfig)
include(defaults)
include(helpers)

add_library(${CMAKE_PROJECT_NAME} MODULE)

if(WIN32)
  list(APPEND CMAKE_PREFIX_PATH ${CMAKE_CURRENT_SOURCE_DIR}/.deps/obs-studio-32.2.1/build_x64/libobs)
  list(APPEND CMAKE_PREFIX_PATH ${CMAKE_CURRENT_SOURCE_DIR}/.deps/obs-studio-32.2.1/build_x64/deps/w32-pthreads)
  list(APPEND CMAKE_PREFIX_PATH ${CMAKE_CURRENT_SOURCE_DIR}/.deps/obs-studio-32.2.1/build_x64/UI/obs-frontend-api)
endif()

find_package(libobs REQUIRED)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE OBS::libobs)

if(ENABLE_FRONTEND_API)
  find_package(obs-frontend-api REQUIRED)
  target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE OBS::obs-frontend-api)
endif()

if(ENABLE_QT)
  find_package(Qt6 COMPONENTS Widgets Core REQUIRED)
  target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE Qt6::Core Qt6::Widgets)
  target_compile_options(
    ${CMAKE_PROJECT_NAME}
    PRIVATE $<$<C_COMPILER_ID:Clang,AppleClang>:-Wno-quoted-include-in-framework-header -Wno-comma>
  )
  set_target_properties(
    ${CMAKE_PROJECT_NAME}
    PROPERTIES AUTOMOC ON AUTOUIC ON AUTORCC ON
  )
endif()

if(ENABLE_WEBSOCKET)
  find_path(OBS_WEBSOCKET_INCLUDE_DIR
    NAMES obs-websocket-api.h
    PATHS
      "${CMAKE_CURRENT_SOURCE_DIR}/dep/obs-websocket"
      "${CMAKE_CURRENT_SOURCE_DIR}/src"
      "${CMAKE_CURRENT_SOURCE_DIR}/.deps/obs-studio-32.2.1/plugins/obs-websocket"
      "${CMAKE_CURRENT_SOURCE_DIR}/.deps/obs-studio-32.2.1/build_x64/plugins/obs-websocket"
      /opt/homebrew/include
      /usr/local/include
      /usr/include
  )

  if(OBS_WEBSOCKET_INCLUDE_DIR)
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ${OBS_WEBSOCKET_INCLUDE_DIR})
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE ENABLE_WEBSOCKET=1)
    message(STATUS "Found obs-websocket headers: ${OBS_WEBSOCKET_INCLUDE_DIR}")
  else()
    message(FATAL_ERROR "obs-websocket-api.h not found. Custom StreamOps plugin requires the WebSocket Vendor API; refusing to build a release without it.")
  endif()
endif()

target_sources(${CMAKE_PROJECT_NAME} PRIVATE
  ./src/pch.h
  ./src/obs-multi-rtmp.h
  ./src/obs-multi-rtmp.cpp
  ./src/edit-widget.h
  ./src/edit-widget.cpp
  ./src/push-widget.h
  ./src/push-widget.cpp
  ./src/multi-output-widget.h
  ./src/multi-output-widget.cpp
  ./src/json-util.hpp
  ./src/output-config.h
  ./src/output-config.cpp
  ./src/obs-properties-widget.h
  ./src/obs-properties-widget.cpp
  ./src/protocols.h
  ./src/protocols.cpp
  ./src/helpers.h
  ./src/helpers.cpp
  $<$<BOOL:${ENABLE_WEBSOCKET}>:./src/ws_vendor.hpp>
  $<$<BOOL:${ENABLE_WEBSOCKET}>:./src/ws_vendor.cpp>
)

target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/dep
  ${CMAKE_CURRENT_SOURCE_DIR}/dep/nlohmann
  ${CMAKE_CURRENT_SOURCE_DIR}/dep/nlohmann-json
  ${CMAKE_CURRENT_SOURCE_DIR}/dep/obs-websocket
  ${CMAKE_CURRENT_SOURCE_DIR}/src
)

set_target_properties_plugin(${CMAKE_PROJECT_NAME} PROPERTIES OUTPUT_NAME ${_name})
