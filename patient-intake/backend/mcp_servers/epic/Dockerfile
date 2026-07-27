FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Fully self-contained stub — no services/ or data/ needed at all.
COPY mcp_servers/epic/ mcp_servers/epic/

EXPOSE 5004

ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/epic/server.py"]