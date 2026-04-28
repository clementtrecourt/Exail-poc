cmake_minimum_required(VERSION 3.10)
project(exail_backend)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -s") 

add_executable(exail_backend src/main.cpp)
