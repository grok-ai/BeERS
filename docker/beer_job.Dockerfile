FROM nvidia/cuda:11.5.1-devel-ubuntu20.04
FROM continuumio/miniconda3:latest

WORKDIR /root

# Install utilities
RUN \
    apt-get update && \
    apt-get install -y sudo rsync bzip2 ca-certificates byobu tmux nano htop wget curl  \
    build-essential git lm-sensors neovim less grep ripgrep

# Add SSH
RUN \
    apt-get update && \
    DEBIAN_FRONTEND="noninteractive" apt-get install -y openssh-server && \
    mkdir .ssh

# SSH port
EXPOSE 22

# Disable SSH login via password
#RUN sed -i -E 's/#?PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
#
# Change root password
RUN echo 'root:beer' | chpasswd
#
# Allow SSH root login
RUN sed -ri 's/^#?PermitRootLogin\s+.*/PermitRootLogin yes/' /etc/ssh/sshd_config
RUN sed -ri 's/UsePAM yes/#UsePAM yes/g' /etc/ssh/sshd_config

# Add VSCode Server
RUN curl -fsSL https://code-server.dev/install.sh | sh

# Start SSH service and run bash
ENTRYPOINT service ssh restart && bash
