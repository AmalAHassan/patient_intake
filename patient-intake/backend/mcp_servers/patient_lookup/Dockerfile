# Base Python image — matches your Python 3.13 backend.
FROM python:3.13-slim

WORKDIR /app

# Copy the backend's requirements.txt first (cache-friendly layering:
# this layer only re-runs if requirements.txt changes, not every time
# server.py changes).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything the server actually imports:
# - services/patient_lookup.py  (imported via importlib)
# - data/patients_enriched.csv  (read inside load_patients())
# - mcp_servers/patient_lookup/server.py (the entrypoint itself)
#
# We copy full folders rather than single files, since server.py does
# sys.path.insert(0, BACKEND_DIR) and expects the whole "services."
# package structure to be importable.
COPY services/ services/
COPY data/ data/
COPY mcp_servers/patient_lookup/ mcp_servers/patient_lookup/

# Only 5001 (the MCP/SSE endpoint) is reachable from outside.
# 5101 is intentionally not exposed — it's internal-only.
EXPOSE 5001

# Tells server.py where "BACKEND_DIR" is inside the container.
# Since the whole backend/ tree was copied into /app, /app IS
# the equivalent of your local backend/ folder.
ENV MCP_BACKEND_DIR=/app

CMD ["python", "mcp_servers/patient_lookup/server.py"]