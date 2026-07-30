"""
services/stripe_mcp.py — Deterministic backend-mediated call to Stripe's
REAL remote MCP server (https://mcp.stripe.com).

This still genuinely uses Stripe's remote MCP server and protocol — it's
just orchestrated deterministically by our own backend instead of by
Claude reasoning through tool selection turn by turn. We skip the
planner/search/details discovery chain entirely, since the exact
operation needed (PostPaymentLinks via stripe_api_write) was already
confirmed via diagnose_stripe_mcp.py — there's nothing left to discover.

amount and description are passed in fresh on every call — nothing
patient-specific is hardcoded, only the fixed SHAPE of "one Payment Link,
one line item, quantity 1" is fixed, matching how any real integration
(including Stripe's own SDK) would call this operation.
"""
import os
import re
import json
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Load .env explicitly here rather than relying on some other module in
# the import chain to have already done it — this file was silently
# depending on that as a side effect, which broke the moment it got
# imported from a standalone script with a different import order.
for env_path in [
    os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    os.path.join(os.path.dirname(__file__), "..", ".env"),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
        break

STRIPE_MCP_URL = "https://mcp.stripe.com"
STRIPE_MCP_KEY = os.getenv("STRIPE_MCP_RESTRICTED_KEY") or os.getenv("STRIPE_SECRET_KEY")

# Defense in depth: even though this path is now deterministic (not
# AI-generated), validate the returned URL actually looks like a real
# Stripe-hosted link before trusting it — cheap insurance against ever
# passing something malformed through to a patient.
_REAL_LINK_RE = re.compile(r"https://(?:buy|checkout)\.stripe\.com/\S+")


FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


async def create_payment_link_via_mcp(copay_cents: int, description: str, session_id: str) -> dict:
    """
    Creates a real Stripe Payment Link via Stripe's own remote MCP
    server. `session_id` (our OWN intake session ID, already known at
    creation time) gets attached as metadata so the webhook can later
    resolve which patient this payment belongs to — Stripe has no
    concept of "your patients" on its own; this ID is the only thread
    connecting a successful payment back to a specific database row.

    Returns {"url": "..."} on success, or {"error": "..."} on failure —
    never raises, so the caller can gracefully fall back (e.g. to "pay
    at clinic") rather than crash the intake flow.
    """
    if not STRIPE_MCP_KEY:
        return {"error": "No Stripe MCP key configured (STRIPE_MCP_RESTRICTED_KEY / STRIPE_SECRET_KEY)"}

    headers = {"Authorization": f"Bearer {STRIPE_MCP_KEY}"}

    try:
        async with streamablehttp_client(STRIPE_MCP_URL, headers=headers) as (
            read_stream, write_stream, _
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                result = await session.call_tool(
                    "stripe_api_write",
                    {
                        "stripe_api_operation_id": "PostPaymentLinks",
                        "parameters": {
                            "line_items": [{
                                "price_data": {
                                    "currency": "usd",
                                    "product_data": {"name": description},
                                    "unit_amount": copay_cents,
                                },
                                "quantity": 1,
                            }],
                            # "hosted_confirmation" was a dead end — Stripe's
                            # own generic success page with no way back to
                            # the app. Redirect to our own success page
                            # instead, carrying our session_id along.
                            "after_completion": {
                                "type": "redirect",
                                "redirect": {
                                    "url": f"{FRONTEND_URL}/payment-complete?session_id={session_id}"
                                },
                            },
                            # Attached to the resulting Checkout Session —
                            # the webhook reads this back to know which
                            # intake session (and therefore which patient)
                            # this payment belongs to.
                            "metadata": {"session_id": session_id},
                        },
                    },
                )

                raw_text = "".join(
                    block.text for block in result.content if hasattr(block, "text")
                )

                url = None
                try:
                    parsed = json.loads(raw_text)
                    url = parsed.get("url")
                except json.JSONDecodeError:
                    pass

                if not url:
                    # Fallback: try to find a link directly in the raw
                    # text, in case the response wasn't pure JSON.
                    match = _REAL_LINK_RE.search(raw_text)
                    url = match.group(0) if match else None

                if url and _REAL_LINK_RE.search(url):
                    print(f"[stripe] Payment link created: {url}")
                    return {"url": url}

                print(f"[stripe] No valid link in MCP response: {raw_text[:300]}")
                return {"error": f"No valid payment link in response: {raw_text[:300]}"}

    except Exception as e:
        # asyncio.TaskGroup wraps the REAL underlying error inside an
        # ExceptionGroup, hiding it behind a generic "unhandled errors in
        # a TaskGroup" message. Unwrap it so we can actually see what
        # failed, instead of a useless one-liner.
        real_errors = getattr(e, "exceptions", None)
        if real_errors:
            for sub_e in real_errors:
                print(f"[stripe] Underlying error: {type(sub_e).__name__}: {sub_e}")
            detail = "; ".join(f"{type(sub_e).__name__}: {sub_e}" for sub_e in real_errors)
        else:
            import traceback
            traceback.print_exc()
            detail = str(e)
        print(f"[stripe] MCP call failed: {detail}")
        return {"error": detail}