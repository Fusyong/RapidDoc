# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 配置文件 - RapidDoc CLI工具
优化打包大小，排除不必要的模块
"""

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# 收集所有子模块
hiddenimports = []

# RapidDoc相关模块
rapid_doc_modules = collect_submodules('rapid_doc')
hiddenimports.extend(rapid_doc_modules)

# RapidOCR相关模块
try:
    rapidocr_modules = collect_submodules('rapidocr')
    hiddenimports.extend(rapidocr_modules)
except:
    pass

# 其他可能需要的隐藏导入
hiddenimports.extend([
    'pypdfium2',
    'pypdfium2._pypdfium',
    'pdfminer',
    'pdfminer.six',
    'skimage',
    'skimage.io',
    'skimage.transform',
    'skimage.filters',
    'skimage.morphology',
    'skimage.measure',
    'skimage.segmentation',
    'skimage.color',
    'skimage.util',
    'skimage.draw',
    'cv2',
    'numpy',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'matplotlib',
    'matplotlib.backends.backend_agg',
    'matplotlib.figure',
    'matplotlib.pyplot',
    'shapely',
    'shapely.geometry',
    'shapely.ops',
    'tokenizers',
    'fast_langdetect',
    'json_repair',
    'ftfy',
    'beautifulsoup4',
    'bs4',
    'pydantic',
    'onnxruntime',
    'openvino',
    'torch',
    'torchvision',
    'loguru',
    'tqdm',
    'boto3',
    'requests',
    'reportlab',
    'pdftext',
    'pypdf',
    'omegaconf',
    'omegaconf.omegaconf',
    'yaml',
    'unittest',
    'unittest.mock',
    'numpy.testing',
    'scipy',
    'scipy.spatial',
    'scipy.sparse',
])

# 收集数据文件
datas = []

# RapidDoc资源文件
try:
    rapid_doc_datas = collect_data_files('rapid_doc')
    datas.extend(rapid_doc_datas)
except:
    pass

# RapidOCR资源文件（包括yaml配置文件）
try:
    rapidocr_datas = collect_data_files('rapidocr')
    datas.extend(rapidocr_datas)
except:
    pass

# fast-langdetect资源文件（FastText模型）
try:
    fast_langdetect_datas = collect_data_files('fast_langdetect')
    datas.extend(fast_langdetect_datas)
    print(f"已收集fast_langdetect数据文件: {len(fast_langdetect_datas)} 个")
except Exception as e:
    print(f"警告: 无法自动收集fast_langdetect数据文件: {e}")
    pass

# 手动添加fast-langdetect的FastText模型文件
try:
    import fast_langdetect
    from pathlib import Path
    fast_langdetect_path = Path(fast_langdetect.__file__).parent

    # 查找lid.176.ftz文件
    ftz_files = list(fast_langdetect_path.rglob('lid.176.ftz'))
    if ftz_files:
        for ftz_file in ftz_files:
            rel_path = ftz_file.relative_to(fast_langdetect_path)
            datas.append((str(ftz_file), f'fast_langdetect/{rel_path.parent}'))
            print(f"已添加FastText模型: {ftz_file} -> fast_langdetect/{rel_path.parent}/")
    else:
        print("警告: 未找到fast_langdetect的lid.176.ftz文件")

except Exception as e:
    print(f"警告: 无法手动添加fast_langdetect模型文件: {e}")
    import traceback
    traceback.print_exc()
    pass

# 手动添加可能缺失的rapidocr数据文件
try:
    import rapidocr
    from pathlib import Path
    rapidocr_path = Path(rapidocr.__file__).parent

    # 添加default_models.yaml（在rapidocr根目录）
    yaml_file = rapidocr_path / 'default_models.yaml'
    if yaml_file.exists():
        datas.append((str(yaml_file), 'rapidocr'))
        print(f"已添加: {yaml_file} -> rapidocr/")

    # 添加networks目录下的所有yaml文件
    networks_dir = rapidocr_path / 'networks'
    if networks_dir.exists() and networks_dir.is_dir():
        for yaml_file in networks_dir.rglob('*.yaml'):
            rel_path = yaml_file.relative_to(rapidocr_path)
            datas.append((str(yaml_file), f'rapidocr/{rel_path.parent}'))
            print(f"已添加: {yaml_file} -> rapidocr/{rel_path.parent}/")

    # 添加configs目录（如果存在）
    configs_dir = rapidocr_path / 'configs'
    if configs_dir.exists() and configs_dir.is_dir():
        for yaml_file in configs_dir.rglob('*.yaml'):
            rel_path = yaml_file.relative_to(rapidocr_path)
            datas.append((str(yaml_file), f'rapidocr/{rel_path.parent}'))
            print(f"已添加: {yaml_file} -> rapidocr/{rel_path.parent}/")

except Exception as e:
    print(f"警告: 无法自动收集rapidocr数据文件: {e}")
    import traceback
    traceback.print_exc()
    pass

# 排除不必要的模块以减小体积
excludes = [
    # 测试相关（注意：不要排除unittest，因为numpy.testing等模块需要它）
    'pytest',
    # 'unittest',  # 不能排除，numpy.testing需要它
    'test',
    'tests',
    # 开发工具
    'IPython',
    'jupyter',
    'notebook',
    # Web框架（如果不需要）
    'flask',
    'django',
    'fastapi',
    'uvicorn',
    'gradio',
    # 其他不需要的
    'tkinter',
    'matplotlib.tests',
    'numpy.tests',
    'scipy.tests',
    'pandas.tests',
    # 文档生成
    'sphinx',
    # 'pydoc',
]

a = Analysis(
    ['cli_tool.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 优化：使用UPX压缩（如果可用）
# 注意：需要先安装UPX，并且某些DLL可能无法压缩
# upx_exclude = [
#     'vcruntime140.dll',
#     'python*.dll',
# ]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='rapiddoc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # 启用UPX压缩以减小体积
    upx_exclude=[],  # 排除无法压缩的文件
    runtime_tmpdir=None,
    console=True,  # 命令行工具，显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加图标文件路径
)

