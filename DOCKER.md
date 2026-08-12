# Sprite Video Lab – Docker 部署指南

## 前置要求

- **Docker**（20.10+）
- **NVIDIA Container Toolkit**（用于 GPU 加速）
- **NVIDIA 驱动**（≥ 575.x，兼容 CUDA 13.0）
- **Docker Compose**（v2 推荐，已内置在 Docker Desktop 中）

### 验证 GPU 环境

```bash
nvidia-smi                          # 检查驱动版本，确认 >= 575
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi  # 验证 Docker GPU 访问
```

## 基础镜像信息

| 组件 | 版本 |
|---|---|
| PyTorch | 2.9.0 |
| CUDA | 13.0.2 |
| Python | 3.12.7 |
| Base OS | Alinux3.2104 (RHEL 系) |

镜像地址：`ac2-registry.cn-hangzhou.cr.aliyuncs.com/ac2/pytorch:2.9.0.10-cuda13.0.2-py312-alinux3.2104`

> 该镜像托管在阿里云 ACR（杭州），中国大陆拉取速度快。如镜像为私有仓库，请先 `docker login ac2-registry.cn-hangzhou.cr.aliyuncs.com`。

## 快速启动

```bash
cd sprite-video-lab

# 可选：预先拉取基础镜像（约 8–12 GB），避免构建时超时
docker pull ac2-registry.cn-hangzhou.cr.aliyuncs.com/ac2/pytorch:2.9.0.10-cuda13.0.2-py312-alinux3.2104

docker compose up -d --build
```

首次构建会安装 ffmpeg 和 AI 依赖包。构建完成后服务自动在后台启动。

访问地址：[http://127.0.0.1:8894](http://127.0.0.1:8894)

### 查看日志

```bash
docker compose logs -f
```

### 停止服务

```bash
docker compose down
```

## 环境变量

以下变量可在 `docker-compose.yml` 中修改，或通过 `docker compose run -e` 覆盖：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SPRITE_VIDEO_LAB_HOST` | `0.0.0.0` | 服务绑定地址（容器内使用 `0.0.0.0`） |
| `SPRITE_VIDEO_LAB_PORT` | `8894` | 服务端口 |
| `SPRITE_VIDEO_LAB_FFMPEG_DIR` | `/usr/bin` | ffmpeg / ffprobe 所在目录 |
| `SPRITE_VIDEO_LAB_AI_MODEL_CACHE` | `/app/ai-cache` | Hugging Face 模型缓存目录 |

其他可选环境变量（如需调整可自行添加到 `docker-compose.yml` 的 `environment` 段）：

- `SPRITE_VIDEO_LAB_FFMPEG_ACCEL` — 硬件加速模式，Docker 中建议保持默认或设为 `cpu`
- `SPRITE_VIDEO_LAB_REALESRGAN_BIN` — MAGIC 超分使用的 realesrgan-ncnn-vulkan 路径
- `SPRITE_VIDEO_LAB_CORRIDORKEY_ROOT` — CorridorKey 项目目录

## 数据持久化

两个命名卷用于持久化数据，容器删除后数据不丢失：

| 卷名 | 容器路径 | 内容 |
|---|---|---|
| `sprite-video-lab-work` | `/app/work` | 上传文件、处理结果、导出帧 |
| `sprite-video-lab-ai-cache` | `/app/ai-cache` | Hugging Face AI 模型缓存 |

查看卷占用空间：

```bash
docker system df -v | grep sprite-video-lab
```

## 首次使用注意事项

1. **AI 模型下载**：首次使用 BiRefNet 抠图或 MAGIC 超分时，模型会自动从 Hugging Face 下载到 `/app/ai-cache`。下载期间前端可能无响应，查看日志确认进度。
2. **GPU 不可用时回退 CPU**：如果 GPU 不可用，AI 功能会自动回退到 CPU 推理，速度较慢但仍可用。日志中会打印设备选择信息。
3. **ffmpeg 硬件加速**：Docker 中 GPU 硬件解码配置较复杂，建议让 ffmpeg 使用默认解码器（自动选择软件解码）。
4. **Alinux3 系统**：基础镜像使用 Alibaba Cloud Linux 3（RHEL 系），包管理器为 `yum`，Python 命令为 `python3`。

## 故障排查

### 端口被占用

如果 8894 端口已被占用，修改 `docker-compose.yml` 的端口映射：

```yaml
ports:
  - "127.0.0.1:8895:8894"   # 将 8895 改为你需要的端口
```

### GPU 不可用

确认 nvidia-container-toolkit 安装正确：

```bash
nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### CUDA 13.0 驱动不兼容

如果驱动不满足 CUDA 13.0 的要求（≥ 575.x），有以下选择：

1. **升级驱动** — 从 [NVIDIA 官网](https://www.nvidia.com/drivers) 下载最新驱动
2. **忽略 GPU** — 修改 `docker-compose.yml`，删除 `deploy.resources.reservations.devices` 段，AI 将回退 CPU
3. **回退基础镜像** — 换回 `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime`（需 CUDA 12.4 驱动 ≥ 550.x）

### 构建失败（网络问题）

如果 pip install 或 yum install 超时，可为 Docker 配置代理：

```yaml
build:
  context: .
  dockerfile: Dockerfile
  args:
    - HTTP_PROXY=http://proxy:port
    - HTTPS_PROXY=http://proxy:port
```

## 与 Windows 本地运行的差异

| 方面 | Windows 本地 | Docker (ACR) |
|---|---|---|
| 基础系统 | Windows | Alinux3.2104 (RHEL 系) |
| Python 版本 | 3.10+ | 3.12.7 |
| PyTorch 版本 | 按需安装 | 2.9.0 预装 |
| CUDA 版本 | 取决于本地驱动 | 13.0.2 |
| ffmpeg 路径 | 手动配置 `SPRITE_VIDEO_LAB_FFMPEG_DIR` | 固定为 `/usr/bin` |
| GPU 加速 | 支持 CUDA、QSV、D3D11VA 等多后端 | 仅 CUDA（通过 nvidia-docker） |
| AI 模型缓存 | `%USERPROFILE%\.cache\huggingface` | `/app/ai-cache`（卷持久化） |
| 包管理器 | 无需（独立 Python） | yum (RHEL 系) |
| 启动脚本 | `start_sprite_video_lab.bat` | `docker compose up -d` |

## 许可证

本项目基于 [MIT 许可证](./LICENSE)。Docker 镜像中使用的 PyTorch、CUDA、cuDNN 等软件受其各自的许可证约束。

---

详细使用说明见 [README.md](./README.md)（中文）和 [USAGE.md](./USAGE.md)（英文）。
