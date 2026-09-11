from __future__ import annotations

import json
import subprocess
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / "workflows" / "MGB-020-download-reel.json"
BASELINE = "8d401cb34894998dec2d871183c3998521c3e162"


class Mgb020ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}
        cls.connections = cls.workflow["connections"]

    def node(self, name: str) -> dict:
        return self.nodes[name]

    def successors(self, name: str, output: int | None = None) -> set[str]:
        outputs = self.connections.get(name, {}).get("main", [])
        selected = outputs if output is None else outputs[output : output + 1]
        return {
            edge["node"]
            for branch in selected
            for edge in branch
        }

    def predecessors(self, name: str) -> set[str]:
        return {
            source
            for source in self.connections
            if name in self.successors(source)
        }

    def can_reach(self, source: str, target: str, output: int | None = None) -> bool:
        queue = deque(self.successors(source, output))
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                queue.extend(self.successors(current))
        return False

    def test_input_normalization_accepts_canonical_and_legacy_ids_only(self) -> None:
        code = self.node("DATA — Normalizar entrada")["parameters"]["jsCode"]
        self.assertIn("$json.reel_id ?? $json.id", code)
        self.assertIn("Number.isSafeInteger", code)
        self.assertIn("return { reel_id: reelId };", code)
        self.assertNotIn("telegram_chat_id", code)

    def test_atomic_claim_is_limited_and_emits_claim_diagnostics(self) -> None:
        query = self.node("DB — Reivindicar processamento")["parameters"]["query"]
        self.assertIn("UPDATE app.reels", query)
        self.assertIn("status IN ('received', 'download_failed')", query)
        eligibility = query.split("AND status IN", 1)[1].split("RETURNING", 1)[0]
        self.assertEqual(eligibility.strip(), "('received', 'download_failed')")
        self.assertIn("TRUE AS claimed", query)
        self.assertIn("AS reel_exists", query)
        for output in (
            "id",
            "shortcode",
            "original_url",
            "telegram_chat_id",
            "status",
        ):
            self.assertIn(output, query)
        self.assertNotIn("retry_count =", query)
        self.assertEqual(
            self.successors("DATA — Normalizar entrada"),
            {"DB — Reivindicar processamento"},
        )

    def test_processing_is_gated_only_by_claimed_and_unclaimed_stops(self) -> None:
        claimed_if = self.node("IF — Reivindicado?")
        conditions = claimed_if["parameters"]["conditions"]["conditions"]
        self.assertEqual(len(conditions), 1)
        self.assertIn("$json.claimed", conditions[0]["leftValue"])
        self.assertFalse(
            self.can_reach(
                "IF — Reivindicado?",
                "HTTP — Worker Downloader",
                output=1,
            )
        )
        self.assertFalse(
            self.can_reach(
                "IF — Reivindicado?",
                "DB — Marcar downloaded",
                output=1,
            )
        )

    def test_downloader_request_is_canonical_and_not_telegram_coupled(self) -> None:
        request = self.node("HTTP — Worker Downloader")["parameters"]["jsonBody"]
        self.assertIn("item_id:", request)
        self.assertIn("shortcode:", request)
        self.assertIn("url:", request)
        self.assertNotIn("telegram_chat_id", request)
        self.assertEqual(
            self.successors("HTTP — Worker Downloader", 0),
            {"DATA — Validar resposta Downloader"},
        )

    def test_success_response_validation_precedes_guarded_persistence(self) -> None:
        validator = self.node("DATA — Validar resposta Downloader")["parameters"]["jsCode"]
        self.assertIn("valid_response: false", validator)
        self.assertIn("DOWNLOADER_INVALID_RESPONSE", validator)
        self.assertIn("claim.id", validator)
        self.assertIn("claim.shortcode", validator)
        self.assertIn("cloudflare_r2", validator)
        self.assertIn("^[a-f0-9]{64}$", validator)
        self.assertIn("has_video", validator)
        self.assertEqual(
            self.successors("DATA — Validar resposta Downloader"),
            {"IF — Resposta Downloader válida?"},
        )
        self.assertEqual(
            self.successors("IF — Resposta Downloader válida?", 0),
            {"DB — Marcar downloaded"},
        )
        downloaded = self.node("DB — Marcar downloaded")["parameters"]
        self.assertIn("AND status = 'downloading'", downloaded["query"])
        self.assertIn("$('DB — Reivindicar processamento').item.json.id", downloaded["options"]["queryReplacement"])
        self.assertNotIn("$json.item_id,", downloaded["options"]["queryReplacement"])

    def test_mgb030_follows_only_successful_downloaded_persistence(self) -> None:
        self.assertEqual(
            self.predecessors("SUB — Enriquecer Reel"),
            {"DB — Marcar downloaded"},
        )
        self.assertIn(
            "SUB — Enriquecer Reel",
            self.successors("DB — Marcar downloaded"),
        )

    def test_telegram_notifications_are_conditional_nonfatal_and_not_required(self) -> None:
        for if_name, telegram_name in (
            ("IF — Tem chat Telegram inicial?", "TG — Download iniciado"),
            ("IF — Tem chat Telegram sucesso?", "TG — Download concluído"),
            ("IF — Tem chat Telegram falha?", "TG — Falha no download"),
        ):
            self.assertIn(telegram_name, self.successors(if_name, 0))
            self.assertEqual(self.node(telegram_name)["onError"], "continueRegularOutput")

        self.assertIn(
            "HTTP — Worker Downloader",
            self.successors("IF — Tem chat Telegram inicial?", 1),
        )
        self.assertIn(
            "SUB — Enriquecer Reel",
            self.successors("DB — Marcar downloaded"),
        )

    def test_failure_normalization_and_guarded_failure_persistence(self) -> None:
        normalizer = self.node("DATA — Normalizar falha Downloader")["parameters"]["jsCode"]
        for code in (
            "DOWNLOAD_FAILED",
            "DOWNLOADER_INTERNAL_ERROR",
            "DOWNLOADER_INVALID_RESPONSE",
            "DOWNLOADER_REQUEST_FAILED",
        ):
            self.assertIn(code, normalizer)
        self.assertIn("claim.id", normalizer)
        self.assertIn("slice(0, 512)", normalizer)
        self.assertIn(
            "DATA — Normalizar falha Downloader",
            self.successors("HTTP — Worker Downloader", 1),
        )
        self.assertIn(
            "DATA — Normalizar falha Downloader",
            self.successors("IF — Resposta Downloader válida?", 1),
        )
        failure = self.node("DB — Registrar falha")["parameters"]
        self.assertIn("retry_count = retry_count + 1", failure["query"])
        self.assertIn("AND status = 'downloading'", failure["query"])
        self.assertIn("$('DB — Reivindicar processamento').item.json.id", failure["options"]["queryReplacement"])

    def test_legacy_workflows_remain_unchanged_from_baseline(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                BASELINE,
                "--",
                "workflows/MGB-010-entrada-reel.json",
                "workflows/MGB-030-enrichment-reel.json",
            ],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
