# Sprite Video Lab 0.2.0 – Docker image (CUDA GPU)
# Base: Alibaba Cloud ACR PyTorch 2.9.0 + CUDA 13.0.2 + Python 3.12
FROM ac2-registry.cn-hangzhou.cr.aliyuncs.com/ac2/pytorch:2.9.0.10-cuda13.0.2-py312-alinux3.2104

# Environment defaults (can be overridden at runtime)
ENV SPRITE_VIDEO_LAB_FFMPEG_DIR=/usr/bin
ENV SPRITE_VIDEO_LAB_AI_MODEL_CACHE=/app/ai-cache

# Install build tools + ffmpeg dependencies, then compile ffmpeg from source
RUN yum install -y gcc gcc-c++ make nasm yasm pkgconfig diffutils         bzip2 which         libx264-devel libx265-devel libvpx-devel         freetype-devel fontconfig-devel fribidi-devel         harfbuzz-devel libxml2-devel         openssl-devel         && git clone --depth 1 https://gitee.com/mirrors/ffmpeg.git /tmp/ffmpeg-src         && cd /tmp/ffmpeg-src         && ./configure           --prefix=/usr           --enable-gpl           --enable-libx264           --enable-libx265           --enable-libvpx           --enable-openssl           --enable-nonfree           --disable-static --enable-shared           --extra-ldflags="-Wl,-rpath,/usr/lib"         && make -j"$(nproc)"         && make install         && ldconfig         && cd / && rm -rf /tmp/ffmpeg-src         && yum remove -y gcc gcc-c++ make nasm yasm pkgconfig         libx264-devel libx265-devel libvpx-devel         freetype-devel fontconfig-devel fribidi-devel         harfbuzz-devel libxml2-devel openssl-devel         && yum autoremove -y         && yum clean all

# Verify ffmpeg works
RUN ffmpeg -version && ffprobe -version

# Install Python dependencies (torch + torchvision are pre-installed in base image)
COPY requirements.txt requirements-ai.txt ./
RUN pip install --no-cache-dir -r requirements.txt     && pip install --no-cache-dir -r requirements-ai.txt

# Create app directory
WORKDIR /app

# Copy application files
COPY server.py .
COPY VERSION .
COPY README.md .
COPY sprite_video_lab_icon.ico .
COPY sprite_video_lab_icon.png .
COPY app/ app/

# Create directories for persistent data
RUN mkdir -p /app/work /app/ai-cache

# Expose the default port
EXPOSE 8894

# Health check – poll the main page
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3     CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8894/')" || exit 1

# Start the server (Alinux3 uses python3)
CMD ["python3", "server.py", "--serve", "--host", "0.0.0.0", "--port", "8894"]
