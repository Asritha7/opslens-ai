"""Deterministic runbook selection. Roles are test inputs, not authentication."""
import argparse
import json
import re
from pathlib import Path

from opslens.citations import validate_citations

ROOT = Path(__file__).resolve().parents[1]
ROLES = {"platform", "security", "intern"}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Use an exact major.minor.patch version, e.g. 2.4.0")
    return tuple(int(part) for part in value.split("."))


def load_documents():
    documents = json.loads((ROOT / "datasets/northstar/catalog.json").read_text())
    for doc in documents:
        if any('citation' in claim for claim in doc['claims']):
            path = (ROOT / doc['path']).resolve()
            if not path.is_relative_to(ROOT / 'datasets/northstar') or path.suffix != '.md':
                raise ValueError('Invalid citation source path')
            validate_citations(doc['claims'], path.read_text(encoding='utf-8'))
    return documents


def select(documents, *, role, service, software_version, environment,
           key_rotation_enabled=None):
    if role not in ROLES:
        raise ValueError("Unknown test role")
    requested = version(software_version)
    if environment not in {"production", "staging"}:
        raise ValueError("Environment must be production or staging")
    if key_rotation_enabled is not None and type(key_rotation_enabled) is not bool:
        raise ValueError("key_rotation_enabled must be true, false, or unknown")
    matches, uncertain = [], []
    questions, review_items = [], []
    # Authorization filtering precedes metadata inspection and all returned explanations.
    for doc in documents:
        if role not in doc["allowed_roles"]:
            continue
        if doc["status"] != "approved" or doc["service"] != service:
            continue
        if doc["environment"] is not None and doc["environment"] != environment:
            continue
        if doc["version_min"] is not None and requested < version(doc["version_min"]):
            continue
        if doc["version_max_exclusive"] is not None and requested >= version(doc["version_max_exclusive"]):
            continue
        required = doc["key_rotation_enabled"]
        if required is not None and key_rotation_enabled is not None and required != key_rotation_enabled:
            continue
        if (not doc["metadata_verified"] or doc["environment"] is None
                or doc["version_min"] is None or doc["version_max_exclusive"] is None
                or (required is not None and key_rotation_enabled is None)):
            uncertain.append(doc["id"])
            reference = {"document_id": doc["id"], "title": doc["title"],
                         "revision": doc["revision"], "path": doc["path"]}
            reasons = []
            if not doc["metadata_verified"]:
                reasons.append("metadata_unverified")
            for field in ("environment", "version_min", "version_max_exclusive"):
                if doc[field] is None:
                    reasons.append("missing_" + field)
            if reasons:
                review_items.append(dict(reference, reasons=reasons))
            if required is not None and key_rotation_enabled is None:
                if not questions:
                    questions.append({"field": "key_rotation_enabled",
                                      "question": "Is key rotation enabled in the affected service?",
                                      "allowed_answers": [True, False]})
            continue
        matches.append(doc)

    conflicts, conflict_details = [], []
    for i, left in enumerate(matches):
        for right in matches[i + 1:]:
            opposing = sorted({a["action"] for a in left["claims"] for b in right["claims"]
                               if a["action"] == b["action"] and {a["rule"], b["rule"]} == {"must", "must_not"}})
            if opposing:
                conflicts.append([left["id"], right["id"]])
                for action in opposing:
                    conflict_details.append({"action": action, "basis": "catalog_rules",
                        "documents": [{"document_id": d["id"], "title": d["title"],
                                       "revision": d["revision"], "path": d["path"],
                                       "rules": sorted({c["rule"] for c in d["claims"] if c["action"] == action}),
                                       "citations": [dict(c["citation"], rule=c["rule"], document_id=d["id"], revision=d["revision"])
                                                     for c in d["claims"] if c["action"] == action and "citation" in c],
                                       "citation_status": "available" if all("citation" in c for c in d["claims"] if c["action"] == action) else "incomplete"}
                                      for d in (left, right)],
                        "explanation": f"Applicable documents require and forbid the same action: {action}."})
    status = "conflict" if conflicts else "needs_context_or_review" if uncertain else "selected" if matches else "insufficient_evidence"
    messages = {
        "selected": "Found approved guidance applicable to the supplied context.",
        "conflict": "Applicable documents disagree. No recommendation is available until the conflict is reviewed.",
        "needs_context_or_review": "More context or metadata review is required before guidance can be recommended.",
        "insufficient_evidence": "Could not find enough approved guidance you can access for the supplied context.",
    }
    next_steps = []
    if conflicts:
        next_steps.append("Ask an authorized document owner to resolve the opposing instructions.")
    if questions:
        next_steps.append("Answer the follow-up question and submit the request again.")
    if review_items:
        next_steps.append("Ask an authorized reviewer to verify the listed document metadata.")
    if status == "selected":
        next_steps.append("Read the supporting documents and follow their approval requirements before acting.")
    if status == "insufficient_evidence":
        next_steps.append("Check the service, version, environment and prerequisites, or request an approved source.")
    return {
        "status": status,
        "message": messages[status],
        "next_steps": next_steps,
        "questions": questions,
        "review_items": review_items,
        "conflict_details": conflict_details,
        "applicable_documents": [d["id"] for d in matches],
        "uncertain_documents": uncertain,
        "conflicts": conflicts,
        "recommended_documents": [d["id"] for d in matches] if status == "selected" else [],
        "evidence": [{"document_id": d["id"], "revision": d["revision"], "path": d["path"]} for d in matches],
    }


def main():
    parser = argparse.ArgumentParser(description="Select fictional runbooks using explicit metadata; no AI calls.")
    parser.add_argument("--role", required=True, choices=sorted(ROLES))
    parser.add_argument("--source", choices=["files", "database"], default="files")
    parser.add_argument("--service", default="identity-service")
    parser.add_argument("--version", required=True)
    parser.add_argument("--environment", required=True, choices=["production", "staging"])
    parser.add_argument("--key-rotation", choices=["true", "false", "unknown"], default="unknown")
    args = parser.parse_args()
    try:
        if args.source == "database":
            import psycopg
            from opslens.database import load_authorized_documents
            try:
                documents = load_authorized_documents(args.role)
            except psycopg.Error:
                parser.exit(1, "Database unavailable or not initialized; check SETUP.md.\n")
        else:
            documents = load_documents()
        result = select(documents, role=args.role, service=args.service,
                        software_version=args.version, environment=args.environment,
                        key_rotation_enabled={"true": True, "false": False, "unknown": None}[args.key_rotation])
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
