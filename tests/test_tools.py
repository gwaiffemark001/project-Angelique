import unittest

from core.tools import execute_tool


class ToolsTests(unittest.TestCase):
    def test_execute_tool_known_command_runs_shell(self):
        result = execute_tool("run_shell_command", {"command": "echo hello"})
        self.assertIsInstance(result, str)
        self.assertTrue("hello" in result.lower())

    def test_execute_tool_unknown_command_returns_error(self):
        self.assertEqual(execute_tool("not_a_tool", {}), "Error: Tool 'not_a_tool' not found.")

    def test_execute_tool_ignores_unexpected_args(self):
        result = execute_tool("run_shell_command", {"command": "echo hello", "extra": "ignored"})
        self.assertTrue("hello" in result.lower())


if __name__ == "__main__":
    unittest.main()
