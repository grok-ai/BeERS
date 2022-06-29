FROM nvidia/cuda:11.5.1-cudnn8-devel-ubuntu20.04

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

# Miniconda
ENV PATH="/root/miniconda3/bin:$PATH"

RUN \
    wget -O miniconda.sh "https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh" && \
    bash miniconda.sh -b -p /root/miniconda3 && \
    rm -f miniconda.sh


RUN conda update -y conda && conda init

# Disable SSH login via password
#RUN sed -i -E 's/#?PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
#
# Change root password
# RUN echo 'root:beers' | chpasswd
#
# Allow SSH root login
RUN sed -ri 's/^#?PermitRootLogin\s+.*/PermitRootLogin yes/' /etc/ssh/sshd_config
RUN sed -ri 's/UsePAM yes/#UsePAM yes/g' /etc/ssh/sshd_config

# Add VSCode Server
RUN curl -fsSL https://code-server.dev/install.sh | sh

# SSH port
EXPOSE 22

# Start SSH service and run bash
ENTRYPOINT service ssh restart && bash
