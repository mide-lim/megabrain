#!/usr/bin/env python3
import copy
import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "megabrain_deploy_capability.py"
spec = importlib.util.spec_from_file_location("deploy_capability", MODULE)
deploy = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(deploy)

ISSUE = "MEG-3"
COMMIT = "d9a3f3424e1deb734e871e0b2c16d0e633d53fe3"

def valid_gate():
    return {
        "id": "83d5976d-54e2-4222-9fe1-057192b928d1",
        "issue": ISSUE,
        "kind": "request_confirmation",
        "status": "accepted",
        "effectiveResolverPolicy": "human_only",
        "result": {"version": 1, "outcome": "accepted"},
        "payload": {
            "version": 1,
            "target": {
                "type": "custom",
                "key": "megabrain-production-deploy",
                "href": "/MEG/issues/MEG-3",
                "revisionId": COMMIT,
            },
        },
        "resolvedByUserId": "megabrain-owner",
        "resolvedByAgentId": None,
    }

class GateContractTest(unittest.TestCase):
    def test_accepts_explicit_human_bound_gate(self):
        self.assertTrue(deploy.gate_matches(valid_gate(), ISSUE, COMMIT))

    def test_rejects_generic_confirmation_without_target(self):
        gate = valid_gate()
        gate["payload"].pop("target")
        self.assertFalse(deploy.gate_matches(gate, ISSUE, COMMIT))

    def test_rejects_checkbox_contract(self):
        gate = valid_gate()
        gate["kind"] = "request_checkbox_confirmation"
        self.assertFalse(deploy.gate_matches(gate, ISSUE, COMMIT))

    def test_rejects_wrong_commit_binding(self):
        gate = valid_gate()
        gate["payload"]["target"]["revisionId"] = "0" * 40
        self.assertFalse(deploy.gate_matches(gate, ISSUE, COMMIT))

    def test_rejects_wrong_issue_binding(self):
        gate = valid_gate()
        gate["payload"]["target"]["href"] = "/MEG/issues/MEG-4"
        self.assertFalse(deploy.gate_matches(gate, ISSUE, COMMIT))

    def test_rejects_non_human_resolution(self):
        gate = valid_gate()
        gate["resolvedByUserId"] = None
        gate["resolvedByAgentId"] = "agent"
        self.assertFalse(deploy.gate_matches(gate, ISSUE, COMMIT))

    def test_rejects_rejected_outcome(self):
        gate = valid_gate()
        gate["result"]["outcome"] = "rejected"
        self.assertFalse(deploy.gate_matches(gate, ISSUE, COMMIT))

    def test_rejects_wrong_capability_key(self):
        gate = valid_gate()
        gate["payload"]["target"]["key"] = "other-capability"
        self.assertFalse(deploy.gate_matches(gate, ISSUE, COMMIT))

if __name__ == "__main__":
    unittest.main()
