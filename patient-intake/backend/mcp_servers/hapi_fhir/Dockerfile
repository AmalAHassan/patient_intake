FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py .
COPY services/ services/
COPY mcp_servers/hapi_fhir/ mcp_servers/hapi_fhir/

# 5103 is the FastAPI /call port that mcp_client.py actually hits.
# 5003 is only the FastMCP SSE transport — unused by this architecture.
EXPOSE 5103

ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/hapi_fhir/server.py"]