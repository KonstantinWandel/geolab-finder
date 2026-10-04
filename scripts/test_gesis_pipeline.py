"""Offline RDF, identity and additional-source registry checks."""
import json
from pathlib import Path
import tempfile
import unittest

from pyoxigraph import NamedNode, RdfFormat, Store

from build_gesis_metadata import graph_dataset, make_item, merge_metadata, study_key
from harvest_gesis import KG, SCHEMA
from import_gesis_bulk import canonical, resource, triples
from registry_extras import supplement_sources
from gesis_regions import dataset_eligibility, variable_eligibility


class PipelineTests(unittest.TestCase):
    def test_activity_in_a_neighbourhood_is_not_a_geographic_identifier(self):
        self.assertIsNone(variable_eligibility({"label": ["Cinema visits in another Stadtteil"], "name": ["v7"]}, None))
        self.assertIsNotNone(variable_eligibility({"label": ["Stadtteil des Wohnorts"], "name": ["v7"]}, None))
        self.assertIsNotNone(variable_eligibility({"label": ["Wahlkreisnummer"], "name": ["v7"]}, None))
        self.assertIsNone(variable_eligibility({"label": ["Wollen Sie in Ihrem Bundesland bleiben?"], "name": ["v7"]}, None))
        self.assertIsNone(variable_eligibility({"label": ["Gruende fuer weniger Kinder - junge Menschen in alte Bundeslaender gezogen"], "name": ["v7"]}, None))
        self.assertIsNotNone(variable_eligibility({"label": ["P7 REGION - GERMANY NUTS 1"], "name": ["v7"]}, None))
        for label in ("HE.BUNDESLAND", "[*] Bundesland", "Geburtsland: Bundesland", "Bundestagswahlkreis", "BIK-Ortsgröße", "F16 Statistik: Bundesland", "Regierungsbezirk", "Geographic coordinate (lon)"):
            self.assertIsNotNone(variable_eligibility({"label": [label], "name": ["v7"]}, None), label)
        self.assertIsNone(variable_eligibility({"label": ["Verbundenheitsbatterie: Bundesland"], "name": ["v7"]}, None))
        self.assertIsNone(variable_eligibility({"label": ["Gewichtungsfaktor, basierend auf Bundesland"], "name": ["v7"]}, None))

    def test_study_bookkeeping_is_not_an_aggregate_indicator(self):
        parent = {"classification": "regional_dataset", "evidence": "Regional accounts"}
        self.assertIsNone(variable_eligibility({"label": ["ZA STUDY IDENTIFICATION"], "name": ["v1"]}, parent))

    def test_variable_iri_is_provenance_and_browser_link_opens_study(self):
        metadata = {"title": ["A survey"], "geography": ["Germany"], "kg": True}
        variable = {"label": ["Bundesland"], "name": ["v1"], "study_id": "ZA1234"}
        eligible = variable_eligibility({**variable, "parent_metadata": metadata}, None)
        item = make_item("provider-variable", metadata, eligible, variable, "https://data.gesis.org/gesiskg/resource/provider-variable")
        self.assertEqual(item["indicator_url"], "https://search.gesis.org/research_data/ZA1234")
        self.assertEqual(item["link_level"], "dataset")
        self.assertEqual(item["variable_name"], "v1")
        self.assertTrue(item["metadata_resource_uri"].endswith("provider-variable"))
        self.assertNotIn("Metadatenquelle", item["embedding_context"])
        self.assertIn("Metadatenquelle", item["rich_description"])

    def test_geography_field_does_not_inherit_study_topic_or_date_boilerplate(self):
        metadata = {"title": ["Environment survey"], "geography": ["Germany"], "kg": True,
                    "topics": ["Energy", "Housing"], "collection_dates": ["2013-02-04", "2013-02-07"]}
        variable = {"label": ["Bundesland"], "name": ["v1"], "study_id": "ZA1234"}
        eligible = variable_eligibility({**variable, "parent_metadata": metadata}, None)
        item = make_item("provider-variable", metadata, eligible, variable, "https://example.org/variable")
        self.assertEqual(item["theme"], "Geografie / Kontext")
        self.assertEqual(item["study_topics"], ["Energy", "Housing"])
        self.assertEqual(item["available_years_text"], "2013")
        self.assertIn("2013-02-07", item["collection_periods"])

    def test_subnational_coverage_is_a_study_not_a_nuts_indicator(self):
        metadata = {"title": ["Local survey"], "geography": ["DE-NW Nordrhein-Westfalen"],
                    "analysis_unit": ["Individuals"]}
        eligible = dataset_eligibility(metadata)
        self.assertEqual(eligible["classification"], "regional_study")
        self.assertEqual(eligible["nuts_levels"], [])

    def test_city_aggregates_and_coordinate_fields_are_discoverable(self):
        metadata = {"title": ["Staedtedaten"], "analysis_unit": ["Cities"], "geography": ["Germany"]}
        self.assertEqual(dataset_eligibility(metadata)["classification"], "regional_dataset")
        self.assertEqual(variable_eligibility({"label": ["Longitude"]}, None)["spatial_levels"], ["Adressen/Koordinaten"])

    def test_grid_survey_is_regional_but_not_an_aggregate_dataset(self):
        metadata = {"title": ["Georeferenced opinion study"], "analysis_unit": ["Individuals assigned to grid cells"],
                    "geography": ["Germany"], "universe": ["Individuals"]}
        eligible = dataset_eligibility(metadata)
        self.assertEqual(eligible["classification"], "regional_study")
        self.assertEqual(eligible["spatial_levels"], ["Rasterzellen"])
        self.assertEqual(eligible["nuts_levels"], [])
        self.assertIsNone(variable_eligibility({"label": ["Job satisfaction"]}, eligible))
        self.assertIsNotNone(variable_eligibility({"label": ["Grid cell identifier"]}, eligible))

    def test_geospatial_datatype_does_not_invent_a_level(self):
        metadata = {"title": ["Restricted context study"], "data_kind": ["Geospatial"], "universe": ["Individuals"]}
        eligible = dataset_eligibility(metadata)
        self.assertEqual(eligible["classification"], "regional_study")
        self.assertEqual(eligible["spatial_levels"], ["Weitere Gliederungen"])
        self.assertEqual(eligible["nuts_levels"], [])

    def test_mixed_survey_abstract_does_not_promote_all_variables(self):
        metadata = {"title": ["Sozialoekologische Studie"], "geography": ["DE Deutschland"],
                    "abstract": ["Zusaetzlich verkodet: aggregierte Regionaldaten fuer die Gemeinden."],
                    "universe": ["Deutsche in der Einwohnermeldekartei"],
                    "collection_method": ["Muendliche Befragung mit Fragebogen"]}
        eligible = dataset_eligibility(metadata)
        self.assertEqual(eligible["classification"], "regional_study")
        self.assertIsNone(variable_eligibility({"name": ["v1"], "label": ["Berufszufriedenheit"]}, eligible))

    def test_distant_abstract_terms_are_not_regional_evidence(self):
        metadata = {"title": ["National accounts"], "geography": ["Germany"],
                    "abstract": ["Public finances of municipalities. " + "National series. " * 100 + "Aggregated investment."]}
        self.assertIsNone(dataset_eligibility(metadata))

    def test_tweet_and_parliament_member_units_are_not_regional_aggregates(self):
        for unit in ("Tweets", "Members of Parliament"):
            metadata = {"title": ["Regional data study"], "geography": ["Districts in the United States"],
                        "analysis_unit": [unit], "universe": [unit],
                        "abstract": ["Aggregated counts per county are also available."]}
            self.assertEqual(dataset_eligibility(metadata)["classification"], "regional_study")

    def test_rdf_parser_preserves_languages_links_and_newlines(self):
        store = Store()
        store.load(input=b'''@prefix s: <https://schema.org/> .
          <https://example.org/a> s:name "Zeile\\nZwei"@de, "English"@en ;
          s:about <https://example.org/region> .''', format=RdfFormat.TURTLE)
        fields = resource(store, NamedNode("https://example.org/a"))
        self.assertEqual({v["language"] for v in fields[SCHEMA + "name"]}, {"de", "en"})
        self.assertIn("Zeile\nZwei", {v["value"] for v in fields[SCHEMA + "name"]})
        self.assertEqual(fields[SCHEMA + "about"][0]["type"], "uri")
        self.assertEqual(len(triples(fields)), 3)

    def test_api_and_rdf_literal_encodings_are_equivalent(self):
        self.assertEqual(canonical({"value": "x", "type": "literal"}),
                         canonical({"value": "x", "type": "typed-literal", "datatype": "http://www.w3.org/2001/XMLSchema#string"}))
        self.assertNotEqual(canonical({"value": "x", "type": "literal", "xml:lang": "de"}),
                            canonical({"value": "x", "type": "literal", "xml:lang": "en"}))

    def test_study_ids_merge_without_losing_doi_underscores(self):
        self.assertEqual(study_key("oai:dbk.gesis.org:SDN/10.7802_1933", {}), "SDN-10.7802-1933")
        self.assertEqual(study_key("oai:dbk.gesis.org:SDN/10.7802_a_b", {}), "SDN-10.7802-a_b")
        self.assertEqual(study_key("oai:dbk.gesis.org:DBK/ZA8145", {}), "ZA8145")

    def test_access_and_original_aliases_survive_merging(self):
        fields = {SCHEMA + "name": [{"value": "English", "type": "literal", "language": "en"},
                                    {"value": "Deutsch", "type": "literal", "language": "de"}],
                  SCHEMA + "conditionsOfAccess": [{"value": "Restricted", "type": "literal"}],
                  KG + "doi": [{"value": "10.example/x", "type": "literal"}]}
        metadata = graph_dataset(fields)
        self.assertEqual(metadata["title"], ["Deutsch", "English"])
        merged = merge_metadata(metadata, {"access": ["On request"], "oai_identifier": "fixture"})
        merged = merge_metadata(merged, {"oai_identifier": ""})
        self.assertEqual(merged["access"], ["Restricted", "On request"])
        self.assertEqual(merged["oai_identifier"], "fixture")
        self.assertEqual(merge_metadata({"variables": [{"id": "v1"}]}, {"variables": [{"id": "v1"}, {"id": "v2"}]}),
                         {"variables": [{"id": "v1"}, {"id": "v2"}]})
        self.assertEqual(merge_metadata({"abstract": ["Same\ntext"]}, {"abstract": ["Same text"]}),
                         {"abstract": ["Same\ntext"]})

    def test_additions_are_idempotent_and_cannot_replace_workbook_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "additional_sources.json").write_text(json.dumps({"sources": [{"slug": "gesis", "name": "GESIS"}]}))
            source = [{"slug": "inkar", "name": "INKAR"}]
            result = supplement_sources(source, folder)
            self.assertEqual(result, supplement_sources(result, folder))
            self.assertEqual(source, [{"slug": "inkar", "name": "INKAR"}])
            with self.assertRaisesRegex(ValueError, "collides"):
                supplement_sources([{"slug": "gesis"}], folder)


if __name__ == "__main__":
    unittest.main()
