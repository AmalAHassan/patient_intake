FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_servers/athena/ mcp_servers/athena/

EXPOSE 5005

ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/athena/server.py"]