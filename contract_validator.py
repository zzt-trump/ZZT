"""Contract Validator: static analysis of Skill Contract JSON files.

Checks 12+ items per contract:
  1. Requirement ID uniqueness
  2. Capability references existing requirements
  3. Capability produces existing evidence
  4. Completion requires existing evidence
  5. Binding references existing tool name
  6. Version field present
  7. No unreachable capabilities (all have satisfiable requires)
  8. No orphan requirements (all referenced by at least one capability)
  9. No circular dependencies among capabilities
 10. All capabilities have a path to __final__
 11. Schema version compatibility
 12. High-risk actions have permission declarations

Usage:
    python -m production_bench.stateful.validators.contract_validator
    python contract_validator.py --contracts-dir path/to/contracts/
"""

from __future__ import annotations

import json
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    file: str
    check: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class ValidationReport:
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, file: str, check: str, message: str) -> None:
        self.errors.append(ValidationError(file, check, message, "error"))

    def add_warning(self, file: str, check: str, message: str) -> None:
        self.warnings.append(ValidationError(file, check, message, "warning"))

    def merge(self, other: ValidationReport) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


# ---------------------------------------------------------------------------
# High-risk binding patterns for check #12
# ---------------------------------------------------------------------------

HIGH_RISK_PATTERNS = ["write", "execute", "delete", "modify", "setpoint", "control_valve", "control_output"]


def _is_high_risk(binding_name: str) -> bool:
    # Only match control-related patterns, but exclude "control_response" (analysis tool)
    lower = binding_name.lower()
    if "control_response" in lower:
        return False
    return any(pattern in lower for pattern in HIGH_RISK_PATTERNS)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class ContractValidator:
    """Validates one or more Skill Contract JSON files."""

    def __init__(self, contracts_dir: str | Path) -> None:
        self.contracts_dir = Path(contracts_dir)
        self._contracts: dict[str, dict] = {}  # filename → parsed JSON
        self._reports: dict[str, ValidationReport] = {}

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_contracts(self) -> list[str]:
        """Load all .json contract files from the directory. Returns list of filenames."""
        if not self.contracts_dir.is_dir():
            raise FileNotFoundError(f"Contracts directory not found: {self.contracts_dir}")
        loaded = []
        for fp in sorted(self.contracts_dir.glob("*.json")):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._contracts[fp.name] = data
                self._reports[fp.name] = ValidationReport()
                loaded.append(fp.name)
            except (json.JSONDecodeError, OSError) as exc:
                report = ValidationReport()
                report.add_error(fp.name, "parse", f"Cannot parse: {exc}")
                self._reports[fp.name] = report
        return loaded

    def _report(self, filename: str) -> ValidationReport:
        return self._reports[filename]

    def _contract(self, filename: str) -> dict:
        return self._contracts[filename]

    # ------------------------------------------------------------------
    # Check 1: requirement ID uniqueness
    # ------------------------------------------------------------------

    def check_req_id_uniqueness(self, filename: str) -> None:
        c = self._contract(filename)
        reqs = c.get("requirements", [])
        seen: set[str] = set()
        for r in reqs:
            rid = r.get("id")
            if rid is None:
                self._report(filename).add_error(filename, "req-id-unique", "requirement missing 'id' key")
            elif rid in seen:
                self._report(filename).add_error(filename, "req-id-unique", f"duplicate requirement id: {rid}")
            else:
                seen.add(rid)

    # ------------------------------------------------------------------
    # Check 2: capability references existing requirements
    # ------------------------------------------------------------------

    def check_cap_refs_reqs(self, filename: str) -> None:
        c = self._contract(filename)
        req_ids = {r["id"] for r in c.get("requirements", []) if "id" in r}
        ev_ids = set(c.get("evidence_types", {}).keys())
        valid_ids = req_ids | ev_ids  # requires can reference both requirements and evidence
        for cap in c.get("capabilities", []):
            for rid in cap.get("requires", []):
                if rid not in valid_ids:
                    self._report(filename).add_error(
                        filename, "cap-refs-req",
                        f"capability '{cap.get('id','?')}' requires unknown id '{rid}'"
                    )

    # ------------------------------------------------------------------
    # Check 3: capability produces existing evidence
    # ------------------------------------------------------------------

    def check_cap_produces_evidence(self, filename: str) -> None:
        c = self._contract(filename)
        ev_ids = set(c.get("evidence_types", {}).keys())
        ev_ids.add("__final__")  # special marker
        for cap in c.get("capabilities", []):
            for eid in cap.get("produces", []):
                if eid not in ev_ids:
                    self._report(filename).add_error(
                        filename, "cap-produces-evidence",
                        f"capability '{cap.get('id','?')}' produces unknown evidence '{eid}'"
                    )

    # ------------------------------------------------------------------
    # Check 4: completion requires existing evidence
    # ------------------------------------------------------------------

    def check_completion_evidence(self, filename: str) -> None:
        c = self._contract(filename)
        ev_ids = set(c.get("evidence_types", {}).keys())
        for eid in c.get("completion", {}).get("requires", []):
            if eid not in ev_ids:
                self._report(filename).add_error(
                    filename, "completion-evidence",
                    f"completion requires unknown evidence '{eid}'"
                )

    # ------------------------------------------------------------------
    # Check 5: binding references existing tool name
    # ------------------------------------------------------------------

    def check_binding_tool_exists(self, filename: str) -> None:
        c = self._contract(filename)
        bindings = c.get("bindings", {})
        for cap in c.get("capabilities", []):
            binding = cap.get("binding")
            if binding is None:
                self._report(filename).add_error(
                    filename, "binding-tool",
                    f"capability '{cap.get('id','?')}' missing 'binding' field"
                )
            elif binding == "noop":
                continue  # noop is always valid
            elif binding not in bindings:
                self._report(filename).add_error(
                    filename, "binding-tool",
                    f"capability '{cap.get('id','?')}' binding '{binding}' not found in bindings"
                )

    # ------------------------------------------------------------------
    # Check 6: version field present
    # ------------------------------------------------------------------

    def check_version_present(self, filename: str) -> None:
        c = self._contract(filename)
        version = c.get("version")
        if not version or not isinstance(version, str) or not version.strip():
            self._report(filename).add_error(
                filename, "version-present",
                "contract missing or empty 'version' field"
            )

    # ------------------------------------------------------------------
    # Check 7: no unreachable capabilities (BFS from input-satisfiable caps)
    # ------------------------------------------------------------------

    def check_reachable_capabilities(self, filename: str) -> None:
        """BFS: start with capabilities whose requires are all input-type requirements.
        Track which evidence becomes available. Flag any capability that can never fire."""
        c = self._contract(filename)
        caps = c.get("capabilities", [])
        reqs = c.get("requirements", [])
        input_ids = {r["id"] for r in reqs if r.get("type") == "input" and "id" in r}

        available_evidence: set[str] = set()
        fired: set[str] = set()

        changed = True
        while changed:
            changed = False
            for cap in caps:
                cid = cap.get("id", "")
                if cid in fired:
                    continue
                needs = set(cap.get("requires", []))
                if needs.issubset(input_ids | available_evidence):
                    fired.add(cid)
                    produces = set(cap.get("produces", [])) - {"__final__"}
                    available_evidence.update(produces)
                    changed = True

        for cap in caps:
            cid = cap.get("id", "")
            if cid not in fired:
                self._report(filename).add_warning(
                    filename, "reachable-caps",
                    f"capability '{cid}' may be unreachable (requires not satisfiable from inputs)"
                )

    # ------------------------------------------------------------------
    # Check 8: no orphan requirements (non-input, not referenced by any capability)
    # ------------------------------------------------------------------

    def check_orphan_requirements(self, filename: str) -> None:
        c = self._contract(filename)
        all_reqs = {r["id"] for r in c.get("requirements", []) if "id" in r}
        referenced: set[str] = set()
        for cap in c.get("capabilities", []):
            referenced.update(cap.get("requires", []))
        input_ids = {r["id"] for r in c.get("requirements", []) if r.get("type") == "input" and "id" in r}
        orphans = (all_reqs - referenced) - input_ids
        for rid in sorted(orphans):
            self._report(filename).add_error(
                filename, "orphan-req",
                f"requirement '{rid}' is not referenced by any capability and is not an input"
            )

    # ------------------------------------------------------------------
    # Check 9: no circular dependencies among capabilities
    # ------------------------------------------------------------------

    def check_circular_dependencies(self, filename: str) -> None:
        """Detect cycles in the capability dependency graph."""
        c = self._contract(filename)
        caps = c.get("capabilities", [])
        cap_ids = {cap["id"] for cap in caps if "id" in cap}

        evidence_to_producer: dict[str, str] = {}
        for cap in caps:
            for ev in cap.get("produces", []):
                if ev != "__final__":
                    evidence_to_producer[ev] = cap["id"]

        adj: dict[str, set[str]] = {cid: set() for cid in cap_ids}
        for cap in caps:
            for req_ev in cap.get("requires", []):
                producer = evidence_to_producer.get(req_ev)
                if producer and producer in cap_ids and producer != cap["id"]:
                    adj[producer].add(cap["id"])

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {cid: WHITE for cid in cap_ids}

        def dfs(node: str, path: list[str]) -> list[str] | None:
            color[node] = GRAY
            path.append(node)
            for neighbor in adj.get(node, set()):
                if color.get(neighbor) == GRAY:
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]
                if color.get(neighbor) == WHITE:
                    cycle = dfs(neighbor, list(path))
                    if cycle is not None:
                        return cycle
            color[node] = BLACK
            return None

        for cid in sorted(cap_ids):
            if color[cid] == WHITE:
                cycle = dfs(cid, [])
                if cycle:
                    self._report(filename).add_error(
                        filename, "circular-deps",
                        f"circular dependency: {' → '.join(cycle)}"
                    )
                    return

    # ------------------------------------------------------------------
    # Check 10: all capabilities have a path to __final__
    # ------------------------------------------------------------------

    def check_path_to_final(self, filename: str) -> None:
        """Reverse BFS from __final__-producing caps to ensure every cap can reach completion."""
        c = self._contract(filename)
        caps = c.get("capabilities", [])
        cap_ids = {cap["id"] for cap in caps if "id" in cap}

        final_producers = {cap["id"] for cap in caps if "__final__" in cap.get("produces", [])}
        if not final_producers:
            self._report(filename).add_error(
                filename, "path-to-final",
                "no capability produces __final__"
            )
            return

        evidence_to_producer: dict[str, str] = {}
        for cap in caps:
            for ev in cap.get("produces", []):
                if ev != "__final__":
                    evidence_to_producer[ev] = cap["id"]

        reverse_adj: dict[str, set[str]] = {cid: set() for cid in cap_ids}
        for cap in caps:
            for req_ev in cap.get("requires", []):
                producer = evidence_to_producer.get(req_ev)
                if producer and producer in cap_ids:
                    reverse_adj[cap["id"]].add(producer)

        reachable: set[str] = set(final_producers)
        queue = deque(final_producers)
        while queue:
            node = queue.popleft()
            for prev in reverse_adj.get(node, set()):
                if prev not in reachable:
                    reachable.add(prev)
                    queue.append(prev)

        dead_ends = cap_ids - reachable
        for cid in sorted(dead_ends):
            self._report(filename).add_warning(
                filename, "path-to-final",
                f"capability '{cid}' has no path to __final__"
            )

    # ------------------------------------------------------------------
    # Check 11: schema version compatibility
    # ------------------------------------------------------------------

    def check_schema_version(self, filename: str) -> None:
        c = self._contract(filename)
        version = c.get("version", "")
        if not version.startswith("v"):
            self._report(filename).add_warning(
                filename, "schema-version",
                f"version '{version}' does not follow 'vN' convention"
            )
        if not c.get("skill_id"):
            self._report(filename).add_error(
                filename, "schema-version",
                "contract missing 'skill_id' field"
            )
        if not c.get("domain"):
            self._report(filename).add_warning(
                filename, "schema-version",
                "contract missing 'domain' field"
            )

    # ------------------------------------------------------------------
    # Check 12: high-risk actions have permission declarations
    # ------------------------------------------------------------------

    def check_high_risk_permissions(self, filename: str) -> None:
        c = self._contract(filename)
        bindings = c.get("bindings", {})
        permissions = c.get("permissions", [])

        for bname, bdef in bindings.items():
            if isinstance(bdef, dict):
                tool = bdef.get("tool", bname)
            else:
                tool = bname
            if _is_high_risk(tool) and not permissions:
                self._report(filename).add_warning(
                    filename, "high-risk-perms",
                    f"binding '{bname}' ({tool}) looks high-risk but no 'permissions' declared"
                )

    # ------------------------------------------------------------------
    # Run all checks
    # ------------------------------------------------------------------

    CHECKS = [
        "check_req_id_uniqueness",
        "check_cap_refs_reqs",
        "check_cap_produces_evidence",
        "check_completion_evidence",
        "check_binding_tool_exists",
        "check_version_present",
        "check_reachable_capabilities",
        "check_orphan_requirements",
        "check_circular_dependencies",
        "check_path_to_final",
        "check_schema_version",
        "check_high_risk_permissions",
    ]

    def validate_all(self) -> dict[str, ValidationReport]:
        """Run all checks on all loaded contracts."""
        for fn in list(self._contracts.keys()):
            for check_name in self.CHECKS:
                getattr(self, check_name)(fn)
        return dict(self._reports)

    def print_report(self) -> int:
        """Print a human-readable report. Returns 0 if all valid, 1 if errors."""
        total_errors = 0
        total_warnings = 0
        all_filenames = sorted(self._reports.keys())

        for fn in all_filenames:
            report = self._reports[fn]
            if report.errors:
                print(f"\n=== {fn} — {len(report.errors)} ERROR(S) ===")
                for err in report.errors:
                    print(f"  [{err.check}] {err.message}")
                total_errors += len(report.errors)
            if report.warnings:
                for w in report.warnings:
                    print(f"  [WARNING:{w.check}] {w.message}")
                total_warnings += len(report.warnings)

        n = len(all_filenames)
        checks_per = len(self.CHECKS)
        print(f"\n{'='*60}")
        if total_errors == 0:
            print(f"All contracts valid ({n} contracts, {checks_per} checks each, {total_warnings} warnings)")
        else:
            print(f"FAILED: {total_errors} error(s), {total_warnings} warning(s) across {n} contracts")
        return 0 if total_errors == 0 else 1


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate Skill Contract JSON files")
    parser.add_argument(
        "--contracts-dir",
        default=None,
        help="Path to contracts directory (default: auto-detect relative to this file)",
    )
    args = parser.parse_args(argv)

    if args.contracts_dir:
        contracts_dir = Path(args.contracts_dir)
    else:
        this_file = Path(__file__).resolve()
        contracts_dir = this_file.parent.parent / "contracts"

    if not contracts_dir.is_dir():
        print(f"ERROR: contracts directory not found: {contracts_dir}")
        return 1

    validator = ContractValidator(contracts_dir)
    validator.load_contracts()
    validator.validate_all()
    return validator.print_report()


if __name__ == "__main__":
    sys.exit(main())