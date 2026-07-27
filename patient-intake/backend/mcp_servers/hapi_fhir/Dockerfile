FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py .
COPY services/ services/
COPY mcp_servers/hapi_fhir/ mcp_servers/hapi_fhir/

EXPOSE 5003

ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/hapi_fhir/server.py"]