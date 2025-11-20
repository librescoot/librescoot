FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LC_ALL=en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US.UTF-8

RUN apt-get update && apt-get install -y \
    gawk wget git diffstat unzip texinfo gcc build-essential \
    chrpath socat cpio python3 python3-pip python3-pexpect \
    xz-utils debianutils iputils-ping python3-git python3-jinja2 \
    python3-subunit zstd liblz4-tool file locales libacl1 \
    curl sudo git-lfs python-is-python3 vim gcc-multilib \
    && rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8

RUN mkdir -p /etc/sudoers.d && \
    groupadd -g 999 yocto && \
    useradd -m -u 999 -g 999 yocto && \
    usermod -aG sudo yocto && \
    echo "yocto ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/yocto

RUN curl http://commondatastorage.googleapis.com/git-repo-downloads/repo > /usr/local/bin/repo && \
    chmod a+x /usr/local/bin/repo

WORKDIR /yocto
RUN chown -R yocto:yocto /yocto


COPY docker/entrypoint.sh /usr/local/bin/
RUN mkdir -p /opt/yocto-env
COPY nightly.env stable.env /opt/yocto-env/

USER yocto
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
