FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_servers/cerner/ mcp_servers/cerner/

EXPOSE 5006

ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/cerner/server.py"]