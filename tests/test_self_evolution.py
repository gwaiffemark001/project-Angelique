import os
import tempfile
import unittest

from skills.self_evolution import code_generator as cg


class SelfEvolutionTests(unittest.TestCase):
    def test_generate_skill_from_instruction_square_without_llm(self):
        skill_name, code = cg.generate_skill_from_instruction("Compute the square of 7", allow_llm=False)
        self.assertIsInstance(skill_name, str)
        self.assertIn("return 7 ** 2", code)

    def test_execute_generated_code_simple_function(self):
        code = "def main(**kwargs):\n    return kwargs.get('x', 0) + 1\n"
        result = cg.execute_generated_code(code, function_name="main", x=4)
        self.assertIn("✅ Code executed.", result)
        self.assertIn("5", result)

    def test_convert_webm_to_mp4_missing_source(self):
        result = cg.convert_webm_to_mp4("nonexistent_input.webm", "out.mp4")
        self.assertIn("Input file not found", result)

    def test_create_and_execute_skill_square_fallback(self):
        result = cg.create_and_execute_skill("Compute the square of 7")
        self.assertIn("✅ Skill", result)
        self.assertIn("Result", result)

        # Clean up any generated fallback skill file
        skill_name, _ = cg.generate_skill_from_instruction("Compute the square of 7", allow_llm=False)
        skill_path = os.path.join(cg.SKILLS_DIR, f"{skill_name}.py")
        if os.path.exists(skill_path):
            os.remove(skill_path)


if __name__ == '__main__':
    unittest.main()
