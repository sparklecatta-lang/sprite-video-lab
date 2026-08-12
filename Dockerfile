# Sprite Video Lab 0.2.0 – Docker image (CUDA GPU)
# Base: Alibaba Cloud ACR PyTorch 2.9.0 + CUDA 13.0.2 + Python 3.12
FROM ac2-registry.cn-hangzhou.cr.aliyuncs.com/ac2/pytorch:2.9.0.10-cuda13.0.2-py312-alinux3.2104 AS base

# Environment defaults (can be overridden at runtime)
ENV SPRITE_VIDEO_LAB_FFMPEG_DIR=/usr/bin
ENV SPRITE_VIDEO_LAB_AI_MODEL_CACHE=/app/ai-cache

# Prefer public Alibaba Cloud mirrors for Docker Desktop/local builds.
RUN sed -i 's|http://mirrors.cloud.aliyuncs.com/|http://mirrors.aliyun.com/|g' /etc/yum.repos.d/*.repo \
    && yum makecache --disablerepo=cuda-rhel8-x86_64

# ============================================================
# Stage 1: Build ffmpeg from source
# ============================================================
FROM base AS ffmpeg-builder

# Layer B1: Install base build toolchain
RUN yum install -y --disablerepo=cuda-rhel8-x86_64 \
        gcc gcc-c++ make nasm yasm pkgconfig diffutils \
        bzip2 which 

# Layer B2: Install ffmpeg build helpers available in Alinux3
RUN yum install -y --disablerepo=cuda-rhel8-x86_64 zlib-devel 

RUN yum install -y --disablerepo=cuda-rhel8-x86_64 \
        git

RUN yum clean all

# Layer B3: Clone ffmpeg source at specified tag
RUN git clone --depth 1 --branch n7.1 https://gitee.com/mirrors/ffmpeg.git /tmp/ffmpeg-src

# Layer B4: Configure, compile, and install ffmpeg
RUN cd /tmp/ffmpeg-src \
    && ./configure \
        --prefix=/usr \
        --enable-gpl \
        --disable-static --enable-shared \
        --extra-ldflags="-Wl,-rpath,/usr/lib" \
    && make -j"$(nproc)" \
    && make install \
    && ldconfig

# ============================================================
# Stage 2: Final runtime image
# ============================================================
FROM base AS runtime

# Copy ffmpeg binaries from builder stage
COPY --from=ffmpeg-builder /usr/bin/ffmpeg /usr/bin/ffmpeg
COPY --from=ffmpeg-builder /usr/bin/ffprobe /usr/bin/ffprobe

# Copy ffmpeg shared libraries from builder stage
COPY --from=ffmpeg-builder /usr/lib/libavcodec.* /usr/lib/
COPY --from=ffmpeg-builder /usr/lib/libavdevice.* /usr/lib/
COPY --from=ffmpeg-builder /usr/lib/libavfilter.* /usr/lib/
COPY --from=ffmpeg-builder /usr/lib/libavformat.* /usr/lib/
COPY --from=ffmpeg-builder /usr/lib/libavutil.* /usr/lib/
COPY --from=ffmpeg-builder /usr/lib/libpostproc.* /usr/lib/
COPY --from=ffmpeg-builder /usr/lib/libswresample.* /usr/lib/
COPY --from=ffmpeg-builder /usr/lib/libswscale.* /usr/lib/

# Copy pkgconfig files (needed for ldconfig / .so resolution)
COPY --from=ffmpeg-builder /usr/lib/pkgconfig /usr/lib/pkgconfig

# Install minimal runtime dependencies (no build toolchain)
RUN yum install -y --disablerepo=cuda-rhel8-x86_64 zlib \
    && yum clean all \
    && ldconfig

# Verify ffmpeg works
RUN ffmpeg -version && ffprobe -version

# Install Python dependencies
COPY requirements.txt requirements-ai.txt ./
RUN pip install --no-cache-dir -r requirements.txt  -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
RUN pip install --no-cache-dir -r requirements-ai.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn

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
