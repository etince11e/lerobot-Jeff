#!/bin/bash

# Parse BUILD_NUM - exclude --clean and overseas from being used as version number
BUILD_NUM=""
for arg in "$@"; do
    if [ "$arg" != "--clean" ] && [ "$arg" != "overseas" ]; then
        BUILD_NUM=$arg
        break
    fi
done

# Default to empty if no valid build number provided
echo "BUILD_NUM: $BUILD_NUM"

echo "set qt gcc compile env parameter..."
################################################################################
################################################################################
# Set the path to your Qt installation for GCC 64-bit architecture
if [ -z "$QT_GCC_64" ]; then
    for qt_path in \
        /home/zwg/pro/Qt6/6.6.3/gcc_64 \
        /home/ubuntu/Qt/6.6.3/gcc_64; do
        if [ -f "$qt_path/lib/cmake/Qt6/Qt6Config.cmake" ]; then
            QT_GCC_64=$qt_path
            break
        fi
    done
fi

if [ -z "$QT_GCC_64" ] || [ ! -f "$QT_GCC_64/lib/cmake/Qt6/Qt6Config.cmake" ]; then
    echo "Qt6 gcc_64 path not found. Set QT_GCC_64 to your Qt installation path."
    exit 1
fi

QT_GCC_64=${QT_GCC_64%/}
QT6_TOOLS=${QT6_TOOLS:-$(dirname "$(dirname "$QT_GCC_64")")/Tools}
export QT_GCC_64
export QT6_TOOLS

export PATH=$QT_GCC_64/bin:$PATH
export PATH=$QT_GCC_64/include:$PATH
export PATH=$QT6_TOOLS/QtCreator/bin:$PATH
export PATH=$QT6_TOOLS/CMake/bin:$PATH
#################################################################################
################################################################################

echo "set qt gcc compile env parameter finished."
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd $DIR

PROJECT_DIR=$DIR
RELEASE_DIR=$DIR/RelWithDebInfo

# Create directories if they don't exist (but don't delete if they do)
BinDir="$DIR/bin"
if [ ! -d "$BinDir" ]; then
    mkdir bin
fi

if [ ! -d "$RELEASE_DIR" ]; then
    mkdir RelWithDebInfo
fi

SHOULD_CONFIGURE=0
if [ -f "$RELEASE_DIR/CMakeCache.txt" ]; then
    CACHE_QT_PREFIX=$(grep '^CMAKE_PREFIX_PATH:PATH=' "$RELEASE_DIR/CMakeCache.txt" | cut -d= -f2-)
    if [ "${CACHE_QT_PREFIX%/}" != "$QT_GCC_64" ]; then
        SHOULD_CONFIGURE=1
    fi
fi

# Only configure if CMakeCache.txt doesn't exist or --clean flag is provided
if [ ! -f "$RELEASE_DIR/CMakeCache.txt" ] || [ "$SHOULD_CONFIGURE" = "1" ] || [ "$2" = "--clean" ] || [ "$1" = "--clean" ]; then
    echo "Running CMake configuration..."

    # If --clean flag is provided, remove directories and recreate them
    if [ "$2" = "--clean" ] || [ "$1" = "--clean" ]; then
        echo "Cleaning build directories..."
        rm -rf bin
        mkdir bin
        rm -rf RelWithDebInfo
        mkdir RelWithDebInfo
        echo "Clean completed."
        exit 0
    fi

    if [ "$1" = "overseas" ]; then
        cmake -S $PROJECT_DIR -B $RELEASE_DIR -DBUILD_LIB_PATH:STRING=$QT_GCC_64 -DAUTO_BUILD_NUM:STRING=$BUILD_NUM -DCMAKE_BUILD_TYPE:STRING=RelWithDebInfo -DCMAKE_PREFIX_PATH:PATH=$QT_GCC_64 -DAUTO_BUILD_OVERSEA=ON
    else
        cmake -S $PROJECT_DIR -B $RELEASE_DIR -DBUILD_LIB_PATH:STRING=$QT_GCC_64 -DAUTO_BUILD_NUM:STRING=$BUILD_NUM -DCMAKE_BUILD_TYPE:STRING=RelWithDebInfo -DCMAKE_PREFIX_PATH:PATH=$QT_GCC_64
    fi
fi

# Always build
echo "Building..."
cmake --build $RELEASE_DIR --target all

echo "Build completed."
