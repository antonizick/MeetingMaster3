# Convenience targets for the Docker deployment. Run from the repository root.
#   MM3_VAULT_PATH=/path/to/vault make up
# Variables: CPU=1 (no GPU), HOSTNET=1 (host network, for an Ollama on 127.0.0.1).
COMPOSE_FILES := -f docker/compose.yaml
ifeq ($(CPU),1)
COMPOSE_FILES += -f docker/compose.cpu.yaml
endif
ifeq ($(HOSTNET),1)
COMPOSE_FILES += -f docker/compose.host-network.yaml
endif
COMPOSE := docker compose $(COMPOSE_FILES)
SERVICE := meetingmaster3

.PHONY: build up down logs doctor models-download shell prune

build:            ## build the image
	$(COMPOSE) build
up:               ## start (detached)
	$(COMPOSE) up -d --build
down:             ## stop and remove the container (volumes are kept)
	$(COMPOSE) down
logs:             ## follow the logs
	$(COMPOSE) logs -f $(SERVICE)
doctor:           ## hardware and environment report from inside the container
	$(COMPOSE) exec $(SERVICE) mm3 doctor
models-download:  ## download WhisperX/pyannote models into the models volume
	$(COMPOSE) exec $(SERVICE) mm3 models download
shell:            ## shell inside the running container
	$(COMPOSE) exec $(SERVICE) bash
prune:            ## remove dangling images and build cache (never touches volumes)
	docker image prune -f
	docker builder prune -f
