"""Tenant-Aufloesung pro Anruf: DID -> Konfiguration (Prompt, Stimme, Nummern).

Der Adapter fragt den PHP-Worker (Lima) per HTTP.  Faellt der Worker aus,
bleibt der Anruf trotzdem moeglich: dann gilt die lokale agent_prompt.yaml
und die Stimme aus der .env.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


def _get_json(url: str, timeout: float) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - Netzfehler duerfen den Anruf nicht killen
        logger.warning("tenant lookup failed", url=url, error=str(exc))
        return None


def _get_text(url: str, timeout: float) -> str:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("prompt fetch failed", url=url, error=str(exc))
        return ""


async def fetch_tenant(
    did: str,
    base_url: str,
    ani: str = "",
    timeout: float = 3.0,
) -> Optional[dict[str, Any]]:
    """Holt die Tenant-Konfiguration zur DID.  None = unbekannt/Worker weg."""
    if not did:
        return None
    q = urllib.parse.urlencode({"did": did, "ani": ani})
    url = f"{base_url.rstrip('/')}/tenant/by-did?{q}"
    data = await asyncio.to_thread(_get_json, url, timeout)
    if not data or not data.get("ok"):
        logger.info("no tenant for did", did=did, response=str(data)[:120])
        return None
    tenant = data.get("tenant") or {}
    logger.info(
        "tenant resolved",
        did=did,
        tenant_id=tenant.get("id"),
        name=tenant.get("name"),
        voice_id=tenant.get("voice_id"),
    )
    return tenant


async def fetch_prompt(prompt_url: str, timeout: float = 4.0) -> str:
    """Laedt den Prompt-Text des Tenants."""
    if not prompt_url:
        return ""
    return await asyncio.to_thread(_get_text, prompt_url, timeout)
