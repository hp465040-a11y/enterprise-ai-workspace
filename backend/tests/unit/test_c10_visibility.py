"""Offline anti-leak assertion checks; no providers or databases are invoked."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from investigation_api_c10_once import verify_model_visibility


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.allowed = dict(chunk_id="allowed-chunk", document_id="allowed-document",
                            vector_id="allowed-vector", document_filename="allowed.txt", content="Allowed body")
        self.denied = dict(chunk_id="foreign-chunk", document_id="foreign-document",
                           vector_id="foreign-vector", document_filename="restricted.txt", content="Foreign body")
        self.requests = [{"system": "Report", "tools": [], "messages": [
            {"role": "tool", "tool_name": "search_knowledge",
             "content": json.dumps({"status": "found", "sources": [self.allowed]})}]}]

    def test_allowed_source_is_required_and_visible(self):
        result = verify_model_visibility(self.requests, self.allowed, self.denied)
        self.assertTrue(all(result.values()))

    def test_each_foreign_identifier_or_body_is_rejected_in_every_input_surface(self):
        for token in [*self.denied.values(), "RESTRICTED-B"]:
            for surface in ("system", "tools", "messages"):
                with self.subTest(token=token, surface=surface):
                    requests = copy.deepcopy(self.requests)
                    if surface == "system":
                        requests[0][surface] = token
                    elif surface == "tools":
                        requests[0][surface] = [{"description": token}]
                    else:
                        requests[0][surface].append({"role": "assistant", "content": token})
                    with self.assertRaises(AssertionError):
                        verify_model_visibility(requests, self.allowed, self.denied)

    def test_no_context_or_no_authorized_source_cannot_pass(self):
        for requests in ([], [{"messages": [], "system": "", "tools": []}]):
            with self.subTest(requests=requests), self.assertRaises(AssertionError):
                verify_model_visibility(requests, self.allowed, self.denied)
