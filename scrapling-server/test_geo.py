"""Distances for place texts of result lists; mirrors tests/umkreis.test.mjs."""
import unittest

import geo


class Geo(unittest.TestCase):
    def test_schorndorf_is_not_averaged_with_the_bavarian_namesake(self):
        local = geo.center("Schorndorf")
        self.assertLess(geo.km(local, (48.80537, 9.52721)), 5)
        self.assertLess(geo.km(geo.center("Waiblingen"), local), 20)
        self.assertGreater(geo.km(local, geo.center("93489")), 200)
        self.assertEqual(geo.center("Schorndorf (Oberpfalz)"), geo.center("93489"))

    def test_center_never_averages_homonyms_across_the_country(self):
        _, by_key = geo.data()
        names = sorted({ort["name"] for orte in by_key.values() for ort in orte})
        ambiguous = 0
        for name in names:
            points = geo.resolve(name)
            if not points or len(geo.clusters(points)) < 2:
                continue
            ambiguous += 1
            self.assertLessEqual(min(geo.km(geo.center(name), p) for p in points), geo.CLUSTER_KM, name)
        self.assertGreater(ambiguous, 100)

    def test_known_homonyms_resolve_to_the_regional_place(self):
        for name, expected in (("Leonberg", (48.798, 9.013)), ("Lorch", (48.79, 9.69)), ("Urbach", (48.80, 9.58)),
                               ("Leutenbach", (48.88, 9.35)), ("Schorndorf", (48.805, 9.527))):
            with self.subTest(name=name):
                self.assertLess(geo.km(geo.center(name), expected), 15)

    def test_unambiguous_places_keep_their_mean(self):
        for name in ("Waiblingen", "Stuttgart", "Fellbach", "Welzheim", "Backnang", "Winnenden"):
            with self.subTest(name=name):
                points = geo.resolve(name)
                self.assertEqual(len(geo.clusters(points)), 1)
                self.assertEqual(geo.center(name), geo.mean(points))

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
