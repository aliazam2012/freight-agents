"""A made-up carrier's claims service: a JSON API with Idempotency-Key, and a web portal.

The API follows the same key rules as the mock TMS (services/mock-kit). The portal is
deliberately like a real carrier portal: a sign-in, a claim form with uploads, a
confirmation page that shows the claim number, a "my claims" list, sessions that
expire after 30 minutes, and no idempotency at all, so a double submit files twice.
Admin routes (outside the OpenAPI file) let tests act as the carrier: acknowledge,
pay, decline or make an offer.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Cookie, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from freight_agents.mock_kit.idempotency import KeyStore, install_problems, parse_key
from pydantic import BaseModel

PORTAL_USER = "claims@lhg.example.com"
PORTAL_PASSWORD = "example-only"  # a made-up demo login for a made-up portal
SESSION_TTL = dt.timedelta(minutes=30)
Clock = Callable[[], dt.datetime]


class ClaimIn(BaseModel):
    reference: str
    claimant: str
    pro_number: str | None
    bol_number: str | None
    claim_type: Literal["damage", "shortage", "loss"]
    description: str
    amount_usd: float
    documents: list[str]


class ClaimOut(BaseModel):
    claim_number: str
    reference: str
    claimant: str
    channel: Literal["api", "portal"]
    status: Literal["received", "acknowledged", "resolved"]
    received_on: dt.date
    acknowledged_on: dt.date | None
    disposition: Literal["paid", "declined", "offered"] | None
    disposition_amount: float | None
    disposition_on: dt.date | None
    claim: ClaimIn


class Store:
    def __init__(self, path: str, scac: str, clock: Clock) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.scac, self.clock = scac, clock
        with self.lock, self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS claims (number TEXT PRIMARY KEY, "
                "reference TEXT NOT NULL, body TEXT NOT NULL)"
            )
        self.keys = KeyStore(self.db, self.lock, clock)
        self.sessions: dict[str, dt.datetime] = {}

    def create(self, claim: ClaimIn, channel: Literal["api", "portal"]) -> ClaimOut:
        with self.lock, self.db:
            count = self.db.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            out = ClaimOut(
                claim_number=f"{self.scac}-C-{count + 1:06d}",
                reference=claim.reference,
                claimant=claim.claimant,
                channel=channel,
                status="received",
                received_on=self.clock().date(),
                acknowledged_on=None,
                disposition=None,
                disposition_amount=None,
                disposition_on=None,
                claim=claim,
            )
            self.db.execute(
                "INSERT INTO claims VALUES (?, ?, ?)",
                (out.claim_number, out.reference, out.model_dump_json()),
            )
            return out

    def get(self, number: str) -> ClaimOut:
        row = self.db.execute("SELECT body FROM claims WHERE number = ?", (number,)).fetchone()
        if row is None:
            raise HTTPException(404, f"no claim {number}")
        return ClaimOut.model_validate_json(row[0])

    def find(self, reference: str | None) -> list[ClaimOut]:
        rows = self.db.execute("SELECT body FROM claims ORDER BY number").fetchall()
        claims = [ClaimOut.model_validate_json(r[0]) for r in rows]
        return [c for c in claims if reference is None or c.reference == reference]

    def save(self, claim: ClaimOut) -> None:
        with self.lock, self.db:
            self.db.execute(
                "UPDATE claims SET body = ? WHERE number = ?",
                (claim.model_dump_json(), claim.claim_number),
            )

    def session_ok(self, token: str | None) -> bool:
        started = self.sessions.get(token or "")
        return started is not None and self.clock() - started < SESSION_TTL


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"</head><body><h1>{html.escape(title)}</h1>{body}</body></html>"
    )


LOGIN_FORM = (
    "<form method='post' action='/portal/login'>"
    "<label>Email <input name='username' id='username'></label>"
    "<label>Password <input name='password' id='password' type='password'></label>"
    "<button type='submit' id='sign-in'>Sign in</button></form>"
)
CLAIM_FORM = (
    "<form method='post' action='/portal/claims' enctype='multipart/form-data'>"
    "<label>Your reference <input name='reference' id='reference'></label>"
    "<label>Claimant <input name='claimant' id='claimant'></label>"
    "<label>PRO number <input name='pro_number' id='pro_number'></label>"
    "<label>Bill of lading <input name='bol_number' id='bol_number'></label>"
    "<label>Type <select name='claim_type' id='claim_type'><option>damage</option>"
    "<option>shortage</option><option>loss</option></select></label>"
    "<label>Description <textarea name='description' id='description'></textarea></label>"
    "<label>Amount claimed <input name='amount_usd' id='amount_usd'></label>"
    "<label>Documents <input type='file' name='documents' id='documents' multiple></label>"
    "<button type='submit' id='submit-claim'>File claim</button></form>"
)


def create_app(
    scac: str,
    clock: Clock | None = None,
    db: str | Path = ":memory:",
    portal_without: tuple[str, ...] = (),
) -> FastAPI:
    """`portal_without` drops form fields by id, the way a carrier's redesign might."""
    app = FastAPI(
        title=f"Mock carrier claims ({scac})",
        version="0.1.0",
        description="A made-up carrier claims API with Idempotency-Key semantics.",
    )
    store = Store(str(db), scac, clock or (lambda: dt.datetime.now(dt.UTC)))
    app.state.store = store
    install_problems(app)

    @app.post("/api/claims", status_code=201, response_model=ClaimOut)
    def file_claim(body: ClaimIn, idempotency_key: str | None = Header(default=None)) -> Response:
        key = parse_key(idempotency_key)
        return store.keys.run(
            key, "POST /api/claims", body.model_dump_json(), lambda: store.create(body, "api"), 201
        )

    @app.get("/api/claims", response_model=list[ClaimOut])
    def list_claims(reference: str | None = None) -> list[ClaimOut]:
        return store.find(reference)

    @app.get("/api/claims/{number}", response_model=ClaimOut)
    def get_claim(number: str) -> ClaimOut:
        return store.get(number)

    # The carrier's own actions, for tests and demos.
    def act(number: str, update: dict[str, object]) -> ClaimOut:
        claim = store.get(number).model_copy(update=update)
        store.save(claim)
        return claim

    @app.post("/admin/claims/{number}/acknowledge", include_in_schema=False)
    def acknowledge(number: str) -> ClaimOut:
        return act(number, {"status": "acknowledged", "acknowledged_on": store.clock().date()})

    @app.post("/admin/claims/{number}/{outcome}", include_in_schema=False)
    def dispose(
        number: str, outcome: Literal["pay", "decline", "offer"], amount: float | None = None
    ) -> ClaimOut:
        name = {"pay": "paid", "decline": "declined", "offer": "offered"}[outcome]
        return act(
            number,
            {
                "status": "resolved",
                "disposition": name,
                "disposition_amount": amount,
                "disposition_on": store.clock().date(),
            },
        )

    @app.get("/portal/login", include_in_schema=False)
    def login_page() -> HTMLResponse:
        return _page("Sign in", LOGIN_FORM)

    @app.post("/portal/login", include_in_schema=False)
    def login(username: Annotated[str, Form()], password: Annotated[str, Form()]) -> Response:
        if (username, password) != (PORTAL_USER, PORTAL_PASSWORD):
            return _page("Sign in", "<p id='error'>Wrong email or password.</p>" + LOGIN_FORM)
        token = secrets.token_hex(16)
        store.sessions[token] = store.clock()
        response = RedirectResponse("/portal/claims", status_code=303)
        response.set_cookie("session", token, httponly=True)
        return response

    def signed_in(session: str | None) -> bool:
        return store.session_ok(session)

    @app.get("/portal/claims", include_in_schema=False)
    def my_claims(session: Annotated[str | None, Cookie()] = None) -> Response:
        if not signed_in(session):
            return RedirectResponse("/portal/login", status_code=303)
        rows = "".join(
            f"<tr><td class='number'>{html.escape(c.claim_number)}</td>"
            f"<td class='reference'>{html.escape(c.reference)}</td>"
            f"<td class='status'>{c.status}</td>"
            f"<td class='received'>{c.received_on.isoformat()}</td></tr>"
            for c in store.find(None)
        )
        head = "<tr><th>Claim</th><th>Reference</th><th>Status</th><th>Received</th></tr>"
        table = f"<table id='claims'>{head}{rows}</table>"
        return _page(
            "My claims", table + "<a href='/portal/claims/new' id='new-claim'>File a claim</a>"
        )

    @app.get("/portal/claims/new", include_in_schema=False)
    def new_claim(session: Annotated[str | None, Cookie()] = None) -> HTMLResponse:
        if not signed_in(session):
            return _page("Sign in", LOGIN_FORM)
        form = CLAIM_FORM
        for name in portal_without:
            form = re.sub(
                rf"<label>[^<]*<(?:input|select|textarea)[^>]*id='{name}'.*?</label>", "", form
            )
        return _page("File a claim", form)

    @app.post("/portal/claims", include_in_schema=False)
    def submit_claim(
        reference: Annotated[str, Form()],
        claimant: Annotated[str, Form()],
        claim_type: Annotated[Literal["damage", "shortage", "loss"], Form()],
        description: Annotated[str, Form()],
        amount_usd: Annotated[float, Form()],
        pro_number: Annotated[str | None, Form()] = None,
        bol_number: Annotated[str | None, Form()] = None,
        documents: Annotated[list[UploadFile] | None, File()] = None,
        session: Annotated[str | None, Cookie()] = None,
    ) -> Response:
        if not signed_in(session):
            return RedirectResponse("/portal/login", status_code=303)
        claim = ClaimIn(
            reference=reference,
            claimant=claimant,
            pro_number=pro_number or None,
            bol_number=bol_number or None,
            claim_type=claim_type,
            description=description,
            amount_usd=amount_usd,
            documents=[d.filename or "" for d in documents or []],
        )
        out = store.create(claim, "portal")
        return _page(
            "Claim received",
            f"<p id='confirmation'>Claim number: {html.escape(out.claim_number)}</p>"
            f"<p>Reference {html.escape(out.reference)}</p>"
            f"<p id='received'>Received on {out.received_on.isoformat()}</p>",
        )

    return app


def write_openapi(path: Path) -> None:
    path.write_text(json.dumps(create_app(scac="EXFL").openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    write_openapi(Path(__file__).resolve().parents[3] / "openapi.json")
