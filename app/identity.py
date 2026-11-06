"""Telefonie-Identitaet eines Anrufs: DID (Rufnummer des Marktes) und ANI (Anrufer).

Carrier liefern Nummern unterschiedlich: sipload schickt 0049..., easybell
haelt sich an E164 (+49...).  Hier wird einmal an der Kante normalisiert,
damit der Worker und die Datenbank nur eine Form kennen.  Die Rohwerte
bleiben erhalten (Fehlersuche, CDR).
"""

from __future__ import annotations

import re
from typing import Any


def e164(number: str, default_cc: str = "49") -> str:
    """Normalisiert eine Rufnummer auf E164 (+49...).

    Akzeptiert "+49...", "0049...", "049..." und "49...".
    Leere oder unbrauchbare Werte ergeben "".
    """
    n = (number or "").strip().strip('"').strip("'")
    # sip:user@host oder user:port abtrennen
    n = n.split("@")[0].split(";")[0]
    n = n.replace("sip:", "").replace("tel:", "")
    n = re.sub(r"[^\d+]", "", n)
    if not n:
        return ""
    if n.startswith("+"):
        return "+" + re.sub(r"\D", "", n[1:])
    if n.startswith("00"):
        return "+" + n[2:]
    if n.startswith("0"):
        return f"+{default_cc}{n[1:]}"
    if n.startswith(default_cc) and len(n) > len(default_cc) + 5:
        return f"+{n}"
    return f"+{default_cc}{n}"


def _header_number(invite: Any, name: str) -> str:
    """Liest die Nummer aus einem SIP-Header (From/To/P-Asserted-Identity)."""
    try:
        hdr = invite.headers.get(name)
    except AttributeError:
        return ""
    if isinstance(hdr, dict):
        return (hdr.get("number") or hdr.get("address") or "").strip()
    if isinstance(hdr, str):
        return hdr.strip()
    return ""


def extract_identity(invite: Any, default_cc: str = "49") -> dict[str, str]:
    """Liefert did/ani in Rohform und als E164.

    DID  = angerufene Nummer (To-Header; die Request-URI traegt bei manchen
           Traeks nur den Registrierungs-Namen, z.B. sip183911).
    ANI  = Anrufer (From, ersatzweise P-Asserted-Identity).
    """
    did_raw = _header_number(invite, "To")
    ani_raw = _header_number(invite, "From") or _header_number(
        invite, "P-Asserted-Identity"
    )
    return {
        "did_raw": did_raw,
        "did": e164(did_raw, default_cc),
        "ani_raw": ani_raw,
        "ani": e164(ani_raw, default_cc),
    }
