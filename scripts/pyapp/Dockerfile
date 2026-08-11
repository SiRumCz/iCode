# Linux builder for openjiuwen PyApp binaries (musl Rust target).
# Used by scripts/pyapp/build-multi.sh for linux/amd64 and linux/arm64.
#
# macOS and Windows binaries are NOT produced from this image — use native
# runners (or Chrys-style GitHub Actions matrix) for those platforms.

FROM rust:1-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        perl \
        musl-tools \
        zip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pre-install common musl targets (actual arch depends on --platform).
RUN rustup target add x86_64-unknown-linux-musl aarch64-unknown-linux-musl || true

# uv installs openjiuwen[tui] + deps into the embedded CPython for --full builds.
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

WORKDIR /src
