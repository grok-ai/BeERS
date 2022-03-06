#! /bin/bash

# https://dockerswarm.rocks/swarmpit/

# exit when any command fails
set -e

temp_dir=$(mktemp -d)
cd "$temp_dir"

export DOMAIN=${DOMAIN:? Missing DOMAIN env var}

git clone https://github.com/stefanprodan/swarmprom.git
cd swarmprom

ADMIN_USER=$SWARMPROM_USER

echo "Now choose a password for the user '$ADMIN_USER' to log into swarmprom services."
HASHED_PASSWORD=$(openssl passwd -apr1)
export HASHED_PASSWORD=HASHED_PASSWORD


curl -L dockerswarm.rocks/swarmprom.yml -o swarmprom.yml

docker stack deploy -c swarmprom.yml swarmprom

rm -R "$temp_dir"
