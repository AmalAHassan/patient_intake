FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Unlike patient-lookup, this server is self-contained — no services/
# or data/ needed, since all its logic and mock data live in server.py
# itself.
COPY mcp_servers/eligibility/ mcp_servers/eligibility/

# Only 5002 (MCP/SSE) needs to be reachable from outside.
# 5102 stays internal — same reasoning as patient-lookup's 5101.
EXPOSE 5002

ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/eligibility/server.py"]