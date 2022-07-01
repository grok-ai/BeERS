#! /bin/bash
# Adapted from http://cowlet.org/2018/05/21/accessing-gpus-from-a-docker-swarm-service.html and
# https://gist.github.com/tomlankhorst/33da3c4b9edbde5c83fc1244f010815c

NFS_DIR="${1:-1}"
NFS_ALLOWED_RULE="${2:-*}"

# TODO: mandatory?
sudo mkdir -p /etc/systemd/system/docker.service.d

# https://stackoverflow.com/a/17841619
function join_by {
  local IFS="$1"
  shift
  echo "$*"
}

echo "Fetching available GPUs"

GPU_IDS=$(nvidia-smi -a | grep UUID | awk '{print $4}')

gpu_resources=()
for gpu_id in $GPU_IDS; do
  gpu_resources+=("\"GPU=$gpu_id\"")
done

gpus_list=$(join_by , "${gpu_resources[@]}")

# Fetch RAM quantity to update the shared memory option
ram=$(free -g | awk '/^Mem:/{print $2}')
ram=$((ram/2))

echo "Updating /etc/docker/daemon.json"

# This solution needs nvidia-container-runtime to be available!
cat <<EOF | sudo tee /etc/docker/daemon.json
{
  "default-shm-size": "${ram}G",
  "node-generic-resources": [
    $gpus_list
  ],
  "runtimes": {
      "nvidia": {
          "path": "/usr/bin/nvidia-container-runtime",
          "runtimeArgs": []
      }
  },
  "default-runtime": "nvidia"
}
EOF

echo "Updating /etc/nvidia-container-runtime/config.toml"

## Allow the GPU to be advertised as a swarm resource
sudo sed -i '/swarm-resource = "DOCKER_RESOURCE_GPU/d' /etc/nvidia-container-runtime/config.toml
sudo sed -i '1iswarm-resource = "DOCKER_RESOURCE_GPU"' /etc/nvidia-container-runtime/config.toml

echo "Reloading Docker"

# Reload the Docker daemon
sudo systemctl daemon-reload
sudo systemctl restart docker

# NFS setup
if [[ "$NFS_DIR" != 1 ]]; then
  echo "Installing nfs-kernel-server via apt"

  mkdir -p "$NFS_DIR"
  sudo apt update
  sudo apt install nfs-kernel-server

  echo "Updating /etc/exports"

  cat <<EOF | sudo tee /etc/exports
$NFS_DIR  $NFS_ALLOWED_RULE(rw,no_root_squash,subtree_check)
EOF

  echo "Enabling and reloading NFS service"
  sudo systemctl enable --now nfs-kernel-server
  sudo exportfs -r
fi
