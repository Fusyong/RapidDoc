# RapidDoc ah21 便携包 — 打包与使用说明

本文说明如何将 ah21 定制版打成可拷贝的便携目录，以及如何传给他人使用。  
定制文件均带 `ah21` 后缀，不改上游结构；勿向 RapidAI 上游提交这些文件。

---

## 一、目录里有什么

| 路径 | 说明 |
|------|------|
| `gui_ah21.py` | 图形界面（选文件、method、lang） |
| `demo_ah21.py` | 解析逻辑入口 |
| `RapidDoc_ah21.bat` | 启动脚本（开发 / 便携均可） |
| `build_portable_ah21.ps1` | 一键生成便携包 |
| `output_portable_ah21\` | 构建产物（已由 `output*/` 规则忽略，不会进 git） |

便携包解压后的结构：

```text
output_portable_ah21\          （或你改名后的文件夹）
  Python\                      # 便携 Python（含依赖）
  app\                         # 程序源码
  models\                      # 模型目录（可空，见下文）
  RapidDoc_ah21.bat            # 双击启动
  requirements_ah21_freeze.txt # 依赖清单备份（参考用）
```

---

## 二、本机开发使用（不打包）

在仓库根目录任选其一：

1. 双击 `RapidDoc_ah21.bat`（自动使用 `.venv`）
2. 或在已激活的虚拟环境中执行：

```text
python gui_ah21.py
```

界面中可设置：

- **输入文件**：PDF / 图片等  
- **method**：`auto` / `txt` / `ocr`  
- **lang**：`ch` / `chinese_cht` / `en` / `korean` / `japan` / `ta` / `te` / `ka`  
- **输出目录**：默认同输入文件所在目录  

可选环境变量：

| 变量 | 作用 |
|------|------|
| `RAPID_MODELS_DIR` | 模型目录 |
| `AH21_CJK_FONT` | 双层 PDF 用的中文字体文件路径（不设则自动找微软雅黑等） |

---

## 三、打包成便携目录

### 前提

- 已在仓库根目录建好 `.venv`，且依赖安装完整（能正常跑 `gui_ah21.py`）。
- 使用 **Windows PowerShell**，在仓库根目录执行。

### 完整构建（首次或依赖有变）

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable_ah21.ps1
```

脚本会：

1. 复制当前 `.venv` 所用的基础 Python → `output_portable_ah21\Python\`
2. 复制 `.venv\Lib\site-packages` → 便携 Python（比重新 pip 安装更快、更稳）
3. 复制运行所需源码 → `app\`
4. 创建 `models\`，并写入启动脚本

### 同时打入模型（推荐离线分发）

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable_ah21.ps1 -SourceModelsDir "你的模型目录完整路径"
```

也可先设置环境变量再构建：

```powershell
$env:RAPID_MODELS_DIR = "你的模型目录完整路径"
powershell -ExecutionPolicy Bypass -File .\build_portable_ah21.ps1
```

### 只刷新程序源码（依赖未变）

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable_ah21.ps1 -SkipPipInstall
```

不会重拷 Python / site-packages，适合改完 `gui_ah21.py` 等后快速更新便携包。

---

## 四、压缩并传给他人

1. 确认 `output_portable_ah21\` 已构建完成（有模型需求则 `models\` 非空）。
2. 压缩整个文件夹，例如：

```powershell
Compress-Archive -Path .\output_portable_ah21\* -DestinationPath .\RapidDoc_ah21_portable.zip -CompressionLevel Optimal
```

或在资源管理器中对 `output_portable_ah21` 右键压缩。

3. 通过网盘、U 盘等传递 zip（体积通常很大，含 Python 与依赖；含模型时更大）。

**传的是便携包，不是整个 git 仓库。**

---

## 五、对方如何使用

1. 解压到任意目录（路径尽量短，避免权限受限的目录）。
2. 双击 **`RapidDoc_ah21.bat`**。
3. 在窗口中选择文件、method、lang，点击「开始处理」。
4. 到输出目录查看结果（Markdown、双层 PDF 等）。

### 对方环境要求

- 64 位 Windows  
- 一般无需单独装 Python  
- 系统通常已有微软雅黑等字体；若双层 PDF 中文异常，可设置 `AH21_CJK_FONT` 指向字体文件  

### 若没有打进模型

- 首次运行可能需联网，由程序按上游逻辑下载模型到 `models\`；或  
- 由你另行提供 `models` 文件夹，解压后放到与 `RapidDoc_ah21.bat` 同级的 `models\` 下。

---

## 六、与上游同步时注意

- 只维护带 `ah21` 的文件，不要改上游已有文件名对应的内容。  
- 同步上游示例：`git fetch upstream` 后 `git merge upstream/main`。  
- 不要向 RapidAI/RapidDoc 上游提包含 ah21 定制的 PR。  

---

## 七、常见问题

**启动报错找不到 Python / gui**  
确认是解压后的便携目录里双击 bat，且存在 `Python\python.exe` 与 `app\gui_ah21.py`。

**`MagikaError: model dir not found ... magika\models\...`**  
说明 `app\rapid_doc\model\magika\models` 未打进包。请用较新的 `build_portable_ah21.ps1` 重新执行（不要排除该目录），或手动从仓库拷贝该目录到便携包对应路径。

**bat 窗口中文乱码 /「文件名、目录名或卷标语法不正确」**  
旧版 bat 含中文提示，在默认代码页下可能乱码并误伤命令。请使用仓库中已改为英文提示的 `RapidDoc_ah21.bat`，并复制到便携包根目录覆盖。

**处理很慢或显存/内存不足**  
大 PDF、OCR、表格公式都会较吃资源；可先用较少页的文件试跑，或换 method。

**中文在双层 PDF 里显示异常**  
设置环境变量 `AH21_CJK_FONT` 为某 CJK 字体路径，例如：  
`C:\Windows\Fonts\msyh.ttc`

**重新打包后对方仍是旧版**  
确认压缩的是最新的 `output_portable_ah21`；改代码后至少执行过带或不带 `-SkipPipInstall` 的构建脚本。
