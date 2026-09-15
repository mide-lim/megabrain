from __future__ import annotations

import json
import subprocess
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "1d81048adef6c0a952ace232eb3944fad77ccd1a"
MGB010_PATH = ROOT / "workflows" / "MGB-010-entrada-reel.json"
MGB015_PATH = ROOT / "workflows" / "MGB-015-internal-dispatch-reel.json"
MGB020_PATH = ROOT / "workflows" / "MGB-020-download-reel.json"
MGB030_PATH = ROOT / "workflows" / "MGB-030-enrichment-reel.json"


class F33InternalOrchestrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mgb010 = json.loads(MGB010_PATH.read_text(encoding="utf-8"))
        cls.mgb015 = json.loads(MGB015_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def nodes(workflow: dict) -> dict[str, dict]:
        return {node["name"]: node for node in workflow["nodes"]}

    @staticmethod
    def successors(workflow: dict, name: str, output: int | None = None) -> set[str]:
        outputs = workflow["connections"].get(name, {}).get("main", [])
        selected = outputs if output is None else outputs[output : output + 1]
        return {
            edge["node"]
            for branch in selected
            for edge in branch
        }

    @staticmethod
    def predecessors(workflow: dict, name: str) -> set[str]:
        return {
            source
            for source in workflow["connections"]
            if name in F33InternalOrchestrationContractTests.successors(workflow, source)
        }

    @classmethod
    def can_reach_from_output(
        cls, workflow: dict, source: str, output: int, target: str
    ) -> bool:
        queue = deque(cls.successors(workflow, source, output))
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                queue.extend(cls.successors(workflow, current))
        return False

    @classmethod
    def can_reach(cls, workflow: dict, source: str, target: str) -> bool:
        queue = deque(cls.successors(workflow, source))
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                queue.extend(cls.successors(workflow, current))
        return False

    def test_mgb010_is_a_sanitized_fastapi_telegram_adapter(self) -> None:
        nodes = self.nodes(self.mgb010)
        self.assertFalse(
            any(node["type"] == "n8n-nodes-base.postgres" for node in nodes.values())
        )
        self.assertFalse(
            any(
                node["type"] == "n8n-nodes-base.executeWorkflow"
                for node in nodes.values()
            )
        )
        request = nodes["HTTP — Registrar Reel no FastAPI"]
        parameters = request["parameters"]
        self.assertEqual(parameters["method"], "POST")
        self.assertEqual(parameters["url"], "http://web:8000/internal/reels")
        self.assertEqual(parameters["genericAuthType"], "httpHeaderAuth")
        self.assertEqual(
            request["credentials"]["httpHeaderAuth"],
            {
                "id": "__CREDENTIAL_ID_N8N_TO_WEB_INGESTION__",
                "name": "__CREDENTIAL_NAME_N8N_TO_WEB_INGESTION__",
            },
        )
        extractor = nodes["DATA — Extrair request Telegram"]["parameters"]["jsCode"]
        self.assertIn("url: match[0]", extractor)
        self.assertNotIn("shortcode", extractor)
        self.assertNotIn("original_url", extractor)
        self.assertNotIn("status", extractor)
        self.assertIn("telegram:", extractor)
        self.assertIn("notification_chat_id", extractor)
        self.assertIn("url: $json.url", parameters["jsonBody"])
        self.assertIn("telegram: $json.telegram", parameters["jsonBody"])
        self.assertEqual(self.successors(self.mgb010, "IF — Dispatch aceito?", 0), set())
        self.assertEqual(
            self.successors(self.mgb010, "IF — Dispatch aceito?", 1),
            {"IF — Dispatch não requerido?"},
        )
        self.assertEqual(
            self.successors(self.mgb010, "IF — Dispatch não requerido?", 0),
            {"TG — Reel duplicado"},
        )
        self.assertEqual(
            self.successors(self.mgb010, "IF — Dispatch não requerido?", 1),
            {"TG — Processamento não confirmado"},
        )
        for notification in (
            "TG — Reel duplicado",
            "TG — Processamento não confirmado",
        ):
            chat_id = nodes[notification]["parameters"]["chatId"]
            self.assertIn("notification_chat_id", chat_id)
            self.assertIn("DATA — Extrair request Telegram", chat_id)
        self.assertNotIn(
            "TG — Reel registrado",
            {
                target
                for source in self.mgb010["connections"]
                for target in self.successors(self.mgb010, source)
            },
        )

    def test_mgb015_hands_off_before_exact_202_response(self) -> None:
        nodes = self.nodes(self.mgb015)
        webhook = nodes["Webhook — Internal Dispatch"]
        self.assertEqual(webhook["parameters"]["httpMethod"], "POST")
        self.assertEqual(webhook["parameters"]["path"], "megabrain-internal-dispatch")
        self.assertEqual(webhook["parameters"]["authentication"], "headerAuth")
        self.assertEqual(
            webhook["credentials"]["httpHeaderAuth"],
            {
                "id": "__CREDENTIAL_ID_WEB_TO_N8N_DISPATCH__",
                "name": "__CREDENTIAL_NAME_WEB_TO_N8N_DISPATCH__",
            },
        )
        validator = nodes["DATA — Validar body"]["parameters"]["jsCode"]
        self.assertIn("Object.keys(body).length === 1", validator)
        self.assertIn("Number.isSafeInteger", validator)
        self.assertIn("reel_id", validator)
        handoff = nodes["SUB — Acionar MGB-020"]
        self.assertEqual(handoff["parameters"]["options"]["waitForSubWorkflow"], False)
        self.assertEqual(
            handoff["parameters"]["workflowId"]["value"],
            "__WORKFLOW_ID_MGB_020__",
        )
        self.assertEqual(
            self.successors(self.mgb015, "IF — Payload válido?", 0),
            {"DATA — Preparar handoff"},
        )
        self.assertEqual(
            self.successors(self.mgb015, "DATA — Preparar handoff"),
            {"SUB — Acionar MGB-020"},
        )
        self.assertEqual(
            nodes["DATA — Preparar handoff"]["parameters"]["jsCode"],
            "return { reel_id: $json.reel_id };",
        )
        self.assertEqual(
            self.successors(self.mgb015, "SUB — Acionar MGB-020"),
            {"RESP — Aceito"},
        )
        self.assertEqual(
            self.successors(self.mgb015, "IF — Payload válido?", 1),
            {"RESP — Payload inválido"},
        )
        self.assertEqual(
            self.predecessors(self.mgb015, "RESP — Aceito"),
            {"SUB — Acionar MGB-020"},
        )
        self.assertEqual(
            self.predecessors(self.mgb015, "SUB — Acionar MGB-020"),
            {"DATA — Preparar handoff"},
        )
        self.assertEqual(
            self.predecessors(self.mgb015, "DATA — Preparar handoff"),
            {"IF — Payload válido?"},
        )
        self.assertTrue(
            self.can_reach_from_output(
                self.mgb015,
                "IF — Payload válido?",
                0,
                "RESP — Aceito",
            )
        )
        self.assertFalse(
            self.can_reach_from_output(
                self.mgb015,
                "IF — Payload válido?",
                1,
                "SUB — Acionar MGB-020",
            )
        )
        self.assertFalse(
            self.can_reach_from_output(
                self.mgb015,
                "IF — Payload válido?",
                1,
                "RESP — Aceito",
            )
        )
        for source in (
            "Webhook — Internal Dispatch",
            "DATA — Validar body",
            "IF — Payload válido?",
        ):
            self.assertNotIn("RESP — Aceito", self.successors(self.mgb015, source))
        accepted = nodes["RESP — Aceito"]["parameters"]
        self.assertEqual(accepted["options"]["responseCode"], 202)
        self.assertEqual(
            accepted["responseBody"],
            "={{ { accepted: true, reel_id: $('DATA — Preparar handoff').first().json.reel_id } }}",
        )
        self.assertNotIn("$json.reel_id", accepted["responseBody"])
        invalid = nodes["RESP — Payload inválido"]["parameters"]
        self.assertEqual(invalid["options"]["responseCode"], 422)
        self.assertIn("accepted: false", invalid["responseBody"])
        forbidden_types = {
            "n8n-nodes-base.postgres",
            "n8n-nodes-base.telegram",
        }
        self.assertFalse(
            any(node["type"] in forbidden_types for node in nodes.values())
        )
        serialized = json.dumps(self.mgb015)
        for forbidden_term in ("downloader", "enricher", "cloudflare_r2", "retry_count"):
            self.assertNotIn(forbidden_term, serialized.lower())

    def test_mgb020_and_mgb030_only_apply_the_f42_download_status_rename(self) -> None:
        def baseline_workflow(path: Path) -> dict:
            result = subprocess.run(
                ["git", "show", f"{BASELINE}:{path.relative_to(ROOT)}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            return json.loads(result.stdout)

        expected_mgb020 = baseline_workflow(MGB020_PATH)
        for node in expected_mgb020["nodes"]:
            query = node.get("parameters", {}).get("query")
            if isinstance(query, str) and "app.reels" in query:
                node["parameters"]["query"] = query.replace("status", "download_status").replace(
                    "download_failed", "failed"
                )
            text = node.get("parameters", {}).get("text")
            if isinstance(text, str) and "$json.status" in text:
                node["parameters"]["text"] = text.replace("$json.status", "$json.download_status")

        expected_mgb030 = baseline_workflow(MGB030_PATH)
        for node in expected_mgb030["nodes"]:
            query = node.get("parameters", {}).get("query")
            if isinstance(query, str) and "r.status" in query:
                node["parameters"]["query"] = query.replace("r.status", "r.download_status")

        self.assertEqual(json.loads(MGB020_PATH.read_text(encoding="utf-8")), expected_mgb020)
        self.assertEqual(json.loads(MGB030_PATH.read_text(encoding="utf-8")), expected_mgb030)


if __name__ == "__main__":
    unittest.main()
