#!/usr/bin/env python3
"""Small, dependency-free evidence and run-evidence verifier for research projects."""

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCHEMA_VERSION = "1.0"
OPENALEX_URL = "https://api.openalex.org/works"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AssuranceError(ValueError):
    """Raised when an input document is malformed or unsafe to verify."""


def load_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise AssuranceError("Cannot read JSON file {}: {}".format(path, exc)) from exc


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_profile(profile):
    if not isinstance(profile, dict):
        return ["Profile root must be a JSON object"]
    errors = []
    if profile.get("schema_version") != SCHEMA_VERSION:
        errors.append("Profile schema_version must be {}".format(SCHEMA_VERSION))
    for key in ("profile_id", "research_question", "questions", "evidence", "invariants"):
        if key not in profile:
            errors.append("Missing required profile field: {}".format(key))
    for key in ("questions", "evidence", "invariants"):
        if key in profile and not isinstance(profile[key], list):
            errors.append("Profile field {} must be a list".format(key))
    if errors:
        return errors

    evidence_ids = set()
    for item in profile.get("evidence", []):
        if not isinstance(item, dict):
            errors.append("Evidence entries must be JSON objects")
            continue
        evidence_id = item.get("id")
        if not evidence_id:
            errors.append("Evidence entries must have an id")
        elif evidence_id in evidence_ids:
            errors.append("Duplicate evidence id: {}".format(evidence_id))
        else:
            evidence_ids.add(evidence_id)
        for key in ("kind", "reference", "claim", "status"):
            if not item.get(key):
                errors.append("Evidence {} must state {}".format(evidence_id or "<missing id>", key))
        if item.get("status") == "reviewed_attestation" and not item.get("reviewer"):
            errors.append("Reviewed evidence {} must name its reviewer".format(evidence_id))
        if item.get("status") == "reviewed_attestation" and not item.get("reviewed_at"):
            errors.append("Reviewed evidence {} must record reviewed_at".format(evidence_id))

    invariant_ids = set()
    for rule in profile.get("invariants", []):
        if not isinstance(rule, dict):
            errors.append("Invariant entries must be JSON objects")
            continue
        rule_id = rule.get("id")
        if not rule_id:
            errors.append("Invariant entries must have an id")
        elif rule_id in invariant_ids:
            errors.append("Duplicate invariant id: {}".format(rule_id))
        else:
            invariant_ids.add(rule_id)
        for evidence_id in rule.get("evidence_ids", []):
            if evidence_id not in evidence_ids:
                errors.append("Invariant {} references unknown evidence {}".format(rule_id, evidence_id))
        kind = rule.get("type")
        if kind == "range":
            if "minimum" not in rule or "maximum" not in rule:
                errors.append("Range invariant {} requires minimum and maximum".format(rule_id))
            elif any(
                not isinstance(rule[key], (int, float))
                or isinstance(rule[key], bool)
                or not math.isfinite(rule[key])
                for key in ("minimum", "maximum")
            ):
                errors.append("Range invariant {} bounds must be finite numbers".format(rule_id))
            elif rule["minimum"] > rule["maximum"]:
                errors.append("Range invariant {} has minimum above maximum".format(rule_id))
            if not isinstance(rule.get("target"), str) or not rule.get("target"):
                errors.append("Range invariant {} requires a dotted trace target".format(rule_id))
        elif kind != "event_alignment":
            errors.append("Invariant {} has unsupported type {!r}".format(rule_id, kind))
        if not isinstance(rule.get("evidence_ids", []), list):
            errors.append("Invariant {} evidence_ids must be a list".format(rule_id))

    for question in profile.get("questions", []):
        if not isinstance(question, dict):
            errors.append("Question entries must be JSON objects")
        elif question.get("status") not in ("resolved", "unresolved"):
            errors.append("Question {} must have status resolved or unresolved".format(question.get("id", "<missing id>")))

    return errors


def get_path(document, dotted_path):
    value = document
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted_path)
        value = value[part]
    return value


def check_range(rule, trace):
    try:
        values = get_path({"trace": trace}, rule["target"])
    except KeyError:
        return {
            "id": rule["id"],
            "status": "blocked",
            "detail": "Trace field {!r} is missing".format(rule.get("target")),
        }
    if not isinstance(values, list) or not values:
        return {
            "id": rule["id"],
            "status": "blocked",
            "detail": "Trace field {!r} must be a non-empty numeric list".format(rule["target"]),
        }
    flat_values = []
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            flat_values.append(value)
        else:
            return {
                "id": rule["id"],
                "status": "blocked",
                "detail": "Trace field {!r} contains non-finite or non-numeric values".format(rule["target"]),
            }
    if not flat_values:
        return {
            "id": rule["id"],
            "status": "blocked",
            "detail": "Trace field {!r} contains no numeric values".format(rule["target"]),
        }

    minimum = rule["minimum"]
    maximum = rule["maximum"]
    observed_min = min(flat_values)
    observed_max = max(flat_values)
    passed = observed_min >= minimum and observed_max <= maximum
    return {
        "id": rule["id"],
        "status": "passed" if passed else "failed",
        "detail": "Observed [{:.12g}, {:.12g}], permitted [{:.12g}, {:.12g}]{}".format(
            observed_min,
            observed_max,
            minimum,
            maximum,
            " across {} values".format(len(flat_values)),
        ),
    }


def check_event_alignment(rule, trace):
    if not isinstance(trace, dict):
        return {"id": rule["id"], "status": "blocked", "detail": "Trace must be a JSON object"}
    events = trace.get("estimator_events")
    if not isinstance(events, list) or not events:
        return {"id": rule["id"], "status": "blocked", "detail": "No estimator events were recorded"}

    errors = []
    observed_kinds = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append("event {}: event record must be a JSON object".format(index))
            continue
        kind = event.get("event")
        observed_kinds.add(kind)
        if kind == "update":
            state_index = event.get("state_time_index")
            measurement_index = event.get("measurement_time_index")
            if state_index is None or measurement_index is None:
                errors.append("event {}: update lacks state or measurement index".format(index))
            elif state_index != measurement_index:
                errors.append(
                    "event {}: update state t={} uses measurement t={}".format(
                        index, state_index, measurement_index
                    )
                )
        elif kind == "predict":
            start = event.get("state_from_index")
            end = event.get("state_to_index")
            input_index = event.get("input_time_index")
            if start is None or end is None or input_index is None:
                errors.append("event {}: predict lacks state transition or input index".format(index))
            elif end != start + 1 or input_index != start:
                errors.append(
                    "event {}: transition {}->{} must use input t={}".format(
                        index, start, end, start
                    )
                )
        else:
            errors.append("event {}: unsupported event type {!r}".format(index, kind))
    for required_kind in ("predict", "update"):
        if required_kind not in observed_kinds:
            errors.append("trace has no {} events".format(required_kind))
    return {
        "id": rule["id"],
        "status": "failed" if errors else "passed",
        "detail": "; ".join(errors) if errors else "All recorded predict/update indices satisfy the declared contract",
    }


def _safe_output_path(run_dir, relative_path):
    root = Path(run_dir).resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AssuranceError("Output path escapes run directory: {}".format(relative_path)) from exc
    return candidate


def verify_artifacts(run, run_dir):
    results = []
    outputs = run.get("outputs", [])
    if not isinstance(outputs, list):
        return [{"path": None, "status": "blocked", "detail": "Run outputs must be a list"}]
    for item in outputs:
        if not isinstance(item, dict):
            results.append({"path": "<malformed>", "status": "blocked", "detail": "Output record must be a JSON object"})
            continue
        path = item.get("path")
        expected = item.get("sha256")
        if not isinstance(path, str) or not path or not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected):
            results.append({"path": path or "<missing>", "status": "blocked", "detail": "Output needs path and sha256"})
            continue
        try:
            actual_path = _safe_output_path(run_dir, path)
            actual = sha256_file(actual_path)
        except (OSError, AssuranceError) as exc:
            results.append({"path": path, "status": "failed", "detail": str(exc)})
            continue
        results.append(
            {
                "path": path,
                "status": "passed" if actual == expected else "failed",
                "detail": "SHA-256 matches" if actual == expected else "SHA-256 mismatch",
            }
        )
    if not outputs:
        results.append({"path": None, "status": "blocked", "detail": "Run manifest contains no output digests"})
    return results


def compare_replicates(run):
    replicates = run.get("replicates", [])
    if not isinstance(replicates, list):
        return {"status": "not_verified", "detail": "Replicates field must be a list"}
    if len(replicates) < 2:
        return {
            "status": "not_verified",
            "detail": "At least two recorded runs with matching profile, config, and output digests are required",
        }
    signatures = []
    for replicate in replicates:
        if not isinstance(replicate, dict):
            return {"status": "not_verified", "detail": "A replicate record is not a JSON object"}
        if (
            not replicate.get("profile_id")
            or not isinstance(replicate.get("profile_sha256"), str)
            or not SHA256_PATTERN.fullmatch(replicate["profile_sha256"])
            or not isinstance(replicate.get("config_sha256"), str)
            or not SHA256_PATTERN.fullmatch(replicate["config_sha256"])
            or not replicate.get("outputs")
        ):
            return {
                "status": "not_verified",
                "detail": "A replicate is missing profile id, config digest, or output digests",
            }
        if not isinstance(replicate["outputs"], list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or not SHA256_PATTERN.fullmatch(item["sha256"])
            for item in replicate["outputs"]
        ):
            return {"status": "not_verified", "detail": "A replicate has malformed output digest records"}
        if any(
            not item["path"] for item in replicate["outputs"]
        ):
            return {
                "status": "not_verified",
                "detail": "A replicate has malformed output digest records",
            }
        output_signature = sorted(
            (item.get("path"), item.get("sha256")) for item in replicate["outputs"]
        )
        signatures.append(
            (replicate["profile_id"], replicate["profile_sha256"], replicate["config_sha256"], output_signature)
        )
    if all(signature == signatures[0] for signature in signatures[1:]):
        return {
            "status": "matching_recorded_runs",
            "detail": "{} recorded runs share profile, config, and output digests; this does not prove regeneration".format(
                len(replicates)
            ),
        }
    return {"status": "mismatch", "detail": "Recorded replicate profile/config/output digests differ"}


def audit_claims(run, profile):
    claims = run.get("claims")
    if claims is None:
        return {
            "status": "not_assessed",
            "results": [],
            "blockers": ["Claim ledger is missing; report claims cannot be audited"],
            "detail": "No claim ledger was supplied; report claims cannot be audited",
        }
    if not isinstance(claims, list):
        return {
            "status": "blocked",
            "results": [],
            "blockers": ["Claim ledger must be a list"],
            "detail": "Malformed claim ledger",
        }
    evidence_by_id = {item["id"]: item for item in profile.get("evidence", [])}
    results = []
    blockers = []
    for claim in claims:
        if not isinstance(claim, dict):
            blockers.append("Claim record must be a JSON object")
            results.append({"id": "<malformed>", "status": "blocked", "issues": ["claim record must be an object"]})
            continue
        claim_id = claim.get("id", "<missing id>")
        issues = []
        if not claim.get("text"):
            issues.append("claim text is missing")
        evidence_ids = claim.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or not evidence_ids:
            issues.append("no evidence is linked")
            evidence_ids = []
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                issues.append("unknown evidence {}".format(evidence_id))
            elif evidence.get("status") != "reviewed_attestation":
                issues.append("evidence {} is not independently reviewed".format(evidence_id))
        if claim.get("scope") == "external_empirical":
            issues.append("external empirical claims are not validated by this MVP")
        elif claim.get("scope") != "synthetic_model":
            issues.append("claim scope must be synthetic_model or external_empirical")
        results.append(
            {
                "id": claim_id,
                "status": "blocked" if issues else "evidence_linked_unverified",
                "issues": issues,
            }
        )
        if issues:
            blockers.append("{}: {}".format(claim_id, "; ".join(issues)))
    return {
        "status": "blocked" if blockers else "evidence_linked_unverified",
        "results": results,
        "blockers": blockers,
        "detail": "Source applicability and claim truth still require expert review",
    }


def verify(profile, run, profile_path, run_path, config_path=None):
    profile_errors = validate_profile(profile)
    if profile_errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict": "blocked",
            "profile_errors": profile_errors,
            "scientific_validity": "not_established",
        }
    if not isinstance(run, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict": "blocked",
            "run_errors": ["Run manifest root must be a JSON object"],
            "scientific_validity": "not_established",
        }

    blockers = []
    if run.get("profile_id") != profile.get("profile_id"):
        blockers.append("Run profile_id does not match the selected profile")
    recorded_profile_digest = run.get("profile_sha256")
    if not isinstance(recorded_profile_digest, str) or not SHA256_PATTERN.fullmatch(recorded_profile_digest):
        blockers.append("Run manifest is missing a SHA-256 profile_sha256")
    elif recorded_profile_digest != sha256_file(profile_path):
        blockers.append("Run profile_sha256 does not match the selected profile file")
    config_digest = run.get("config_sha256")
    config_integrity = {
        "status": "not_checked",
        "detail": "Configuration contents were not supplied to the verifier",
    }
    if not isinstance(config_digest, str) or not SHA256_PATTERN.fullmatch(config_digest):
        blockers.append("Run manifest is missing a SHA-256 config_sha256")
    elif config_path is not None:
        actual_config_digest = sha256_file(config_path)
        config_matches = config_digest == actual_config_digest
        config_integrity = {
            "status": "passed" if config_matches else "failed",
            "detail": "Configuration SHA-256 matches manifest" if config_matches else "Configuration SHA-256 mismatch",
        }
        if not config_matches:
            blockers.append("Run config_sha256 does not match the selected configuration file")

    unresolved = [
        item for item in profile.get("questions", []) if item.get("status") != "resolved"
    ]
    for item in unresolved:
        blockers.append("Unresolved decision {}: {}".format(item.get("id", "<missing id>"), item.get("question", "")))

    trace = run.get("trace", {})
    if not isinstance(trace, dict):
        trace = {}
        blockers.append("Run trace must be a JSON object")
    invariant_results = []
    evidence_by_id = {item["id"]: item for item in profile.get("evidence", [])}
    for rule in profile.get("invariants", []):
        if rule["type"] == "range":
            result = check_range(rule, trace)
        else:
            result = check_event_alignment(rule, trace)
        unverified_evidence = [
            evidence_id
            for evidence_id in rule.get("evidence_ids", [])
            if evidence_by_id[evidence_id].get("status") != "reviewed_attestation"
        ]
        if unverified_evidence:
            result["evidence_status"] = "unverified"
            if result["status"] == "passed":
                result["status"] = "provisional"
            blockers.append(
                "{} relies on evidence not marked verified: {}".format(
                    result["id"], ", ".join(unverified_evidence)
                )
            )
        else:
            result["evidence_status"] = "verified"
        invariant_results.append(result)
        if result["status"] in ("failed", "blocked"):
            blockers.append("{}: {}".format(result["id"], result["detail"]))

    artifacts = verify_artifacts(run, Path(run_path).resolve().parent)
    for artifact in artifacts:
        if artifact["status"] != "passed":
            blockers.append("Artifact {}: {}".format(artifact["path"], artifact["detail"]))

    reproducibility = compare_replicates(run)
    if reproducibility["status"] != "matching_recorded_runs":
        blockers.append("Reproducibility evidence: {}".format(reproducibility["detail"]))
    claim_audit = audit_claims(run, profile)
    blockers.extend(claim_audit["blockers"])

    external_status = profile.get("external_validation", {}).get("status", "not_assessed")
    if external_status == "performed":
        external_status = "claimed_unverified"
    elif external_status not in ("not_performed", "not_assessed"):
        blockers.append("Unsupported external validation status: {}".format(external_status))
        external_status = "not_assessed"

    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": profile["profile_id"],
        "run_id": run.get("run_id"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "verdict": "blocked" if blockers else "configured_checks_passed",
        "dimensions": {
            "recorded_run_reproducibility": reproducibility,
            "profile_conformance": {
                "status": "blocked" if unresolved else "resolved",
                "unresolved_decisions": [item.get("id") for item in unresolved],
            },
            "model_invariants": invariant_results,
            "artifact_integrity": artifacts,
            "configuration_integrity": config_integrity,
            "claim_audit": claim_audit,
            "external_validation": external_status,
            "scientific_validity": "not_established",
        },
        "blockers": blockers,
        "limits": [
            "Matching recorded hashes are not proof that the experiment can be regenerated.",
            "Passing configured checks is not proof that the profile or model is scientifically valid.",
            "External validation requires appropriate independent data and domain review.",
        ],
    }


def search_openalex(query, limit):
    if not query.strip():
        raise AssuranceError("Search query must not be empty")
    if limit < 1 or limit > 25:
        raise AssuranceError("Search limit must be between 1 and 25")
    params = urlencode(
        {
            "search": query,
            "per-page": limit,
            "select": "id,doi,title,publication_year,type,primary_location,authorships",
        }
    )
    request = Request(
        "{}?{}".format(OPENALEX_URL, params),
        headers={"User-Agent": "research-assurance/0.1 (scholarly discovery; contact: local user)"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AssuranceError("OpenAlex literature search failed: {}".format(exc)) from exc

    works = []
    for item in payload.get("results", []):
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        authors = item.get("authorships") or []
        works.append(
            {
                "title": item.get("title"),
                "year": item.get("publication_year"),
                "type": item.get("type"),
                "doi": item.get("doi"),
                "openalex_id": item.get("id"),
                "venue": source.get("display_name"),
                "landing_page": location.get("landing_page_url"),
                "authors": [
                    author.get("author", {}).get("display_name")
                    for author in authors[:5]
                    if author.get("author")
                ],
                "evidence_status": "candidate_unreviewed",
            }
        )
    return {
        "provider": "OpenAlex Works API",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "results_are": "discovery candidates, not verified evidence",
        "works": works,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Research assurance evidence and run verifier")
    commands = parser.add_subparsers(dest="command", required=True)

    questions_parser = commands.add_parser("questions", help="List unresolved profile decisions")
    questions_parser.add_argument("--profile", required=True)

    verify_parser = commands.add_parser("verify", help="Verify run evidence against a profile")
    verify_parser.add_argument("--profile", required=True)
    verify_parser.add_argument("--run", required=True)
    verify_parser.add_argument("--config", help="Exact configuration file whose SHA-256 is recorded in the run")
    verify_parser.add_argument("--output", help="Optional path to save the JSON report")

    search_parser = commands.add_parser("search-literature", help="Find candidate scholarly records in OpenAlex")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--output", help="Optional path to save the JSON results")

    trace_parser = commands.add_parser("trace", help="Number-level claim provenance and verification")
    trace_parser.add_argument("action", choices=["build", "verify", "slots", "inventory", "passport"])
    trace_parser.add_argument("--notebook", help="Path to executed notebook (.ipynb)")
    trace_parser.add_argument("--recon", help="Path to reconciliation ledger (.csv)")
    trace_parser.add_argument("--manuscript", help="Path to manuscript (.docx)")
    trace_parser.add_argument("--passport", help="Path to passport (.yaml)")
    trace_parser.add_argument("--blocks", help="Path to blocks data (.csv)")
    trace_parser.add_argument("--ledger", help="Path to ledger JSON")
    trace_parser.add_argument("--out", help="Path to output file")
    trace_parser.add_argument("--results", help="Optional path to results.json")

    args = parser.parse_args(argv)
    try:
        if args.command == "questions":
            profile = load_json(args.profile)
            errors = validate_profile(profile)
            if errors:
                raise AssuranceError("; ".join(errors))
            result = {
                "profile_id": profile["profile_id"],
                "unresolved_decisions": [
                    item for item in profile.get("questions", []) if item.get("status") != "resolved"
                ],
            }
            exit_code = 0
        elif args.command == "verify":
            profile = load_json(args.profile)
            run = load_json(args.run)
            result = verify(profile, run, args.profile, args.run, config_path=args.config)
            exit_code = 1 if result["verdict"] == "blocked" else 0
        elif args.command == "trace":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import trace
            trace_args = argparse.Namespace(
                c=args.action,
                notebook=args.notebook,
                recon=args.recon,
                manuscript=args.manuscript,
                passport=args.passport,
                blocks=args.blocks,
                ledger=args.ledger,
                out=args.out,
                results=args.results,
            )
            handler = {
                "build": trace.cmd_build,
                "verify": trace.cmd_verify,
                "slots": trace.cmd_slots,
                "inventory": trace.cmd_inventory,
                "passport": trace.cmd_passport,
            }[args.action]
            exit_code = handler(trace_args) or 0
            return exit_code
        else:
            result = search_openalex(args.query, args.limit)
            exit_code = 0
        rendered = json.dumps(result, indent=2, ensure_ascii=False)
        output_path = getattr(args, "output", None)
        if output_path:
            Path(output_path).write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return exit_code
    except AssuranceError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
