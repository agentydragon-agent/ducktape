FROM ubuntu:22.04

# Install required packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       jq \
       curl \
       ca-certificates \
       systemd \
       python3 \
       dpkg \
       init \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set up systemd
RUN cd /lib/systemd/system/sysinit.target.wants/ \
    && rm $(ls | grep -v systemd-tmpfiles-setup) \
    && rm -f /lib/systemd/system/multi-user.target.wants/* \
    /etc/systemd/system/*.wants/* \
    /lib/systemd/system/local-fs.target.wants/* \
    /lib/systemd/system/sockets.target.wants/*udev* \
    /lib/systemd/system/sockets.target.wants/*initctl* \
    /lib/systemd/system/basic.target.wants/* \
    /lib/systemd/system/anaconda.target.wants/* \
    /lib/systemd/system/plymouth* \
    /lib/systemd/system/systemd-update-utmp*

# Set dpkg_arch for tests
RUN echo 'export dpkg_arch=$(dpkg --print-architecture)' >> /etc/bash.bashrc

# Volume for systemd
VOLUME [ "/sys/fs/cgroup" ]

# Start systemd
CMD ["/lib/systemd/systemd"]