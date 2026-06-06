# Sprite Video Lab

Sprite Video Lab 是一个本地网页工具，用来把视频片段、单张图片或已有序列帧整理成干净的 2D Sprite 资源。

它适合这些工作流：

- 管理本地生图候选资产、提示词、项目分类和生成来源。
- 使用 OpenAI 或 ToioTo 生成图片候选，并把结果记录到本地 SQLite。
- 从资产库一键把图片送入动作帧处理，不需要重新上传。
- 导入本地视频、图片或动画序列帧。
- 截取有用的帧范围。
- 按固定间隔抽帧。
- 去除纯色背景、绿幕/蓝幕背景或 AI 生成背景。
- 用 Luma 保留发光、火焰、闪电、粒子等亮部特效。
- 统一帧尺寸，支持自动宽度画布或方形落地/居中画布。
- 导出透明 PNG 帧、Sprite Sheet、JSON manifest 和 zip 包。

项目优先服务 Windows 本地工作流，但运行时很轻：Python、Pillow、ffmpeg，以及原生 HTML/CSS/JavaScript。

## 功能

- 本地路径导入和拖拽上传。
- 视频区间预览，支持按帧设置起止位置。
- 批处理前先单帧预览参数效果。
- 自动宽度居中画布，适合横向连招、特效条、多姿态行。
- 纯色/绿幕抠图，支持阈值、软边、去色溢出和 Halo 收缩。
- BiRefNet AI 主体抠图。
- Luma 亮度抠图，用来保留发光、火焰、闪电、粒子和亮部 VFX。
- CorridorKey 绿幕/蓝幕边缘精修和前景颜色重建。
- `BiRefNet + Luma + CorridorKey` 三管齐下模式。
- 主体保护预设，减少 BiRefNet/Luma 把主体内部抠成半透明的问题。
- 单帧预览支持原始抽帧全分辨率查看，处理后预览可切换棋盘格或指定纯色背景。
- 预览和批处理后处理：残绿涂黑、半透明像素涂黑。
- 可直接导入已有动画序列帧，按文件名顺序预览和导出。
- 反向动画预览和反向导出。
- 帧选择、动画预览、Sprite Sheet 导出、zip 导出和 JSON manifest 导出。
- 生图资产库：
  - 支持 OpenAI 和 ToioTo 两种来源。
  - 支持文本生图和参考图生图。
  - API key 可在页面保存到工具目录的 `.env`，前端不会回显已保存 key。
  - 图片、缩略图和 `asset_lab.sqlite` 保存在本机资产库工作区。
  - 支持手动创建项目分类，记录资产类型、组件类型、尺寸、背景、透明状态、路径、提示词和来源。
  - 资产卡片和生成结果支持“去处理”，可直接进入动作帧处理页。

## 抠图模式

Sprite Video Lab 目前提供这些背景处理模式：

- `我的绿幕抠图算法`：快速处理受控纯色背景，适合绿幕、蓝幕、白底、灰底等素材。
- `只用 BiRefNet`：AI 主体抠图，适合非纯色背景或生成图背景。
- `只用 CorridorKey`：先用绿幕算法生成粗 alpha，再用 CorridorKey 重建边缘和前景颜色。
- `只用 Luma`：基于亮度生成 alpha，适合亮部特效、火焰、闪电、粒子等素材。
- `BiRefNet + CorridorKey`：BiRefNet 先给主体 alpha，再用 CorridorKey 做绿幕/蓝幕边缘重建。
- `BiRefNet + Luma`：主体 alpha 加亮度 alpha，适合 VFX 比较重的 Sprite。
- `BiRefNet + Luma + CorridorKey`：先合成主体 alpha 和亮度 alpha，再用 CorridorKey 做边缘/颜色重建。
- `不抠图`：素材已经带透明通道时，只做缩放、对齐和导出。

灰底、白底、黑底素材通常不需要去色溢出；绿幕/蓝幕素材再开启 despill 和 CorridorKey 会更稳。

## 环境要求

- Python 3.10+
- Pillow
- ffmpeg / ffprobe
- 可选 AI 环境：
  - PyTorch
  - torchvision
  - transformers
  - huggingface-hub
  - timm 和相关图片依赖
  - CorridorKey 依赖，例如 `safetensors`、OpenCV、NumPy

基础功能只需要 `requirements.txt`。BiRefNet、Luma 组合和 CorridorKey 相关能力需要 `requirements-ai.txt` 里的可选依赖。

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/sparklecatta-lang/sprite-video-lab.git
cd sprite-video-lab
```

### 2. 安装基础依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 安装 ffmpeg

把 `ffmpeg` 和 `ffprobe` 放到 `PATH`。

如果你使用独立 ffmpeg 目录，可以这样指定：

```powershell
$env:SPRITE_VIDEO_LAB_FFMPEG_DIR="D:\ffmpeg\bin"
```

### 4. 可选：安装 AI 抠图环境

Windows 下运行：

```bat
setup_ai_runtime.bat
```

脚本会创建单独的 AI Python 环境，并安装 BiRefNet 和 CorridorKey 所需依赖。模型缓存目录可以这样覆盖：

```bat
set SPRITE_VIDEO_LAB_AI_MODEL_CACHE=<model-cache-dir>
```

CorridorKey 源码和 checkpoint 目录可以这样覆盖：

```bat
set SPRITE_VIDEO_LAB_CORRIDORKEY_ROOT=<corridorkey-dir>
```

也可以指定服务启动时使用的 Python：

```bat
set SPRITE_VIDEO_LAB_PYTHON=<python-runtime>
```

更多说明见 [AI_MATTING.md](./AI_MATTING.md)。

### 5. 启动

Windows 下直接运行：

```bat
start_sprite_video_lab.bat
```

或在终端运行：

```bash
python server.py
```

默认地址：

```text
http://127.0.0.1:8894
```

开发时也可以显式指定监听地址：

```bash
python server.py --host 127.0.0.1 --port 8894
```

默认 `python server.py` 会启动一个文件监听父进程，再启动一个真正提供 HTTP 服务的子进程。任务管理器或 `Get-CimInstance Win32_Process` 中看到两个 `python.exe` 属于正常现象；只有一个子进程会监听 `8894` 端口。若只想单次运行 HTTP 服务，不需要热重载，可以使用：

```bash
python server.py --serve --host 127.0.0.1 --port 8894
```

Windows 可用下面的命令确认当前监听进程：

```powershell
Get-NetTCPConnection -LocalPort 8894 -State Listen
```

### 6. 配置生图来源

生图资产库支持在页面的“来源与设置”中保存 API key。保存后会写入工具目录的 `.env`，不会在前端回填明文 key。

也可以手动创建 `.env`：

```dotenv
TOIOTO_API_KEY=你的_ToioTo_key
OPENAI_API_KEY=你的_OpenAI_key
```

ToioTo key 获取入口：

```text
https://sub2api.toioto.org/register?aff=EYMPMLL9BLS5
```

OpenAI key 获取入口：

```text
https://platform.openai.com/api-keys
```

ToioTo 当前页面文案标注：`image2 生图：0.015 元/张`。实际价格以服务提供方页面为准。

## 使用说明

完整的导入、截取、抠图模式、Luma 主体保护、CorridorKey 精修、后处理、动画预览、反向导出和排错说明见：

- [中文使用说明](./USAGE.zh-CN.md)
- [English usage guide](./USAGE.md)

## 环境变量

- `SPRITE_VIDEO_LAB_HOST`
  - 默认：`127.0.0.1`
- `SPRITE_VIDEO_LAB_PORT`
  - 默认：`8894`
- `SPRITE_VIDEO_LAB_FFMPEG_DIR`
  - 可选，包含 `ffmpeg(.exe)` 和 `ffprobe(.exe)` 的目录
- `SPRITE_VIDEO_LAB_FFMPEG_ACCEL`
  - 可选，支持 `auto`、`cpu`、`cuda`、`qsv`、`d3d11va`、`dxva2`
- `SPRITE_VIDEO_LAB_AI_MODEL_CACHE`
  - 可选，Hugging Face / AI 模型缓存目录
- `SPRITE_VIDEO_LAB_CORRIDORKEY_ROOT`
  - 可选，CorridorKey checkout 和 checkpoint 目录
- `SPRITE_VIDEO_LAB_PYTHON`
  - 可选，启动器使用的 Python 可执行文件
- `SPRITE_VIDEO_LAB_WORKSPACE`
  - 可选，生图资产库工作区。默认在用户本地应用数据目录下，例如 `%LOCALAPPDATA%\SpriteVideoLab\workspace`
- `TOIOTO_API_KEY`
  - 可选，ToioTo 生图来源 key
- `OPENAI_API_KEY`
  - 可选，OpenAI 生图来源 key

也可以从命令行覆盖 host 和 port：

```bash
python server.py --host 127.0.0.1 --port 8894
```

## 项目结构

```text
app/                              前端 UI 和浏览器逻辑
asset_lab/                        生图资产库配置、数据库、图片保存和 provider 适配
docs/                             生图和资产库相关说明
server.py                         本地 HTTP 服务和处理流水线
requirements.txt                  基础运行依赖
requirements-ai.txt               可选 AI 抠图依赖
setup_ai_runtime.bat              Windows AI 环境安装脚本
start_sprite_video_lab.bat        Windows 启动器
start_sprite_video_lab_portable.bat 便携版启动器
build_portable_bundle.ps1         便携版打包脚本
work/                             运行时输出目录，已被 git 忽略
tests/                            自动化测试
```

## 验证与排错

修改后建议运行：

```bash
python -m pytest tests\asset_lab -q
node --check app\app.js
python -m compileall server.py asset_lab tests -q
```

常见排查：

- 页面打不开：确认 `http://127.0.0.1:8894` 是否有进程监听。
- API 改动后仍然 404：重启服务。热重载只会在文件监听进程正常时自动刷新子进程。
- 导入视频报 `ffprobe.exe` 相关错误：确认 `SPRITE_VIDEO_LAB_FFMPEG_DIR` 指向包含 `ffmpeg.exe` 和 `ffprobe.exe` 的目录，或把它们放入 `PATH`。
- 生图提示 key 无效：确认页面“来源与设置”中保存的是对应 provider 的 key，且 `.env` 没有被旧值覆盖。
- 资产库图片无法预览：确认 `SPRITE_VIDEO_LAB_WORKSPACE` 没有变更，数据库记录里的文件仍在本机工作区内。

## 注意事项

- 不要把 `work/`、生成帧、测试视频、模型缓存和虚拟环境提交到 git。
- 不要提交 `.env`。可以提交 `.env.example`，但里面不要放真实 key。
- 生图资产库默认把图片和数据库放在本机工作区，不会把素材复制进当前代码项目。
- AI 模型会在第一次选择相关模式时由本地运行时下载。
- BiRefNet 通过 Hugging Face 的 `trust_remote_code=True` 加载远程模型代码；如果需要更严格的供应链控制，请审查并固定模型 revision。
- CorridorKey 是独立项目，重新分发或用于商业推理服务前请确认它的许可证。

## English

This README is Chinese-first. For English instructions, see [USAGE.md](./USAGE.md).

## License

[MIT](./LICENSE)
