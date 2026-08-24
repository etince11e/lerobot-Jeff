cmake_minimum_required(VERSION 3.14)

project(PXREARobotSDK LANGUAGES CXX)

set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
cmake_host_system_information(RESULT ISA_NAME QUERY OS_PLATFORM)
message("OS_PLATFORM: ${ISA_NAME}")
if(WIN32)
set(INSTALL_DIR  ${PROJECT_SOURCE_DIR}/../SDK/win/64)
endif()

if(UNIX)
    if(ISA_NAME STREQUAL "aarch64")
        set(INSTALL_DIR  ${PROJECT_SOURCE_DIR}/../SDK/linux_aarch64/64)
    else()
        set(INSTALL_DIR  ${PROJECT_SOURCE_DIR}/../SDK/linux/64)
    endif()
endif()

file(MAKE_DIRECTORY ${INSTALL_DIR})

add_compile_definitions(_SILENCE_CXX17_ITERATOR_BASE_CLASS_DEPRECATION_WARNING)




if(WIN32)

    add_definitions(-DPXREACLIENTSDK_LIBRARY)

    add_library(PXREARobotSDK SHARED
        ../PXREAService/PXREAService.grpc.pb.cc
        ../PXREAService/PXREAService.pb.cc
        ../PXREAService/PXREAService.grpc.pb.h
        ../PXREAService/PXREAService.pb.h
        PXREARobotSDK.cpp
        PXREARobotSDK.h

    )

    target_include_directories(PXREARobotSDK PUBLIC
        ../GrpcSDK/include
        ../PXREAService
    )
endif()

if(UNIX)
    if(ISA_NAME STREQUAL "aarch64")
        add_library(PXREARobotSDK SHARED
            ../PXREAService/linux_aarch64/PXREAService.grpc.pb.cc
            ../PXREAService/linux_aarch64/PXREAService.pb.cc
            ../PXREAService/linux_aarch64/PXREAService.grpc.pb.h
            ../PXREAService/linux_aarch64/PXREAService.pb.h
            PXREARobotSDK.cpp
            PXREARobotSDK.h

        )

        target_include_directories(PXREARobotSDK PUBLIC
            ../Redistributable/linux_aarch64/grpc/include
            ../PXREAService/linux_aarch64

        )

    else()
        add_library(PXREARobotSDK SHARED
            ../PXREAService/linux_x86/PXREAService.grpc.pb.cc
            ../PXREAService/linux_x86/PXREAService.pb.cc
            ../PXREAService/linux_x86/PXREAService.grpc.pb.h
            ../PXREAService/linux_x86/PXREAService.pb.h
            PXREARobotSDK.cpp
            PXREARobotSDK.h

        )

        target_include_directories(PXREARobotSDK PUBLIC
            ../Redistributable/linux/grpc/include
            ../PXREAService/linux_x86
        )

    endif()
endif()


if(WIN32)

    target_compile_definitions(PXREARobotSDK PUBLIC
        WINDOWS_x86
    )

    if(CMAKE_BUILD_TYPE STREQUAL "Debug")
        target_link_directories(PXREARobotSDK PUBLIC ${PROJECT_SOURCE_DIR}/../GrpcSDK/lib/debug)

        target_link_libraries(PXREARobotSDK PUBLIC
            # Remove: L${CMAKE_CURRENT_SOURCE_DIR}/../bin/
            # Remove: L${CMAKE_CURRENT_SOURCE_DIR}/../bin/ByteRTC/
            zlibstaticd
            absl_bad_any_cast_impl
            absl_bad_optional_access
            absl_bad_variant_access
            absl_base
            absl_city
            absl_civil_time
            absl_cord
            absl_debugging_internal
            absl_demangle_internal
            absl_examine_stack
            absl_exponential_biased
            absl_failure_signal_handler
            absl_flags
            absl_flags_commandlineflag
            absl_flags_commandlineflag_internal
            absl_flags_config
            absl_flags_internal
            absl_flags_marshalling
            absl_flags_parse
            absl_flags_private_handle_accessor
            absl_flags_program_name
            absl_flags_reflection
            absl_flags_usage
            absl_flags_usage_internal
            absl_graphcycles_internal
            absl_hash
            absl_hashtablez_sampler
            absl_int128
            absl_leak_check
            absl_leak_check_disable
            absl_log_severity
            absl_malloc_internal
            absl_periodic_sampler
            absl_random_distributions
            absl_random_internal_distribution_test_util
            absl_random_internal_platform
            absl_random_internal_pool_urbg
            absl_random_internal_randen
            absl_random_internal_randen_hwaes
            absl_random_internal_randen_hwaes_impl
            absl_random_internal_randen_slow
            absl_random_internal_seed_material
            absl_random_seed_gen_exception
            absl_random_seed_sequences
            absl_raw_hash_set
            absl_raw_logging_internal
            absl_scoped_set_env
            absl_spinlock_wait
            absl_stacktrace
            absl_status
            absl_statusor
            absl_str_format_internal
            absl_strerror
            absl_strings
            absl_strings_internal
            absl_symbolize
            absl_synchronization
            absl_throw_delegate
            absl_time
            absl_time_zone
            absl_wyhash
            address_sorting
            cares
            crypto
            gpr
            grpc
            grpc_plugin_support
            grpc_unsecure
            grpc++
            grpc++_alts
            grpc++_error_details
            grpc++_reflection
            grpc++_unsecure
            grpcpp_channelz
            libprotobufd
            libprotobuf-lited
            libprotocd
            re2
            ssl
            upb
            zlibstaticd
        )

    endif()

    if(CMAKE_BUILD_TYPE STREQUAL "Release")
        target_link_directories(PXREARobotSDK PUBLIC ${PROJECT_SOURCE_DIR}/../GrpcSDK/lib/release)

        target_link_libraries(PXREARobotSDK PUBLIC
            # Remove: L${CMAKE_CURRENT_SOURCE_DIR}/../bin/
            # Remove: L${CMAKE_CURRENT_SOURCE_DIR}/../bin/ByteRTC/
            zlibstatic.lib
            absl_bad_any_cast_impl.lib
            absl_bad_optional_access.lib
            absl_bad_variant_access.lib
            absl_base.lib
            absl_city.lib
            absl_civil_time.lib
            absl_cord.lib
            absl_debugging_internal.lib
            absl_demangle_internal.lib
            absl_examine_stack.lib
            absl_exponential_biased.lib
            absl_failure_signal_handler.lib
            absl_flags.lib
            absl_flags_commandlineflag.lib
            absl_flags_commandlineflag_internal.lib
            absl_flags_config.lib
            absl_flags_internal.lib
            absl_flags_marshalling.lib
            absl_flags_parse.lib
            absl_flags_private_handle_accessor.lib
            absl_flags_program_name.lib
            absl_flags_reflection.lib
            absl_flags_usage.lib
            absl_flags_usage_internal.lib
            absl_graphcycles_internal.lib
            absl_hash.lib
            absl_hashtablez_sampler.lib
            absl_int128.lib
            absl_leak_check.lib
            absl_leak_check_disable.lib
            absl_log_severity.lib
            absl_malloc_internal.lib
            absl_periodic_sampler.lib
            absl_random_distributions.lib
            absl_random_internal_distribution_test_util.lib
            absl_random_internal_platform.lib
            absl_random_internal_pool_urbg.lib
            absl_random_internal_randen.lib
            absl_random_internal_randen_hwaes.lib
            absl_random_internal_randen_hwaes_impl.lib
            absl_random_internal_randen_slow.lib
            absl_random_internal_seed_material.lib
            absl_random_seed_gen_exception.lib
            absl_random_seed_sequences.lib
            absl_raw_hash_set.lib
            absl_raw_logging_internal.lib
            absl_scoped_set_env.lib
            absl_spinlock_wait.lib
            absl_stacktrace.lib
            absl_status.lib
            absl_statusor.lib
            absl_str_format_internal.lib
            absl_strerror.lib
            absl_strings.lib
            absl_strings_internal.lib
            absl_symbolize.lib
            absl_synchronization.lib
            absl_throw_delegate.lib
            absl_time.lib
            absl_time_zone.lib
            absl_wyhash.lib
            address_sorting.lib
            cares.lib
            crypto.lib
            gpr.lib
            grpc.lib
            grpc_plugin_support.lib
            grpc_unsecure.lib
            grpc++.lib
            grpc++_alts.lib
            grpc++_error_details.lib
            grpc++_reflection.lib
            grpc++_unsecure.lib
            grpcpp_channelz.lib
            libprotobuf.lib
            libprotobuf-lite.lib
            libprotoc.lib
            re2.lib
            ssl.lib
            upb.lib
            zlibstatic.lib
        )

    endif()


    target_compile_definitions(PXREARobotSDK PRIVATE PXREAROBOTSDK_LIBRARY)

    add_custom_command(TARGET PXREARobotSDK
        POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${INSTALL_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_BINARY_DIR}/PXREARobotSDK.lib" "${INSTALL_DIR}/PXREARobotSDK.lib"
        COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_BINARY_DIR}/PXREARobotSDK.dll" "${INSTALL_DIR}/PXREARobotSDK.dll"
        COMMAND ${CMAKE_COMMAND} -E copy "${PROJECT_SOURCE_DIR}/PXREARobotSDK.h" "${INSTALL_DIR}/PXREARobotSDK.h"
    )
endif()


if(UNIX)
    if(ISA_NAME STREQUAL "aarch64")
        target_compile_definitions(PXREARobotSDK PUBLIC
            LINUX_aarch64
        )
        set(GRPC_LIB_DIR ${PROJECT_SOURCE_DIR}/../Redistributable/linux_aarch64/grpc/lib)
    else()
        target_compile_definitions(PXREARobotSDK PUBLIC
            LINUX_x86
        )
        set(GRPC_LIB_DIR ${PROJECT_SOURCE_DIR}/../Redistributable/linux/grpc/lib)
    endif()
    set(CMAKE_CXX_STANDARD 17)

    target_compile_definitions(PXREARobotSDK PUBLIC PXREAROBOTSDK_LIBRARY)

    set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} -Wl,--no-undefined")

    # Use absolute paths to avoid linking against conda environment libraries
    target_link_libraries(PXREARobotSDK PUBLIC
        -Wl,--start-group
        ${GRPC_LIB_DIR}/libabsl_bad_any_cast_impl.a
        ${GRPC_LIB_DIR}/libabsl_bad_optional_access.a
        ${GRPC_LIB_DIR}/libabsl_bad_variant_access.a
        ${GRPC_LIB_DIR}/libabsl_base.a
        ${GRPC_LIB_DIR}/libabsl_city.a
        ${GRPC_LIB_DIR}/libabsl_civil_time.a
        ${GRPC_LIB_DIR}/libabsl_cord.a
        ${GRPC_LIB_DIR}/libabsl_cord_internal.a
        ${GRPC_LIB_DIR}/libabsl_cordz_functions.a
        ${GRPC_LIB_DIR}/libabsl_cordz_handle.a
        ${GRPC_LIB_DIR}/libabsl_cordz_info.a
        ${GRPC_LIB_DIR}/libabsl_cordz_sample_token.a
        ${GRPC_LIB_DIR}/libabsl_crc32c.a
        ${GRPC_LIB_DIR}/libabsl_crc_cord_state.a
        ${GRPC_LIB_DIR}/libabsl_crc_cpu_detect.a
        ${GRPC_LIB_DIR}/libabsl_crc_internal.a
        ${GRPC_LIB_DIR}/libabsl_debugging_internal.a
        ${GRPC_LIB_DIR}/libabsl_demangle_internal.a
        ${GRPC_LIB_DIR}/libabsl_die_if_null.a
        ${GRPC_LIB_DIR}/libabsl_examine_stack.a
        ${GRPC_LIB_DIR}/libabsl_exponential_biased.a
        ${GRPC_LIB_DIR}/libabsl_failure_signal_handler.a
        ${GRPC_LIB_DIR}/libabsl_flags_commandlineflag.a
        ${GRPC_LIB_DIR}/libabsl_flags_commandlineflag_internal.a
        ${GRPC_LIB_DIR}/libabsl_flags_config.a
        ${GRPC_LIB_DIR}/libabsl_flags_internal.a
        ${GRPC_LIB_DIR}/libabsl_flags_marshalling.a
        ${GRPC_LIB_DIR}/libabsl_flags_parse.a
        ${GRPC_LIB_DIR}/libabsl_flags_private_handle_accessor.a
        ${GRPC_LIB_DIR}/libabsl_flags_program_name.a
        ${GRPC_LIB_DIR}/libabsl_flags_reflection.a
        ${GRPC_LIB_DIR}/libabsl_flags_usage.a
        ${GRPC_LIB_DIR}/libabsl_flags_usage_internal.a
        ${GRPC_LIB_DIR}/libabsl_graphcycles_internal.a
        ${GRPC_LIB_DIR}/libabsl_hash.a
        ${GRPC_LIB_DIR}/libabsl_hashtablez_sampler.a
        ${GRPC_LIB_DIR}/libabsl_int128.a
        ${GRPC_LIB_DIR}/libabsl_kernel_timeout_internal.a
        ${GRPC_LIB_DIR}/libabsl_leak_check.a
        ${GRPC_LIB_DIR}/libabsl_log_entry.a
        ${GRPC_LIB_DIR}/libabsl_log_flags.a
        ${GRPC_LIB_DIR}/libabsl_log_globals.a
        ${GRPC_LIB_DIR}/libabsl_log_initialize.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_check_op.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_conditions.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_fnmatch.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_format.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_globals.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_log_sink_set.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_message.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_nullguard.a
        ${GRPC_LIB_DIR}/libabsl_log_internal_proto.a
        ${GRPC_LIB_DIR}/libabsl_log_severity.a
        ${GRPC_LIB_DIR}/libabsl_log_sink.a
        ${GRPC_LIB_DIR}/libabsl_low_level_hash.a
        ${GRPC_LIB_DIR}/libabsl_malloc_internal.a
        ${GRPC_LIB_DIR}/libabsl_periodic_sampler.a
        ${GRPC_LIB_DIR}/libabsl_random_distributions.a
        ${GRPC_LIB_DIR}/libabsl_random_internal_distribution_test_util.a
        ${GRPC_LIB_DIR}/libabsl_random_internal_platform.a
        ${GRPC_LIB_DIR}/libabsl_random_internal_pool_urbg.a
        ${GRPC_LIB_DIR}/libabsl_random_internal_randen.a
        ${GRPC_LIB_DIR}/libabsl_random_internal_randen_hwaes.a
        ${GRPC_LIB_DIR}/libabsl_random_internal_randen_hwaes_impl.a
        ${GRPC_LIB_DIR}/libabsl_random_internal_randen_slow.a
        ${GRPC_LIB_DIR}/libabsl_random_internal_seed_material.a
        ${GRPC_LIB_DIR}/libabsl_random_seed_gen_exception.a
        ${GRPC_LIB_DIR}/libabsl_random_seed_sequences.a
        ${GRPC_LIB_DIR}/libabsl_raw_hash_set.a
        ${GRPC_LIB_DIR}/libabsl_raw_logging_internal.a
        ${GRPC_LIB_DIR}/libabsl_scoped_set_env.a
        ${GRPC_LIB_DIR}/libabsl_spinlock_wait.a
        ${GRPC_LIB_DIR}/libabsl_stacktrace.a
        ${GRPC_LIB_DIR}/libabsl_status.a
        ${GRPC_LIB_DIR}/libabsl_statusor.a
        ${GRPC_LIB_DIR}/libabsl_strerror.a
        ${GRPC_LIB_DIR}/libabsl_str_format_internal.a
        ${GRPC_LIB_DIR}/libabsl_strings.a
        ${GRPC_LIB_DIR}/libabsl_strings_internal.a
        ${GRPC_LIB_DIR}/libabsl_string_view.a
        ${GRPC_LIB_DIR}/libabsl_symbolize.a
        ${GRPC_LIB_DIR}/libabsl_synchronization.a
        ${GRPC_LIB_DIR}/libabsl_throw_delegate.a
        ${GRPC_LIB_DIR}/libabsl_time.a
        ${GRPC_LIB_DIR}/libabsl_time_zone.a
        ${GRPC_LIB_DIR}/libabsl_vlog_config_internal.a
        ${GRPC_LIB_DIR}/libaddress_sorting.a
        ${GRPC_LIB_DIR}/libcares.a
        ${GRPC_LIB_DIR}/libcrypto.a
        ${GRPC_LIB_DIR}/libgpr.a
        ${GRPC_LIB_DIR}/libgrpc++.a
        ${GRPC_LIB_DIR}/libgrpc.a
        ${GRPC_LIB_DIR}/libgrpc++_alts.a
        ${GRPC_LIB_DIR}/libgrpc_authorization_provider.a
        ${GRPC_LIB_DIR}/libgrpc++_error_details.a
        ${GRPC_LIB_DIR}/libgrpc_plugin_support.a
        ${GRPC_LIB_DIR}/libgrpcpp_channelz.a
        ${GRPC_LIB_DIR}/libgrpc++_reflection.a
        ${GRPC_LIB_DIR}/libgrpc++_unsecure.a
        ${GRPC_LIB_DIR}/libgrpc_unsecure.a
        ${GRPC_LIB_DIR}/libprotobuf.a
        ${GRPC_LIB_DIR}/libprotobuf-lite.a
        ${GRPC_LIB_DIR}/libprotoc.a
        ${GRPC_LIB_DIR}/libre2.a
        ${GRPC_LIB_DIR}/libssl.a
        ${GRPC_LIB_DIR}/libupb.a
        ${GRPC_LIB_DIR}/libutf8_range.a
        ${GRPC_LIB_DIR}/libutf8_validity.a
        ${GRPC_LIB_DIR}/libz.a
        -Wl,--end-group
        rt
        pthread
        dl
    )

    add_custom_command(TARGET PXREARobotSDK
        POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${INSTALL_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_BINARY_DIR}/libPXREARobotSDK.so" "${INSTALL_DIR}/libPXREARobotSDK.so"
        COMMAND ${CMAKE_COMMAND} -E copy "${PROJECT_SOURCE_DIR}/PXREARobotSDK.h" ${PROJECT_SOURCE_DIR}/../SDK/include/
    )
endif()
