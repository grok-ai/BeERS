#! /bin/bash

# https://dockerswarm.rocks/swarmpit/

# exit when any command fails
set -e

temp_dir=$(mktemp -d)
cd "$temp_dir"

export DOMAIN=${DOMAIN:? Missing DOMAIN env var}

NODE_ID=$(docker info -f '{{.Swarm.NodeID}}')
export NODE_ID=$NODE_ID

docker node update --label-add swarmpit.db-data=true "$NODE_ID"
docker node update --label-add swarmpit.influx-data=true "$NODE_ID"

curl -L dockerswarm.rocks/swarmpit.yml -o swarmpit.yml

docker stack deploy -c swarmpit.yml swarmpit

rm -R "$temp_dir"
