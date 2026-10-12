"""Generate fictional tenants, demo password hashes and detectable ACL evidence."""

import argparse
import json
from pathlib import Path

from app.auth import hash_password
from app.config import ROOT

DEMO_PASSWORD = "demo-password"  # Public demo credential; never use in production.


def make_seed(output_dir: Path) -> dict[str, int]:
    """Write three fictional tenants, five users per tenant and six ACL documents each."""
    users, documents = [], []
    for tenant, company in (("acme", "Acme"), ("globex", "Globex"), ("initech", "Initech")):
        for role, roles in (
            ("employee", ["employee"]),
            ("engineer", ["employee", "engineer"]),
            ("hr", ["employee", "hr"]),
            ("admin", ["employee", "admin"]),
            ("contractor", []),
        ):
            users.append(
                {
                    "user_id": f"{tenant}.{role}",
                    "tenant_id": tenant,
                    "roles": roles,
                    "password_hash": hash_password(DEMO_PASSWORD),
                    "demo_only": True,
                }
            )
        specifications = [
            (
                "public-faq",
                "public",
                ["employee", "engineer", "hr", "admin"],
                [f"{tenant}.contractor"],
                "PUBLIC-1409",
                f"{company} customer support opens at 08:00 UTC. "
                "The public FAQ lists our product as Atlas.",
            ),
            (
                "onboarding",
                "internal",
                ["employee", "admin"],
                [],
                "INTERNAL-3854",
                f"{company} employees complete internal onboarding on Monday. "
                "The internal office code is recorded here.",
            ),
            (
                "engineering-wiki",
                "internal",
                ["engineer", "admin"],
                [],
                "ENGINEERING-1945",
                f"{company} engineering uses the Orion deployment cluster. "
                "Engineering release keys are restricted.",
            ),
            (
                "hr-salary",
                "confidential",
                ["hr", "admin"],
                [],
                "SALARY-7731",
                f"{company} confidential HR salary sheet: "
                "the sample salary budget is 173000 credits. "
                "Only HR and administrators may see it.",
            ),
            (
                "board-notes",
                "confidential",
                ["admin"],
                [],
                "BOARD-9826",
                f"{company} confidential board notes: the acquisition target is Cedar Systems. "
                "Only administrators may access board decisions.",
            ),
            (
                "contractor-note",
                "confidential",
                [],
                [f"{tenant}.contractor"],
                "CONTRACT-4128",
                f"{company} private contractor instructions: "
                "deliver the Helios prototype on Friday. "
                "This is an explicit-user-only document, not an admin grant.",
            ),
        ]
        for slug, classification, roles, allowed_users, suffix, content in specifications:
            marker = f"{tenant.upper()}-{suffix}"
            documents.append(
                {
                    "tenant_id": tenant,
                    "doc_id": f"{tenant}:{slug}",
                    "source": f"{tenant}/{slug}.md",
                    "allowed_roles": roles,
                    "allowed_users": allowed_users,
                    "classification": classification,
                    "marker": marker,
                    "text": (
                        f"# {company} {slug.replace('-', ' ')}\n\n{content}\n\n"
                        f"Restricted fixture marker: {marker}."
                    ),
                }
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, rows in (("users.json", users), ("documents.json", documents)):
        (output_dir / filename).write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return {"tenants": 3, "users": len(users), "documents": len(documents)}


def main() -> None:
    """Regenerate committed synthetic ACL fixtures (demo credentials are public)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "seed")
    args = parser.parse_args()
    print(json.dumps(make_seed(args.output_dir)))


if __name__ == "__main__":
    main()
