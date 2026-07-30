"""
diagnose_stripe_mcp.py — Uses the OFFICIAL mcp Python SDK (not hand-rolled
JSON-RPC) to properly connect to Stripe's remote MCP server, complete the
real initialize handshake, and list its actual available tools + schemas.

Run this BEFORE building any deterministic backend-mediated MCP call —
we need to see the real tool names/schemas and confirm how the server
actually responds (this SDK correctly handles the handshake and any
SSE/session mechanics for you, rather than guessing at raw HTTP).

Install:
    pip install mcp --break-system-packages

Run:
    python diagnose_stripe_mcp.py
"""
import asyncio
import os
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Load .env explicitly from the same folder as this script — Python
# doesn't read .env files automatically, and os.getenv() alone only sees
# variables already exported into the shell.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

STRIPE_MCP_URL = "https://mcp.stripe.com"
STRIPE_MCP_KEY = os.getenv("STRIPE_MCP_RESTRICTED_KEY") or os.getenv("STRIPE_SECRET_KEY")


async def main():
    if not STRIPE_MCP_KEY:
        print("STRIPE_MCP_RESTRICTED_KEY not set in environment.")
        return

    headers = {"Authorization": f"Bearer {STRIPE_MCP_KEY}"}

    async with streamablehttp_client(STRIPE_MCP_URL, headers=headers) as (
        read_stream, write_stream, _
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("[mcp] Handshake succeeded.\n")

            tools_result = await session.list_tools()
            print(f"[mcp] {len(tools_result.tools)} tools available:\n")
            for tool in tools_result.tools:
                print(f"— {tool.name}")
                print(f"  {tool.description}")
                print(f"  input schema: {tool.inputSchema}")
                print()


if __name__ == "__main__":
    asyncio.run(main())