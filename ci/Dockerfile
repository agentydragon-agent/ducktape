FROM ubuntu:latest

RUN apt update && \
  apt install -y \
    python3-pip
RUN pip3 install ansible ansible-lint
RUN apt clean && \
  apt autoremove -y
