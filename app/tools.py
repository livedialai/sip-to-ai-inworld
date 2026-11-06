"""Warenkorb, Lieferdaten, Bestellung und Produktsuche fuer den Inworld-Adapter.

Die Logik ist 1:1 aus dem jambonz-Agenten (lib/agent.js) uebernommen, damit
beide Wege dieselben Regeln haben: Gebinde-Umrechnung, Pflichtfelder,
Summenbildung, Bestellnummer kommt vom Worker.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

LIEFER_FELDER = ["name", "strasse", "hausnummer", "plz", "ort", "etage"]


def eur(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " Euro"


def pack_size(artikel: str) -> int:
    """'6 x 0,33 l' -> 6, sonst 1."""
    m = re.search(r"(\d+)\s*[x×]\s*[\d,.]+\s*l", str(artikel), re.I)
    return max(1, int(m.group(1))) if m else 1


@dataclass
class CallState:
    call_id: str = ""
    did: str = ""
    ani: str = ""
    tenant_id: int = 0
    cart: list[dict[str, Any]] = field(default_factory=list)
    liefer: dict[str, str] = field(default_factory=dict)
    transcript: list[dict[str, str]] = field(default_factory=list)
    order_no: Optional[str] = None
    order_summe: Optional[str] = None
    closed: bool = False
    tool_steps: int = 0


def cart_view(st: CallState) -> dict[str, Any]:
    summe = sum((i["menge"] * i["preis"]) for i in st.cart)
    return {
        "posten": [
            {
                "artikel": i["artikel"],
                "menge": i["menge"],
                "gebinde": i["gebinde"],
                "einzelpreis": eur(i["preis"]),
                "zeilensumme": eur(i["menge"] * i["preis"]),
            }
            for i in st.cart
        ],
        "anzahl_positionen": len(st.cart),
        "summe": eur(summe),
    }


def cart_add(st: CallState, artikel: str, menge: float, preis: float, einheit: str = "") -> dict[str, Any]:
    pack = pack_size(artikel)
    gebinde = max(1, int(menge or 1))
    flaschen = None
    will_flaschen = str(einheit or "").lower().startswith("flasch") or (menge or 0) > 1
    if pack > 1 and will_flaschen:
        gebinde = max(1, -(-int(menge or 1) // pack))  # ceil
        flaschen = gebinde * pack

    for item in st.cart:
        if item["artikel"].lower() == str(artikel).lower():
            item["menge"] += gebinde
            return {**cart_view(st), "hinweis": f"{artikel} jetzt {item['menge']} x im Warenkorb."}
    st.cart.append({"artikel": str(artikel), "menge": gebinde, "preis": float(preis or 0), "gebinde": pack, "flaschen": flaschen})
    return cart_view(st)


def liefer_speichern(st: CallState, args: dict[str, Any]) -> dict[str, Any]:
    for f in LIEFER_FELDER:
        v = args.get(f)
        if v is not None and str(v).strip() != "":
            st.liefer[f] = str(v).strip()
    fehlt = [f for f in LIEFER_FELDER if not st.liefer.get(f)]
    return {
        "gespeichert": st.liefer,
        "fehlt": fehlt,
        "hinweis": f"Es fehlen noch: {', '.join(fehlt)}. Frage nur diese Felder."
        if fehlt
        else "Alle Lieferdaten liegen vor.",
    }


async def _post_json(url: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    return await asyncio.to_thread(_do)


def adresse(st: CallState) -> str:
    parts = [
        st.liefer.get("strasse", ""),
        st.liefer.get("hausnummer", ""),
        " ".join(x for x in [st.liefer.get("plz", ""), st.liefer.get("ort", "")] if x),
        f"Etage {st.liefer['etage']}" if st.liefer.get("etage") else "",
    ]
    return ", ".join([p for p in parts if p])


async def abschluss(st: CallState, order_url: str) -> dict[str, Any]:
    view = cart_view(st)
    fehlt = [f for f in LIEFER_FELDER if not st.liefer.get(f)]
    if st.order_no:
        return {
            "ok": True,
            "order_no": st.order_no,
            "summe": st.order_summe,
            "adresse": adresse(st),
            "hinweis": "Bestellung war bereits abgeschlossen.",
        }
    if fehlt:
        return {"ok": False, "fehlt": fehlt, "hinweis": f"Es fehlen noch: {', '.join(fehlt)}."}
    if not st.cart:
        return {"ok": False, "hinweis": "Der Warenkorb ist leer."}

    payload = {
        "call_sid": st.call_id,
        "quelle": "s2s-adapter",
        "did": st.did,
        "ani": st.ani,
        "tenant_id": st.tenant_id,
        "kunde": st.liefer.get("name", ""),
        "strasse": st.liefer.get("strasse", ""),
        "hausnummer": st.liefer.get("hausnummer", ""),
        "plz": st.liefer.get("plz", ""),
        "ort": st.liefer.get("ort", ""),
        "etage": st.liefer.get("etage", ""),
        "positionen": [
            {"artikel": i["artikel"], "menge": i["menge"], "einzelpreis_num": i["preis"]} for i in st.cart
        ],
    }
    try:
        out = await _post_json(order_url, payload)
    except Exception as exc:  # noqa: BLE001
        logger.error("order failed", error=str(exc), call_id=st.call_id)
        return {"ok": False, "fehler": f"Bestellung konnte nicht gespeichert werden: {exc}"}

    if out.get("ok"):
        st.order_no = out.get("order_no")
        st.order_summe = out.get("summe")
        logger.info("order saved", call_id=st.call_id, order_no=st.order_no, summe=st.order_summe)
        return {
            "ok": True,
            "order_no": st.order_no,
            "summe": out.get("summe") or view["summe"],
            "adresse": adresse(st),
            "hinweis": "Nenne dem Kunden die Bestellnummer und die Summe.",
        }
    return {"ok": False, "fehler": out.get("error") or "unbekannter Fehler", "details": out}


def build_tools() -> list[dict[str, Any]]:
    """Tool-Definitionen — identisch zum jambonz-Agenten."""
    return [
        {
            "type": "function",
            "name": "phrase",
            "description": "Liefert den festen Standardtext fuer eine Gespraechssituation.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        },
        {
            "type": "function",
            "name": "execute_api_tool",
            "description": "Fuehrt ein Markt-Tool aus. tool_name: preis_abfrage oder angebote_abfrage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "enum": ["preis_abfrage", "angebote_abfrage"]},
                    "arguments": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "kategorie": {"type": "string"}},
                        "required": ["query"],
                    },
                },
                "required": ["tool_name", "arguments"],
            },
        },
        {
            "type": "function",
            "name": "warenkorb_hinzufuegen",
            "description": "Legt eine bestaetigte Position in den Warenkorb. menge = Anzahl Gebinde.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artikel": {"type": "string"},
                    "menge": {"type": "number", "description": "Anzahl Gebinde/Packungen"},
                    "preis": {"type": "number", "description": "Einzelpreis pro Gebinde in Euro"},
                    "einheit": {"type": "string", "enum": ["gebinde", "flasche"]},
                },
                "required": ["artikel", "menge", "preis"],
            },
        },
        {
            "type": "function",
            "name": "warenkorb_lesen",
            "description": "Liest den Warenkorb mit Positionen und Summe.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "lieferdaten_speichern",
            "description": "Speichert Lieferdaten. Nur die Felder senden, die der Kunde genannt hat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "strasse": {"type": "string"},
                    "hausnummer": {"type": "string"},
                    "plz": {"type": "string"},
                    "ort": {"type": "string"},
                    "etage": {"type": "string"},
                },
            },
        },
        {
            "type": "function",
            "name": "bestellung_abschliessen",
            "description": "Schliesst die Bestellung ab und liefert Positionen, Summe und Lieferanschrift.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "weiterleiten",
            "description": "Verbindet den Kunden mit einem Mitarbeiter. Nur wenn der Kunde ausdruecklich einen Menschen will.",
            "parameters": {"type": "object", "properties": {"grund": {"type": "string"}}},
        },
    ]


class ToolRunner:
    """Fuehrt Tool-Aufrufe des Modells aus und haelt den Zustand pro Anruf."""

    def __init__(
        self,
        state: CallState,
        search_url: str,
        order_url: str,
        phrases: Optional[dict[str, str]] = None,
        max_steps: int = 6,
    ) -> None:
        self.state = state
        self.search_url = search_url
        self.order_url = order_url
        self.phrases = phrases or {}
        self.max_steps = max_steps
        self.tools = build_tools()

    async def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        st = self.state
        st.tool_steps += 1
        if st.tool_steps > self.max_steps * 4:
            return {"fehler": "zu viele Tool-Aufrufe in diesem Gespraech"}

        try:
            if name == "phrase":
                key = str(args.get("key", ""))
                return {"key": key, "text": self.phrases.get(key) or self.phrases.get("unklar") or ""}
            if name == "execute_api_tool":
                inner = str(args.get("tool_name", ""))
                a = args.get("arguments") or {}
                if isinstance(a, str):
                    try:
                        a = json.loads(a)
                    except json.JSONDecodeError:
                        a = {}
                q = str(a.get("query", "")).strip()
                if not q:
                    return {"fehler": "arguments.query fehlt"}
                if inner not in ("preis_abfrage", "angebote_abfrage"):
                    return {"fehler": f"unbekanntes tool_name {inner}"}
                return await _post_json(self.search_url, {"query": q}, timeout=6.0)
            if name == "warenkorb_hinzufuegen":
                return cart_add(
                    st,
                    str(args.get("artikel") or "Artikel"),
                    args.get("menge") or 1,
                    _as_float(args.get("preis")),
                    str(args.get("einheit") or ""),
                )
            if name == "warenkorb_lesen":
                return cart_view(st)
            if name == "lieferdaten_speichern":
                return liefer_speichern(st, args)
            if name == "bestellung_abschliessen":
                return await abschluss(st, self.order_url)
            if name == "weiterleiten":
                return {"ok": False, "hinweis": "Weiterleitung ist im Adapter noch nicht aktiv."}
            return {"fehler": f"unbekanntes Tool {name}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool failed", tool=name, error=str(exc))
            return {"fehler": str(exc)}


def _as_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
