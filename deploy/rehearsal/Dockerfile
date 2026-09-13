FROM debian:bookworm
ENV container=docker
RUN apt-get update && apt-get install -y systemd systemd-sysv openssh-server python3 sudo && rm -rf /var/lib/apt/lists/*
RUN touch /etc/polybot-disposable-rehearsal
RUN mkdir /run/sshd && ssh-keygen -A
# Nested Docker needs a non-overlay store; production keeps vendor defaults.
RUN mkdir -p /etc/docker && printf '%s' '{"features":{"containerd-snapshotter":false},"storage-driver":"vfs"}' > /etc/docker/daemon.json
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
