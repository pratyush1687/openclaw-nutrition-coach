import unittest

from app.nutrition.parser import looks_like_food_log, parse_steps, parse_target_update, parse_water, parse_weight, rough_macro_estimate


class ParserTests(unittest.TestCase):
    def test_parse_weight(self):
        self.assertEqual(parse_weight("Weight 117.4"), 117.4)

    def test_parse_steps(self):
        self.assertEqual(parse_steps("8000 steps"), 8000)

    def test_parse_water(self):
        self.assertEqual(parse_water("water 2.2 litres"), 2.2)

    def test_rough_macro_estimate(self):
        estimate = rough_macro_estimate("2 eggs 2 rotis dal curd")
        self.assertGreater(estimate["calories"], 500)
        self.assertGreater(estimate["protein"], 25)

    def test_target_update(self):
        updates = parse_target_update("reduce the calories to 2300 permanently, and protien to 150g")
        self.assertEqual(updates["calories_kcal"], 2300)
        self.assertEqual(updates["protein_g"], 150)

    def test_settings_not_food(self):
        self.assertFalse(looks_like_food_log("reduce the calories to 2300 permanently"))

    def test_meal_is_food(self):
        self.assertTrue(looks_like_food_log("had 2 rotis dal and curd"))


if __name__ == "__main__":
    unittest.main()
