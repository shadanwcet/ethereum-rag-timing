import importlib.util
import json
import base64
import hashlib
import http.client
import sys
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "research-assurance" / "engine.py"
PROFILE_PATH = ROOT / "research-assurance" / "profiles" / "battery-estimation-pilot.json"
OBSERVATION_PATH = ROOT / "research-assurance" / "fixtures" / "battery-pilot-observations.json"

spec = importlib.util.spec_from_file_location("research_assurance_engine", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
sys.path.insert(0, str(ENGINE_PATH.parent))
import desktop_app


class RangeInvariantTests(unittest.TestCase):
    def setUp(self):
        self.rule = {
            "id": "SOC-BOUNDS",
            "type": "range",
            "target": "trace.soc",
            "minimum": 0.0,
            "maximum": 1.0,
        }

    def test_accepts_values_inside_declared_range(self):
        result = engine.check_range(self.rule, {"soc": [0.0, 0.5, 1.0]})
        self.assertEqual(result["status"], "passed")

    def test_rejects_out_of_range_ground_truth(self):
        result = engine.check_range(self.rule, {"soc": [0.5, -0.01, 1.0]})
        self.assertEqual(result["status"], "failed")
        self.assertIn("-0.01", result["detail"])

    def test_blocks_missing_or_malformed_trace(self):
        self.assertEqual(engine.check_range(self.rule, {})["status"], "blocked")
        self.assertEqual(engine.check_range(self.rule, {"soc": []})["status"], "blocked")
        self.assertEqual(engine.check_range(self.rule, {"soc": [True]})["status"], "blocked")


class TimingInvariantTests(unittest.TestCase):
    def setUp(self):
        self.rule = {"id": "TIMING", "type": "event_alignment"}

    def test_accepts_aligned_predict_update_sequence(self):
        trace = {
            "estimator_events": [
                {"event": "predict", "state_from_index": 0, "state_to_index": 1, "input_time_index": 0},
                {"event": "update", "state_time_index": 1, "measurement_time_index": 1},
            ]
        }
        self.assertEqual(engine.check_event_alignment(self.rule, trace)["status"], "passed")

    def test_rejects_update_using_measurement_from_previous_step(self):
        trace = {
            "estimator_events": [
                {"event": "predict", "state_from_index": 0, "state_to_index": 1, "input_time_index": 0},
                {"event": "update", "state_time_index": 1, "measurement_time_index": 0},
            ]
        }
        result = engine.check_event_alignment(self.rule, trace)
        self.assertEqual(result["status"], "failed")
        self.assertIn("uses measurement t=0", result["detail"])

    def test_rejects_prediction_with_wrong_input_index(self):
        trace = {
            "estimator_events": [
                {"event": "predict", "state_from_index": 0, "state_to_index": 1, "input_time_index": 1}
            ]
        }
        self.assertEqual(engine.check_event_alignment(self.rule, trace)["status"], "failed")


class EvidenceAndProvenanceTests(unittest.TestCase):
    def test_profile_requires_referenced_evidence(self):
        profile = {
            "schema_version": "1.0",
            "profile_id": "test",
            "research_question": "test",
            "questions": [],
            "evidence": [],
            "invariants": [{"id": "R1", "type": "range", "minimum": 0, "maximum": 1, "evidence_ids": ["MISSING"]}],
        }
        self.assertIn("references unknown evidence MISSING", "; ".join(engine.validate_profile(profile)))

    def test_reproducibility_requires_matching_recorded_runs(self):
        run = {"replicates": []}
        self.assertEqual(engine.compare_replicates(run)["status"], "not_verified")
        replicate = {
            "profile_id": "p",
            "profile_sha256": "d" * 64,
            "config_sha256": "a" * 64,
            "outputs": [{"path": "result.json", "sha256": "b" * 64}],
        }
        run["replicates"] = [replicate, dict(replicate)]
        self.assertEqual(engine.compare_replicates(run)["status"], "matching_recorded_runs")
        run["replicates"][1]["config_sha256"] = "c" * 64
        self.assertEqual(engine.compare_replicates(run)["status"], "mismatch")

    def test_claim_audit_blocks_unreviewed_and_external_claims(self):
        profile = {
            "evidence": [
                {"id": "E1", "status": "observed_not_independently_reviewed"},
                {
                    "id": "E2",
                    "status": "reviewed_attestation",
                    "reviewer": "domain-reviewer",
                    "reviewed_at": "2026-10-28",
                },
            ]
        }
        run = {
            "claims": [
                {"id": "C1", "text": "The method is accurate", "scope": "synthetic_model", "evidence_ids": ["E1"]},
                {"id": "C2", "text": "The method works on real cells", "scope": "external_empirical", "evidence_ids": ["E2"]},
            ]
        }
        result = engine.audit_claims(run, profile)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("not independently reviewed", result["results"][0]["issues"][0])
        self.assertIn("not validated by this MVP", result["results"][1]["issues"][0])

    def test_literature_search_labels_results_as_unreviewed_candidates(self):
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.example/paper",
                    "title": "Battery estimation study",
                    "publication_year": 2024,
                    "type": "article",
                    "primary_location": {"landing_page_url": "https://example.org/paper", "source": {"display_name": "Journal"}},
                    "authorships": [{"author": {"display_name": "A. Author"}}],
                }
            ]
        }
        with patch.object(engine, "urlopen", return_value=BytesIO(json.dumps(payload).encode("utf-8"))):
            result = engine.search_openalex("LFP state of charge estimation", 1)
        self.assertEqual(result["works"][0]["evidence_status"], "candidate_unreviewed")
        self.assertEqual(result["works"][0]["doi"], "https://doi.org/10.example/paper")


class DesktopAppTests(unittest.TestCase):
    def test_uploaded_verification_checks_config_and_artifact_bytes(self):
        profile_bytes = PROFILE_PATH.read_bytes()
        config_bytes = b'{"seed": 1}'
        output_bytes = b'{"value": 7}\n'
        output_hash = hashlib.sha256(output_bytes).hexdigest()
        payload = {
            "profile_base64": base64.b64encode(profile_bytes).decode("ascii"),
            "config_base64": base64.b64encode(config_bytes).decode("ascii"),
            "run": {
                "run_id": "desktop-test",
                "profile_id": "battery-estimation-synthetic-pilot-v1",
                "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
                "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
                "outputs": [{"path": "results.json", "sha256": output_hash}],
                "replicates": [],
                "trace": {},
            },
            "files": [
                {"path": "results.json", "content_base64": base64.b64encode(output_bytes).decode("ascii")}
            ],
        }
        report = desktop_app.verify_uploaded_payload(payload)
        self.assertEqual(report["dimensions"]["configuration_integrity"]["status"], "passed")
        self.assertEqual(report["dimensions"]["artifact_integrity"][0]["status"], "passed")
        self.assertEqual(report["verdict"], "blocked")

    def test_upload_verification_rejects_config_hash_mismatch(self):
        payload = {
            "profile_base64": base64.b64encode(PROFILE_PATH.read_bytes()).decode("ascii"),
            "config_base64": base64.b64encode(b"wrong config").decode("ascii"),
            "run": {"config_sha256": "a" * 64},
            "files": [],
        }
        with self.assertRaisesRegex(desktop_app.RequestError, "does not match"):
            desktop_app.verify_uploaded_payload(payload)

    def test_upload_rejects_path_traversal(self):
        with self.assertRaisesRegex(desktop_app.RequestError, "Unsafe output path"):
            desktop_app.normalize_output_name("../outside.txt")
        with self.assertRaisesRegex(desktop_app.RequestError, "Unsafe output path"):
            desktop_app.normalize_output_name("C:\\outside.txt")

    def test_local_server_serves_app_and_rejects_cross_origin(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), desktop_app.ResearchAssuranceHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/", headers={"Host": "127.0.0.1:{}".format(server.server_port)})
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertIn(b"Research Assurance", body)
            self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
            connection.close()

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/api/pilot-profile", headers={"Host": "127.0.0.1:{}".format(server.server_port)})
            response = connection.getresponse()
            pilot = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(pilot["profile_id"], "battery-estimation-synthetic-pilot-v1")
            connection.close()

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            with patch.object(desktop_app.engine, "search_openalex", return_value={"works": []}):
                connection.request(
                    "POST",
                    "/api/search",
                    body=b'{"query":"test","limit":1}',
                    headers={
                        "Host": "127.0.0.1:{}".format(server.server_port),
                        "Origin": "http://127.0.0.1:{}".format(server.server_port),
                        "Content-Type": "application/json",
                    },
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
            connection.close()

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request(
                "POST",
                "/api/search",
                body=b'{"query":"test","limit":1}',
                headers={
                    "Host": "127.0.0.1:{}".format(server.server_port),
                    "Origin": "https://attacker.example",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_artifact_digest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "output.txt"
            path.write_text("verified output", encoding="utf-8")
            expected = engine.sha256_file(path)
            run = {"outputs": [{"path": "output.txt", "sha256": expected}]}
            self.assertEqual(engine.verify_artifacts(run, temp_dir)[0]["status"], "passed")
            path.write_text("changed output", encoding="utf-8")
            self.assertEqual(engine.verify_artifacts(run, temp_dir)[0]["status"], "failed")

    def test_artifact_path_cannot_escape_run_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run = {"outputs": [{"path": "..\\outside.txt", "sha256": "a" * 64}]}
            result = engine.verify_artifacts(run, temp_dir)[0]
            self.assertEqual(result["status"], "failed")
            self.assertIn("escapes", result["detail"])

    def test_battery_pilot_observations_pass_bounds_but_expose_timing_and_trace_gaps(self):
        profile = engine.load_json(PROFILE_PATH)
        run = engine.load_json(OBSERVATION_PATH)
        checks = {}
        for rule in profile["invariants"]:
            if rule["type"] == "range":
                checks[rule["id"]] = engine.check_range(rule, run["trace"])
            else:
                checks[rule["id"]] = engine.check_event_alignment(rule, run["trace"])
        self.assertEqual(checks["SOC-TRUTH-BOUNDS"]["status"], "passed")
        self.assertEqual(checks["SOC-CLAMP-TRACE"]["status"], "blocked")
        self.assertEqual(checks["ESTIMATOR-TIME-ALIGNMENT"]["status"], "failed")

    def test_soc_mutation_is_caught_by_battery_profile(self):
        profile = engine.load_json(PROFILE_PATH)
        run = engine.load_json(OBSERVATION_PATH)
        run["trace"]["soc_true_extrema_by_episode"][5][0] = -0.01
        rule = next(rule for rule in profile["invariants"] if rule["id"] == "SOC-TRUTH-BOUNDS")
        self.assertEqual(engine.check_range(rule, run["trace"])["status"], "failed")




class ProvenanceTraceTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ENGINE_PATH.parent))
        import trace
        self.trace = trace

    def test_recipe_extractor_extracts_primary_and_ablation(self):
        rec_abl = self.trace.recipe_for("ablation.v2_paper_baseline.coef")
        self.assertIsNotNone(rec_abl)
        self.assertEqual(rec_abl["cell"], 82)

        rec_llm = self.trace.recipe_for("primary.llm_retrieval.fee_reduction")
        self.assertIsNotNone(rec_llm)
        self.assertEqual(rec_llm["cell"], 44)

    def test_apply_extracts_value_from_simulated_cell_output(self):
        simulated_cell_44 = "| `llm_retrieval` | 96 | 35s | **0.48%** [-1.22, 2.12] |"
        rec = self.trace.recipe_for("primary.llm_retrieval.fee_reduction")
        val = self.trace.apply(rec, {44: simulated_cell_44})
        self.assertEqual(val, 0.48)

    def test_comparison_of_detects_unmatched_comparator(self):
        simulated_cell_44 = "| `llm_retrieval` | 96 | 35s | **0.48%** | -3.95 pp | 0.0416 |"
        comp = self.trace.comparison_of("primary.llm_retrieval.holm_p", {44: simulated_cell_44})
        self.assertIsNotNone(comp)
        self.assertEqual(comp["difference_pp"], -3.95)
        self.assertEqual(comp["id"], "vs_unmatched_heuristic_157s_1600swaps")

    def test_fault_injection_detects_discrepancy(self):
        simulated_cell = "| `llm_retrieval` | 96 | 35s | **0.11%** [-1.22, 2.12] |"
        rec = self.trace.recipe_for("primary.llm_retrieval.fee_reduction")
        val = self.trace.apply(rec, {44: simulated_cell})
        # Reported is 0.48, tolerance is 0.1
        self.assertFalse(abs(val - 0.48) <= 0.1)


if __name__ == "__main__":
    unittest.main()
