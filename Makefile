
## Dev startup
## Run `make dev` to start everything
 
.PHONY: dev mcp api stop
 
dev: ## Start MCP servers + FastAPI together
	@echo "Starting MCP servers..."
	@python start_mcp_servers.py &
	@sleep 2
	@echo "Starting FastAPI..."
	@cd backend && uvicorn main:app --reload --port 8000
 
mcp: ## Start only MCP servers
	python start_mcp_servers.py
 
api: ## Start only FastAPI (assumes MCP servers already running)
	cd backend && uvicorn main:app --reload --port 8000
 
stop: ## Stop everything
	@pkill -f start_mcp_servers.py || true
	@pkill -f uvicorn || true
	@echo "All stopped."
 
install: ## Install dependencies
	pip install anthropic mcp fastmcp fastapi uvicorn redis pydantic python-dotenv requests pandas