#!/bin/bash
echo "Start incremental package build..."
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
echo $DIR

# 只在必要时创建目录结构
if [ ! -d "$DIR/package" ]; then
    echo "Creating directory structure..."
    mkdir -p $DIR/package/opt/apps/roboticsservice
    mkdir -p $DIR/package/usr/share/applications
    mkdir -p $DIR/package/usr/share/icons
    mkdir -p $DIR/package/DEBIAN
    echo "Directory structure created."
else
    echo "Using existing directory structure."
fi

# 检查控制文件是否已复制
if [ ! -f "$DIR/package/DEBIAN/control" ]; then
    echo "Copying control files..."
    cp $DIR/control $DIR/package/DEBIAN/
    cp $DIR/postinst $DIR/package/DEBIAN/
    cp $DIR/postrm $DIR/package/DEBIAN/
    cp $DIR/prerm $DIR/package/DEBIAN/
    # 确保脚本有执行权限
    chmod +x $DIR/package/DEBIAN/postinst
    chmod +x $DIR/package/DEBIAN/postrm
    chmod +x $DIR/package/DEBIAN/prerm
    echo "Control files copied."
else
    echo "Control files already exist, checking for updates..."
    # 检查控制文件是否有更新
    if [ "$DIR/control" -nt "$DIR/package/DEBIAN/control" ]; then
        echo "Updating control file..."
        cp $DIR/control $DIR/package/DEBIAN/
    fi
    if [ "$DIR/postinst" -nt "$DIR/package/DEBIAN/postinst" ]; then
        echo "Updating postinst script..."
        cp $DIR/postinst $DIR/package/DEBIAN/
        chmod +x $DIR/package/DEBIAN/postinst
    fi
    if [ "$DIR/postrm" -nt "$DIR/package/DEBIAN/postrm" ]; then
        echo "Updating postrm script..."
        cp $DIR/postrm $DIR/package/DEBIAN/
        chmod +x $DIR/package/DEBIAN/postrm
    fi
    if [ "$DIR/prerm" -nt "$DIR/package/DEBIAN/prerm" ]; then
        echo "Updating prerm script..."
        cp $DIR/prerm $DIR/package/DEBIAN/
        chmod +x $DIR/package/DEBIAN/prerm
    fi
fi

# 检查桌面文件是否已复制或有更新
if [ ! -f "$DIR/package/usr/share/applications/roboticsservice.desktop" ] || [ "$DIR/roboticsservice.desktop" -nt "$DIR/package/usr/share/applications/roboticsservice.desktop" ]; then
    echo "Copying/updating desktop file..."
    cp $DIR/roboticsservice.desktop $DIR/package/usr/share/applications/
    echo "Desktop file copied/updated."
fi

# 检查图标是否已复制
if [ ! -d "$DIR/package/usr/share/icons/hicolor" ] || [ "$DIR/hicolor" -nt "$DIR/package/usr/share/icons/hicolor" ]; then
    echo "Copying/updating icons..."
    cp -rf $DIR/hicolor $DIR/package/usr/share/icons/
    echo "Icons copied/updated."
fi

# 检查脚本文件是否已复制或有更新。二进制文件统一从 bin 目录同步。
for script in run2D.sh runRobotDataRecorder.sh run3D.sh runService.sh; do
    if [ ! -f "$DIR/package/opt/apps/roboticsservice/$script" ] || [ "$DIR/$script" -nt "$DIR/package/opt/apps/roboticsservice/$script" ]; then
        echo "Copying/updating $script..."
        cp $DIR/$script $DIR/package/opt/apps/roboticsservice/
        # 确保脚本有执行权限
        chmod +x $DIR/package/opt/apps/roboticsservice/$script
        echo "$script copied/updated."
    fi
done

# 检查二进制文件是否需要更新
BIN_DIR="$DIR/../../bin"
TARGET_DIR="$DIR/package/opt/apps/roboticsservice"

# 始终复制二进制文件，确保包含最新的可执行文件
echo "Copying binary files..."
# 确保目标目录存在
mkdir -p $TARGET_DIR
# 复制所有二进制文件和依赖项
cp -rf $BIN_DIR/* $TARGET_DIR/
# 确保主可执行文件存在并有执行权限
if [ -f "$BIN_DIR/RoboticsServiceProcess" ]; then
    cp -f $BIN_DIR/RoboticsServiceProcess $TARGET_DIR/
    chmod +x $TARGET_DIR/RoboticsServiceProcess
    echo "Main executable RoboticsServiceProcess copied and made executable."
else
    echo "WARNING: Main executable RoboticsServiceProcess not found in $BIN_DIR!"
fi
echo "Binary files copied."

chmod +x $DIR/package/opt/apps/roboticsservice/SDKDemo/RobotUnityDemo/RobotLinuxDemo.x86_64

# 构建 Debian 包
echo "Building Debian package..."
VERSION=$(grep "Version:" $DIR/control | cut -d " " -f 2)
PACKAGE_NAME="XenseVR-PC-Service_${VERSION}_amd64.deb"

cd $DIR
dpkg-deb -b package/ ./$PACKAGE_NAME
echo "Debian package built: $PACKAGE_NAME"

# 确保输出目录存在
mkdir -p $DIR/../output

# 复制 Debian 包到输出目录
echo "Copying package to output directory..."
cp ./$PACKAGE_NAME $DIR/../output/
echo "Package copied to output directory."

# 清理临时文件
rm ./$PACKAGE_NAME
echo "Temporary files cleaned up."

echo "Incremental package build completed successfully."
