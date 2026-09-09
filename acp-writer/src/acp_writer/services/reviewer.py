"""Reviewer identity — a SMART-on-FHIR-ready seam for the human verifier.

Everything downstream (the approve path, the verifier Humanagent on the
AI-Provenance, conflict acknowledgment) consumes only a ``ReviewerContext`` and
knows nothing about where it came from. Today it is built from config defaults
or an optional request override; a future SMART-on-FHIR launch handler will
construct one from the token's ``fhirUser`` claim (``source="smart"``) and pass
it through the very same request path — no downstream change required. That is
the whole point of this indirection: keep the identity source pluggable.
"""

import os

from pydantic import BaseModel


class ReviewerContext(BaseModel):
    """The clinician performing a care-plan review."""

    display: str
    reference: str | None = None          # e.g. "Practitioner/demo-clinician"
    identifier_system: str | None = None
    identifier_value: str | None = None
    # Provenance of the identity itself. Write-only today (no branch reads it);
    # reserved for the SMART-on-FHIR launch handler + review audit, which will
    # distinguish a token-derived "smart" reviewer from a config/request one.
    source: str = "config"                # "config" | "request" | "smart"

    def as_agent_who(self) -> dict:
        """FHIR Reference for a Provenance verifier agent's ``who``."""
        who: dict = {"display": self.display}
        if self.reference:
            who["reference"] = self.reference
        if self.identifier_system or self.identifier_value:
            ident: dict = {}
            if self.identifier_system:
                ident["system"] = self.identifier_system
            if self.identifier_value:
                ident["value"] = self.identifier_value
            who["identifier"] = ident
        return who


def default_reviewer() -> ReviewerContext:
    """Config-default reviewer from environment (``ACP_REVIEWER_*``)."""
    return ReviewerContext(
        display=os.environ.get("ACP_REVIEWER_DISPLAY", "Demo Clinician"),
        reference=os.environ.get("ACP_REVIEWER_REFERENCE", "Practitioner/demo-clinician") or None,
        identifier_system=os.environ.get("ACP_REVIEWER_ID_SYSTEM") or None,
        identifier_value=os.environ.get("ACP_REVIEWER_ID_VALUE") or None,
        source="config",
    )


def reviewer_from_payload(
    payload: dict | None, clinician: str | None = None
) -> ReviewerContext:
    """Build a reviewer from a request override, falling back to the default.

    ``payload`` is the optional ``reviewer`` object on a review submission:
    ``{reference?, display, identifierSystem?, identifierValue?}``. ``clinician``
    is the legacy bare display-string field some callers still send; it is used
    only when no ``payload`` is present. Centralizing that fallback here keeps the
    ``reviewer`` / ``clinician`` reconciliation in one place instead of copy-
    pasting the shim into every endpoint. Missing/empty inputs yield
    ``default_reviewer()``.
    """
    if not payload and clinician:
        payload = {"display": clinician}
    if not payload:
        return default_reviewer()

    base = default_reviewer()
    display = payload.get("display") or base.display
    return ReviewerContext(
        display=display,
        reference=payload.get("reference") or base.reference,
        identifier_system=payload.get("identifierSystem") or base.identifier_system,
        identifier_value=payload.get("identifierValue") or base.identifier_value,
        source="request",
    )
