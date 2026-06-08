#!/usr/bin/env python3
"""
start_mcp_servers.py
Starts all MCP servers as background processes, then keeps running.
Run this before starting FastAPI:

    python start_mcp_servers.py &
    uvicorn main:app --reload

Or use the Makefile:
    make dev
"""
import subprocess
import sys
import os
import time
import signal

# start_mcp_servers.py lives at project root (patient-intake/)
# MCP servers live at patient-intake/backend/mcp_servers/
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")

# Always use the venv Python so MCP servers have access to installed packages
VENV_PYTHON = os.path.join(BASE, ".venv", "bin", "python3")
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable

SERVERS = [
    {"name": "patient-lookup", "path": "mcp_servers/patient_lookup/server.py", "port": 5001},
    {"name": "eligibility",    "path": "mcp_servers/eligibility/server.py",    "port": 5002},
    {"name": "hapi-fhir",      "path": "mcp_servers/hapi_fhir/server.py",      "port": 5003},
    {"name": "epic",           "path": "mcp_servers/epic/server.py",           "port": 5004},
    {"name": "athena",         "path": "mcp_servers/athena/server.py",         "port": 5005},
    {"name": "cerner",         "path": "mcp_servers/cerner/server.py",         "port": 5006},
]

processes = []


def start_servers():
    for server in SERVERS:
        full_path = os.path.join(BASE, server["path"])
        if not os.path.exists(full_path):
            print(f"  ⚠️  {server['name']} not found at {full_path} — skipping")
            continue

        # Pass the backend dir so MCP servers can find .env
        env = os.environ.copy()
        env["MCP_BACKEND_DIR"] = BASE

        proc = subprocess.Popen(
            [PYTHON, full_path],
            env=env,
            # Don't pipe output — let server logs print to terminal
        )
        processes.append((server["name"], proc, server["port"]))
        print(f"  ✓  {server['name']} started on port {server['port']} (pid {proc.pid})")

    # Wait for servers to be ready before FastAPI starts
    print(f"\nWaiting for {len(processes)} MCP servers to be ready...")
    time.sleep(3)
    
    # Check none crashed during startup
    alive = 0
    for name, proc, port in processes:
        if proc.poll() is None:
            alive += 1
        else:
            print(f"  ⚠️  {name} exited immediately (exit {proc.returncode}) — check server logs above")
    print(f"{alive}/{len(processes)} MCP servers running. Press Ctrl+C to stop all.\n")


def stop_servers(sig=None, frame=None):
    print("\nStopping MCP servers...")
    for name, proc, port in processes:
        proc.terminate()
        print(f"  ✓  {name} stopped")
    sys.exit(0)


if __name__ == "__main__":
    print("Starting MCP servers...\n")
    signal.signal(signal.SIGINT, stop_servers)
    signal.signal(signal.SIGTERM, stop_servers)
    start_servers()

    # Keep alive — check processes are still running every 5s
    while True:
        time.sleep(5)
        for i, (name, proc, port) in enumerate(processes):
            if proc.poll() is not None:
                print(f"  ⚠️  {name} crashed (exit {proc.returncode}) — restarting")
                idx = next(j for j, s in enumerate(SERVERS) if s["name"] == name)
                full_path = os.path.join(BASE, SERVERS[idx]["path"])
                new_proc = subprocess.Popen([PYTHON, full_path])
                processes[i] = (name, new_proc, port)