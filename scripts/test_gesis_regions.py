"""Synthetic classifier cases; no fictitious fixture is published as source data."""
import unittest

from gesis_regions import dataset_eligibility, levels, period, variable_eligibility


class RegionalTests(unittest.TestCase):
    def test_country_coverage_and_incidental_abstract_do_not_make_regional_data(self):
        study = {"title": ["Income survey"], "geography": ["DE Germany"],
                 "analysis_unit": ["Individual"], "abstract": ["Age, income, marital status and Bundesland were asked."]}
        self.assertIsNone(dataset_eligibility(study))
        item = {"label": ["Monthly income"], "name": ["v123"], "parent_metadata": study}
        self.assertIsNone(variable_eligibility(item, None))

    def test_residence_is_geography_not_a_regional_indicator(self):
        item = {"label": ["Bundesland"], "name": ["v100"], "parent_metadata": {"geography": ["DE Deutschland"]}}
        result = variable_eligibility(item, None)
        self.assertEqual(result["classification"], "survey_geography_variable")
        self.assertEqual(result["spatial_levels"], ["Bundesländer"])
        self.assertEqual(result["nuts_levels"], [])

    def test_short_region_label_with_unrelated_code_is_retained(self):
        self.assertIsNotNone(variable_eligibility({"label": ["Region"], "name": ["v7"]}, None))

    def test_region_opinion_item_is_not_a_region_identifier(self):
        self.assertIsNone(variable_eligibility({"label": ["Satisfaction with regional development"], "name": ["v7"]}, None))
        self.assertIsNone(variable_eligibility({"label": ["Arbeiten Sie in Ihrem Wohnort?"], "name": ["v7"]}, None))
        self.assertIsNone(variable_eligibility({"label": ["Satisfaction with your Bundesland"], "name": ["v7"]}, None))

    def test_transliterated_german_state_labels(self):
        result = variable_eligibility({"label": ["Bundeslaender"], "name": ["v7"], "parent_metadata": {"geography": ["DE"]}}, None)
        self.assertEqual(result["spatial_levels"], ["Bundesländer"])

    def test_historical_constituencies_are_not_modern_districts(self):
        study = {"title": ["Reichstagswahlen"], "geography": ["DXDE Deutsches Reich"],
                 "universe": ["Ergebnisse der Reichstagswahlen je Wahlkreis"], "collection_dates": ["1890 - 1912"]}
        result = dataset_eligibility(study)
        self.assertEqual(result["classification"], "regional_dataset")
        self.assertEqual(result["spatial_levels"], ["Historische Wahlkreise"])
        self.assertEqual(result["nuts_levels"], [])

    def test_international_districts_do_not_become_german_kreise(self):
        self.assertEqual(levels("District of residence", False)[0], ["Districts (international)"])

    def test_explicit_nuts_is_preserved_but_not_inferred(self):
        self.assertEqual(levels("Landkreis", True)[1], [])
        self.assertEqual(levels("NUTS-2", False)[1], ["NUTS2"])

    def test_regional_survey_is_not_an_aggregate_dataset(self):
        study = {"title": ["Survey in municipalities"], "analysis_unit": ["Individual"],
                 "geography": ["DE Deutschland"], "universe": ["Residents of Gemeinden"]}
        self.assertEqual(dataset_eligibility(study)["classification"], "regional_study")

    def test_aggregate_parent_allows_actual_measure_variables(self):
        study = {"title": ["Regional accounts"], "analysis_unit": ["Aggregated data: Kreise"], "geography": ["DE Deutschland"]}
        parent = dataset_eligibility(study)
        self.assertEqual(parent["classification"], "regional_dataset")
        result = variable_eligibility({"label": ["Gross domestic product"], "name": ["gdp"]}, parent)
        self.assertEqual(result["classification"], "regional_dataset_variable")

    def test_temporal_coverage_does_not_use_publication_date(self):
        study = {"collection_dates": ["1900-1920"], "publication_date": ["2025"]}
        self.assertEqual(period(study)[:2], (1900, 1920))


if __name__ == "__main__":
    unittest.main()
