FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ services/
COPY data/ data/
COPY mcp_servers/patient_lookup/ mcp_servers/patient_lookup/

# 5101 is the FastAPI /call port that mcp_client.py actually hits.
# 5001 is only the FastMCP SSE transport — unused by this architecture.
EXPOSE 5101

ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/patient_lookup/server.py"]