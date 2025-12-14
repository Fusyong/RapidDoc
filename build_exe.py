#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RapidDoc CLI工具打包脚本
使用PyInstaller将CLI工具打包成exe文件
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path


def check_dependencies():
    """检查必要的依赖"""
    print("检查依赖...")
    try:
        import PyInstaller
        print(f"✓ PyInstaller 已安装: {PyInstaller.__version__}")
    except ImportError:
        print("✗ PyInstaller 未安装")
        print("正在安装 PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller 安装完成")

    # 检查UPX（可选，用于压缩）
    upx_path = shutil.which("upx")
    if upx_path:
        print(f"✓ UPX 已找到: {upx_path}")
    else:
        print("⚠ UPX 未找到（可选，用于进一步压缩exe文件）")
        print("  可以从 https://upx.github.io/ 下载UPX")


def clean_build_dirs():
    """清理之前的构建目录"""
    print("\n清理构建目录...")
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"✓ 已删除: {dir_name}")

    # 清理spec文件生成的缓存
    spec_cache = Path('rapiddoc_cli.spec').parent / 'rapiddoc_cli'
    if spec_cache.exists():
        shutil.rmtree(spec_cache)
        print(f"✓ 已清理spec缓存")


def build_exe():
    """构建exe文件"""
    print("\n开始构建exe文件...")
    print("这可能需要几分钟时间，请耐心等待...\n")

    # 使用spec文件构建
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",  # 清理临时文件
        "rapiddoc_cli.spec"
    ]

    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print("\n✓ 构建完成！")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n✗ 构建失败: {e}")
        return False


def show_results():
    """显示构建结果"""
    dist_dir = Path("dist")
    if dist_dir.exists():
        exe_files = list(dist_dir.glob("*.exe"))
        if exe_files:
            print("\n" + "="*60)
            print("构建成功！")
            print("="*60)
            for exe_file in exe_files:
                size_mb = exe_file.stat().st_size / (1024 * 1024)
                print(f"\n输出文件: {exe_file}")
                print(f"文件大小: {size_mb:.2f} MB")
            print("\n使用说明:")
            print("  1. 将exe文件复制到任意目录")
            print("  2. 在命令行中运行: rapiddoc.exe input.pdf -o output/")
            print("  3. 查看帮助: rapiddoc.exe --help")
            print("\n注意:")
            print("  - 首次运行时，模型文件会自动下载到用户目录")
            print("  - 可以通过环境变量 RAPID_MODELS_DIR 指定模型存储目录")
            print("="*60)
        else:
            print("\n⚠ 未找到生成的exe文件")
    else:
        print("\n⚠ dist目录不存在")


def main():
    """主函数"""
    print("="*60)
    print("RapidDoc CLI工具 - 打包脚本")
    print("="*60)

    # 检查当前目录
    if not Path("cli_tool.py").exists():
        print("✗ 错误: 未找到 cli_tool.py")
        print("  请在项目根目录运行此脚本")
        sys.exit(1)

    if not Path("rapiddoc_cli.spec").exists():
        print("✗ 错误: 未找到 rapiddoc_cli.spec")
        print("  请确保spec文件存在")
        sys.exit(1)

    # 检查依赖
    check_dependencies()

    # 清理旧文件
    clean_build_dirs()

    # 构建
    if build_exe():
        show_results()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

