# RapidDoc CLI工具打包说明

本文档说明如何将RapidDoc CLI工具打包成Windows exe可执行文件。

## 前置要求

1. **Python环境**: Python 3.10-3.13
2. **依赖安装**: 确保已安装所有项目依赖
   ```bash
   pip install -e .[cpu]  # 或 [gpu] 如果需要GPU支持
   ```

## 快速开始

### 方法1: 使用打包脚本（推荐）

```bash
python build_exe.py
```

脚本会自动：
- 检查并安装PyInstaller（如需要）
- 清理旧的构建文件
- 使用优化配置打包
- 显示结果和文件大小

### 方法2: 手动打包

```bash
# 1. 安装PyInstaller
pip install pyinstaller

# 2. 使用spec文件打包
pyinstaller --clean rapiddoc_cli.spec

# 3. 生成的exe文件在 dist/ 目录
```

## 优化打包大小

### 已实施的优化

1. **排除不必要的模块**: 在spec文件中排除了测试、开发工具、Web框架等
2. **UPX压缩**: 启用UPX压缩进一步减小体积（如果可用）
3. **隐藏导入优化**: 只包含必要的模块

### 进一步优化建议

如果生成的exe仍然较大，可以考虑：

1. **使用UPX压缩**:
   - 下载UPX: https://upx.github.io/
   - 将upx.exe添加到PATH
   - spec文件中已启用UPX压缩

2. **排除更多模块**:
   - 如果不需要某些功能，可以在spec文件的`excludes`列表中添加
   - 例如：如果只处理PDF，可以排除图片处理相关模块

3. **使用--onefile模式**:
   - 当前配置已使用onefile模式
   - 如果文件太大，可以考虑使用onedir模式（修改spec文件）

4. **模型文件外置**:
   - 模型文件默认会下载到用户目录
   - 可以通过环境变量`RAPID_MODELS_DIR`指定模型目录
   - 这样exe文件本身不包含模型，体积更小

## 使用打包后的exe

### 基本用法

```bash
# 单个文件
rapiddoc.exe input.pdf -o output/

# 多个文件
rapiddoc.exe file1.pdf file2.pdf -o output/

# 指定解析方法
rapiddoc.exe input.pdf -o output/ --method ocr

# 指定页面范围
rapiddoc.exe input.pdf -o output/ --start-page 0 --end-page 10

# 禁用某些功能以加快速度
rapiddoc.exe input.pdf -o output/ --no-formula --no-table
```

### 查看帮助

```bash
rapiddoc.exe --help
```

### 环境变量

- `RAPID_MODELS_DIR`: 指定模型文件存储目录
- `MINERU_DEVICE_MODE`: 指定设备模式（cuda/cpu等）

## 常见问题

### 1. 打包失败

**问题**: 提示缺少某些模块

**解决**: 
- 确保所有依赖都已安装
- 检查spec文件中的`hiddenimports`列表
- 尝试添加缺失的模块到hiddenimports

### 2. exe文件太大

**问题**: 生成的exe文件超过500MB

**解决**:
- 这是正常的，因为包含了所有依赖库和模型推理引擎
- 使用UPX压缩可以减小约30-50%体积
- 考虑使用onedir模式，将依赖分离到文件夹

### 3. 运行时错误

**问题**: exe运行时提示缺少DLL

**解决**:
- 确保安装了Visual C++ Redistributable
- 检查spec文件中的binaries配置
- 可能需要手动添加某些DLL到binaries列表

### 4. 模型下载问题

**问题**: 首次运行时模型下载失败

**解决**:
- 检查网络连接
- 可以手动下载模型到`RAPID_MODELS_DIR`目录
- 模型下载地址通常在rapid_doc的文档中

### 5. FileNotFoundError: default_models.yaml

**问题**: 运行时提示找不到 `rapidocr\default_models.yaml`

**解决**:
- 这是数据文件未被打包的问题
- 已更新spec文件自动收集rapidocr的数据文件
- 如果仍有问题，检查spec文件中的数据文件收集部分
- 确保rapidocr包已正确安装

## 文件说明

- `cli_tool.py`: CLI工具主程序
- `rapiddoc_cli.spec`: PyInstaller配置文件
- `build_exe.py`: 自动化打包脚本
- `BUILD_README.md`: 本文档

## 改进建议

相比原始的demo.py，CLI工具做了以下改进：

1. **命令行参数**: 使用argparse提供完整的命令行接口
2. **错误处理**: 更好的错误提示和处理
3. **日志控制**: 支持verbose和quiet模式
4. **灵活性**: 可以控制各种输出选项
5. **批量处理**: 支持一次处理多个文件
6. **页面范围**: 支持指定处理的页面范围

## 许可证

与RapidDoc项目保持一致（Apache-2.0）

