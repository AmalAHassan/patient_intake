FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Unlike patient-lookup, this server is self-contained — no services/
# or data/ needed, since all its logic and mock data live in server.py
# itself.
COPY mcp_servers/eligibility/ mcp_servers/eligibility/

# 5102 is the FastAPI /call port that mcp_client.py actually hits.
# 5002 is only the FastMCP SSE transport — unused by this architecture.
EXPOSE 5102

ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/eligibility/server.py"]