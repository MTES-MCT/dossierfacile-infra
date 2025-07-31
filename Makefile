# Sets the default environment to 'dev' if not specified by the user.
# Usage: make <target> env=production
env ?= dev

.PHONY: help deploy-all deploy-main deploy-data
.DEFAULT_GOAL := help

# Self-documenting help target.
help:
	@echo "Usage: make <target> [env=<environment>]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

deploy-all: ## Deploy all stacks for the specified environment
	@echo "--> Deploying all stacks for environment: $(env)"
	@$(MAKE) deploy-main env=$(env)
	@$(MAKE) deploy-data env=$(env)

deploy-main: ## Deploy only the main_stack
	@echo "--> Deploying main_stack for environment: $(env)"
	@cd ovh-server/main_stack && pulumi up --stack $(env) -y

deploy-data: ## Deploy only the data_stack
	@echo "--> Deploying data_stack for environment: $(env)"
	@cd ovh-server/data && pulumi up --stack $(env) -y
