FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2

LABEL org.opencontainers.image.source="https://github.com/librescoot/librescoot"
LABEL org.opencontainers.image.description="Librescoot firmware release packaging tools"

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git jq python3 unzip xdelta3 zstd \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --silent --show-error --location --retry 3 \
      -o /tmp/hdiffpatch.zip \
      https://github.com/sisong/HDiffPatch/releases/download/v5.1.3/hdiffpatch_v5.1.3_bin_linux64.zip \
    && echo '628963bf2ee9108a97260fa5eef44acd9ec94369b76090a957c9182b3abbb558  /tmp/hdiffpatch.zip' | sha256sum -c - \
    && unzip -j /tmp/hdiffpatch.zip 'linux64/hdiffz' -d /usr/local/bin \
    && chmod 0755 /usr/local/bin/hdiffz \
    && rm /tmp/hdiffpatch.zip
