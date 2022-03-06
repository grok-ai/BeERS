#! /bin/bash

# https://dockerswarm.rocks/traefik/

# exit when any command fails
set -e

temp_dir=$(mktemp -d)
cd "$temp_dir"

export EMAIL=${EMAIL:? Missing EMAIL env var}
export DOMAIN=${DOMAIN:? Missing DOMAIN env var}
export USERNAME=${USERNAME:? Missing USERNAME env var}

docker network create --driver=overlay traefik-public

NODE_ID=$(docker info -f '{{.Swarm.NodeID}}')

docker node update --label-add traefik-public.traefik-public-certificates=true "$NODE_ID"

echo "Now choose a password for the user '$USERNAME' to log into $DOMAIN"
HASHED_PASSWORD=$(openssl passwd -apr1)
export HASHED_PASSWORD=$HASHED_PASSWORD

curl -L dockerswarm.rocks/traefik.yml -o traefik.yml

docker stack deploy -c traefik.yml traefik

rm -R "$temp_dir"
