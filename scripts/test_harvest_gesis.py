"""Offline fixtures for completeness checks and provider-format fallbacks."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from xml.etree import ElementTree as ET

from harvest_gesis import Client, NS, SCHEMA, decode_triples, ddi_record, harvest_oai


def record(metadata, identifier="fixture:study", deleted=False):
    status = ' status="deleted"' if deleted else ""
    return ET.fromstring(f'<record xmlns="{NS["o"]}"><header{status}><identifier>{identifier}</identifier>'
                         f'<datestamp>2026-01-02</datestamp></header><metadata>{metadata}</metadata></record>')


class HarvestTests(unittest.TestCase):
    def test_ddi_preserves_access_and_period_attributes(self):
        node = record(f'''<codeBook xmlns="{NS['d']}"><stdyDscr><citation><titlStmt>
          <titl>Fixture study</titl></titlStmt></citation><stdyInfo><sumDscr>
          <timePrd date="1900" event="start"/></sumDscr></stdyInfo><dataAccs><setAvail>
          <avlStatus>Restricted</avlStatus></setAvail></dataAccs></stdyDscr></codeBook>''')
        identifier, data = ddi_record(node)
        self.assertEqual(identifier, "fixture:study")
        self.assertEqual(data["access_status"], ["Restricted"])
        self.assertEqual(data["date_attributes"], [{"date": "1900", "event": "start"}])

    def test_deleted_does_not_request_fallback(self):
        self.assertEqual(ddi_record(record("", deleted=True))[1], {"deleted": True})

    def test_broken_ddi_uses_dara_then_dc(self):
        calls = []

        class Fake:
            def get(self, url, params, path):
                calls.append(params["metadataPrefix"])
                if params["metadataPrefix"] == "oai_dara":
                    return f'<OAI-PMH xmlns="{NS["o"]}"><error code="cannotDisseminateFormat"/></OAI-PMH>'.encode()
                node = record(f'<dc xmlns="{NS["odc"]}" xmlns:d="{NS["dc"]}"><d:title>DC fixture</d:title></dc>')
                return f'<OAI-PMH xmlns="{NS["o"]}"><GetRecord>{ET.tostring(node, encoding="unicode")}</GetRecord></OAI-PMH>'.encode()

        data = ddi_record(record('<Error>Provider conversion failure</Error>'), Fake())[1]
        self.assertEqual(data["title"], ["DC fixture"])
        self.assertEqual(calls, ["oai_dara", "oai_dc"])

    def test_no_format_is_a_recorded_gap(self):
        class Empty:
            def get(self, *args):
                return f'<OAI-PMH xmlns="{NS["o"]}"><error code="cannotDisseminateFormat"/></OAI-PMH>'.encode()
        self.assertIn("metadata_error", ddi_record(record(""), Empty())[1])

    def test_rdf_uri_literal_and_embedded_newlines_survive(self):
        counts = [{"id": {"value": "fixture"}, "triples": {"value": "2"}}]
        rows = [{"id": {"value": "fixture"}, "p": {"value": SCHEMA + "name"},
                 "o": {"value": "Line one\nLine two", "type": "literal", "xml:lang": "de"}},
                {"id": {"value": "fixture"}, "p": {"value": SCHEMA + "about"},
                 "o": {"value": "https://example.org/region", "type": "uri"}}]
        fields = decode_triples(rows, counts)["fixture"]
        self.assertEqual(fields[SCHEMA + "name"][0]["value"], "Line one\nLine two")
        self.assertEqual(fields[SCHEMA + "about"][0]["type"], "uri")
        counts[0]["triples"]["value"] = "3"
        with self.assertRaisesRegex(ValueError, "Truncated"):
            decode_triples(rows, counts)

    def test_oai_tokens_are_exhausted_without_search_restrictions(self):
        calls = []

        class Fake:
            def get(self, url, params, path):
                calls.append(params)
                page = len(calls)
                node = record("", identifier=f"fixture:{page}", deleted=True)
                token = '<resumptionToken>next</resumptionToken>' if page == 1 else '<resumptionToken/>'
                return f'<OAI-PMH xmlns="{NS["o"]}"><ListRecords>{ET.tostring(node, encoding="unicode")}{token}</ListRecords></OAI-PMH>'.encode()

        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE documents(kind TEXT,id TEXT,payload TEXT,PRIMARY KEY(kind,id))")
        report = harvest_oai(Fake(), db, "de")
        self.assertEqual(report["records"], 2)
        self.assertEqual(calls[1], {"verb": "ListRecords", "resumptionToken": "next"})
        self.assertNotIn("set", calls[0])

    def test_cache_cannot_be_reused_for_another_query(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            target = folder / "raw/page.xml"
            target.parent.mkdir()
            target.write_bytes(b"fixture")
            target.with_suffix(".xml.meta.json").write_text(json.dumps({"url": "https://example.org/old", "sha256": "bad"}))
            with self.assertRaisesRegex(ValueError, "mismatch"):
                Client(folder, 0).get("https://example.org/new", {}, "page.xml")


if __name__ == "__main__":
    unittest.main()
