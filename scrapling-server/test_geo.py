"""Distances for place texts of result lists; mirrors tests/umkreis.test.mjs."""
import unittest

import geo


class Geo(unittest.TestCase):
    def test_distances_match_the_netlify_implementation(self):
        backnang = geo.center("Backnang")
        self.assertAlmostEqual(geo.distance_km(backnang, "04103 Leipzig, Deutschland"), 338.32, places=1)
        self.assertEqual(geo.distance_km(backnang, "Stuttgart / 71522 Backnang"), 0)
        self.assertLess(geo.distance_km(backnang, "Winnenden, Württemberg, BADEN_WUERTTEMBERG"), 10)

    def test_federal_states_are_not_places_and_trailing_state_words_are_ignored(self):
        backnang = geo.center("Backnang")
        self.assertIsNone(geo.distance_km(backnang, "Sachsen"))
        self.assertGreater(geo.distance_km(backnang, "Leipzig Sachsen DE"), 300)

    def test_in_range_is_unknown_for_multi_site_teasers_and_unresolvable_places(self):
        origin = geo.center("Waiblingen")
        self.assertTrue(geo.in_range(origin, "Schwäbisch Gmünd, Deutschland", 50))
        self.assertFalse(geo.in_range(origin, "74564 Crailsheim, Deutschland", 50))
        self.assertIsNone(geo.in_range(origin, "04103 Leipzig, Deutschland+", 50))
        self.assertIsNone(geo.in_range(origin, "Xyzdorf, Deutschland", 50))
        self.assertIsNone(geo.in_range(origin, "", 50))
        self.assertIsNone(geo.center("Xyzdorf"))


if __name__ == "__main__":
    unittest.main()
