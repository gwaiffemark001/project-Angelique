import unittest
import os
from unittest.mock import patch, MagicMock

from brain.heuristic_engine import extract_command_heuristically
from brain.cognitive_loop import run_cognitive_loop
import brain.cognitive_loop as cognitive_loop
from brain import llm_interface
from core.tools import execute_tool
import core.tools as core_tools
from skills.conversation.chat_skill import save_conversation
from skills.os_control import system_cmds
from skills.os_control import app_discovery
from skills.voice import voice_interface


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

    @patch("core.tools.call_skill", return_value="system health ok")
    def test_execute_tool_falls_back_to_dynamic_skill_lookup(self, mock_call_skill):
        result = execute_tool("system_monitor", {})
        self.assertEqual(result, "system health ok")
        mock_call_skill.assert_called_once_with("system_monitor", {})

    def test_system_monitor_direct_tool_returns_health_dict_without_recursing(self):
        result = execute_tool("system_monitor.get_system_health", {})
        self.assertIsInstance(result, dict)
        self.assertIn("cpu_percent", result)

    @patch("brain.llm_interface.requests.post")
    def test_query_llm_prefers_remote_models_before_local(self, mock_post):
        original_priority = llm_interface.config.API_PRIORITY
        original_ollama_candidates = llm_interface.config.OLLAMA_MODEL_CANDIDATES
        original_openrouter_key = llm_interface.config.OPENROUTER_API_KEY
        try:
            llm_interface.config.API_PRIORITY = ["openrouter", "ollama"]
            llm_interface.config.OLLAMA_MODEL_CANDIDATES = ["qwen2.5:3b"]
            llm_interface.config.OPENROUTER_API_KEY = "remote-key"

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"choices": [{"message": {"content": "remote answer"}}]}
            mock_post.return_value = response

            result = llm_interface.query_llm([{"role": "user", "content": "hi"}])
            self.assertEqual(result, "remote answer")
            self.assertTrue(mock_post.call_args_list[0][0][0].startswith("https://openrouter.ai"))
        finally:
            llm_interface.config.API_PRIORITY = original_priority
            llm_interface.config.OLLAMA_MODEL_CANDIDATES = original_ollama_candidates
            llm_interface.config.OPENROUTER_API_KEY = original_openrouter_key

    @patch("brain.llm_interface.requests.post")
    def test_query_llm_falls_back_to_ollama_when_remote_is_unavailable(self, mock_post):
        original_priority = llm_interface.config.API_PRIORITY
        original_ollama_candidates = llm_interface.config.OLLAMA_MODEL_CANDIDATES
        original_openrouter_key = llm_interface.config.OPENROUTER_API_KEY
        original_nvidia_key = llm_interface.config.NVIDIA_API_KEY
        try:
            llm_interface.config.API_PRIORITY = ["openrouter", "ollama"]
            llm_interface.config.OLLAMA_MODEL_CANDIDATES = ["qwen2.5:3b"]
            llm_interface.config.OPENROUTER_API_KEY = ""
            llm_interface.config.NVIDIA_API_KEY = ""

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"message": {"content": "local answer"}}
            mock_post.return_value = response

            result = llm_interface.query_llm([{"role": "user", "content": "hi"}])
            self.assertEqual(result, "local answer")
            self.assertTrue(mock_post.call_args_list[0][0][0].endswith("/api/chat"))
        finally:
            llm_interface.config.API_PRIORITY = original_priority
            llm_interface.config.OLLAMA_MODEL_CANDIDATES = original_ollama_candidates
            llm_interface.config.OPENROUTER_API_KEY = original_openrouter_key
            llm_interface.config.NVIDIA_API_KEY = original_nvidia_key

    @patch("brain.cognitive_loop.query_llm")
    @patch("brain.cognitive_loop.execute_tool", return_value="balance ok")
    def test_resolve_user_query_dispatches_direct_tool_commands(self, mock_execute_tool, mock_query_llm):
        result = cognitive_loop.resolve_user_query("what is my mt5 account balance")
        self.assertEqual(result["answer"], "balance ok")
        self.assertEqual(result["source"], "tool")
        mock_execute_tool.assert_called_once_with("get_account_balance", {})
        mock_query_llm.assert_not_called()

    @patch("brain.cognitive_loop.query_llm")
    @patch("brain.cognitive_loop.execute_tool", return_value="folder created")
    def test_resolve_user_query_dispatches_folder_creation(self, mock_execute_tool, mock_query_llm):
        result = cognitive_loop.resolve_user_query("create a folder named feck on my desktop")
        self.assertEqual(result["answer"], "folder created")
        self.assertEqual(result["source"], "tool")
        mock_execute_tool.assert_called_once()
        self.assertEqual(mock_execute_tool.call_args.args[0], "manage_files")
        self.assertEqual(mock_execute_tool.call_args.args[1]["action"], "mkdir")
        mock_query_llm.assert_not_called()

    @patch("skills.voice.voice_interface._play_audio_file")
    @patch("skills.voice.voice_interface._generate_edge_tts")
    def test_speech_toggle_blocks_speak_when_disabled(self, mock_generate_edge_tts, mock_play_audio_file):
        original_state = voice_interface.is_speech_enabled()
        try:
            voice_interface.set_speech_enabled(False)
            with patch("skills.voice.voice_interface._is_online", return_value=True):
                voice_interface.speak("hello")
        finally:
            voice_interface.set_speech_enabled(original_state)

        mock_generate_edge_tts.assert_not_called()
        mock_play_audio_file.assert_not_called()

    def test_heuristic_routes_generic_skill_call(self):
        tool_name, args = extract_command_heuristically("use the system monitor skill")
        self.assertEqual(tool_name, "call_skill")
        self.assertEqual(args.get("skill_name"), "system monitor")

    def test_heuristic_routes_create_folder_command(self):
        tool_name, args = extract_command_heuristically("create a folder named feck on my desktop")
        self.assertEqual(tool_name, "manage_files")
        self.assertEqual(args.get("action"), "mkdir")
        self.assertTrue(str(args.get("path", "")).endswith("/Desktop/feck") or str(args.get("path", "")).endswith("\\Desktop\\feck"))

    def test_heuristic_routes_browser_open_command(self):
        tool_name, args = extract_command_heuristically("open a browser on my pc")
        self.assertEqual(tool_name, "open_app")
        self.assertEqual(args.get("app_name"), "firefox")

    def test_execute_tool_preserves_kwargs_for_recall_memory(self):
        original_function = core_tools.TOOL_REGISTRY["recall_memory"]["function"]
        mock_recall = MagicMock(return_value="memory hit")
        core_tools.TOOL_REGISTRY["recall_memory"]["function"] = mock_recall
        try:
            result = execute_tool("recall_memory", {"query": "what is my name"})
        finally:
            core_tools.TOOL_REGISTRY["recall_memory"]["function"] = original_function

        mock_recall.assert_called_once_with(query="what is my name")
        self.assertEqual(result, "memory hit")

    def test_heuristic_does_not_hardcode_uninstall(self):
        tool_name, args = extract_command_heuristically("uninstall cmatrix")
        self.assertIsNone(tool_name)
        self.assertEqual(args, {})

    def test_heuristic_routes_install_check_to_installation_status(self):
        tool_name, args = extract_command_heuristically("check if packettracer 9.0.0 is installed")
        self.assertEqual(tool_name, "check_installation_status")
        self.assertEqual(args.get("target_name"), "packettracer")

    def test_heuristic_routes_install_check_with_version_and_working(self):
        tool_name, args = extract_command_heuristically("check if packettracer 9.0.0 is installed and working")
        self.assertEqual(tool_name, "check_installation_status")
        self.assertEqual(args.get("target_name"), "packettracer")
        self.assertEqual(args.get("version"), "9.0.0")
        self.assertTrue(args.get("working"))

    def test_heuristic_routes_install_check_with_working_phrase(self):
        tool_name, args = extract_command_heuristically("check if gnome is installed and working")
        self.assertEqual(tool_name, "check_installation_status")
        self.assertEqual(args.get("target_name"), "gnome")
        self.assertTrue(args.get("working"))

    @patch("skills.os_control.app_discovery.get_installed_apps", return_value={})
    @patch("skills.os_control.app_discovery.subprocess.run")
    def test_check_installed_reports_missing_package(self, mock_run, _mock_apps):
        def fake_run(command, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "package packettracer is not installed"
            return result

        mock_run.side_effect = fake_run

        result = app_discovery.check_installed("packettracer")

        self.assertIn("does not appear to be installed", result)

    @patch("skills.os_control.app_discovery.get_installed_apps", return_value={})
    @patch("skills.os_control.app_discovery.subprocess.run")
    def test_check_installed_reports_version_mismatch(self, mock_run, _mock_apps):
        def fake_run(command, **kwargs):
            result = MagicMock()
            if command[:2] == ["dpkg", "-s"]:
                result.returncode = 0
                result.stdout = "Status: install ok installed\n"
                result.stderr = ""
                return result
            if command[:2] == ["dpkg-query", "-W"]:
                result.returncode = 0
                result.stdout = "packettracer\t9.0.1\n"
                result.stderr = ""
                return result
            result.returncode = 1
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = fake_run

        result = app_discovery.check_installed("packettracer", version="9.0.0")

        self.assertIn("version 9.0.0 was not found", result)

    @patch.dict(os.environ, {"DISPLAY": ":1"}, clear=False)
    @patch("skills.os_control.system_cmds.shutil.which")
    @patch("skills.os_control.system_cmds.subprocess.Popen")
    def test_run_shell_command_uses_pkexec_for_privileged_commands(self, mock_popen, mock_which):
        process = MagicMock()
        process.wait.return_value = 0
        mock_popen.return_value = process
        mock_which.side_effect = lambda name: "/usr/bin/pkexec" if name == "pkexec" else "/usr/bin/bash" if name == "bash" else None

        result = system_cmds.run_shell_command("apt-get remove cmatrix")

        mock_popen.assert_called_once()
        self.assertEqual(mock_popen.call_args.args[0][0], "/usr/bin/pkexec")
        self.assertIn("Interactive command finished with exit code: 0", result)

    @patch("skills.os_control.system_cmds.subprocess.Popen")
    def test_run_shell_command_uses_gui_password_when_provided(self, mock_popen):
        process = MagicMock()
        process.communicate.return_value = ("", "")
        process.returncode = 0
        mock_popen.return_value = process

        result = system_cmds.run_shell_command("apt-get remove cmatrix", sudo_password="secret")

        mock_popen.assert_called_once()
        self.assertEqual(mock_popen.call_args.args[0][:4], ["sudo", "-S", "-p", ""])
        process.communicate.assert_called_once()
        self.assertIn("Exit code: 0", result)

    @patch("skills.os_control.system_cmds.subprocess.Popen")
    def test_run_shell_command_auto_confirms_apt_commands(self, mock_popen):
        process = MagicMock()
        process.communicate.return_value = ("", "")
        process.returncode = 0
        mock_popen.return_value = process

        result = system_cmds.run_shell_command("apt-get remove cmatrix", sudo_password="secret", auto_confirm=True)

        mock_popen.assert_called_once()
        command_used = mock_popen.call_args.args[0][-1]
        self.assertIn("apt-get -y remove cmatrix", command_used)
        self.assertIn("Exit code: 0", result)

    @patch("skills.os_control.system_cmds.subprocess.Popen")
    def test_run_shell_command_uses_registered_callbacks(self, mock_popen):
        process = MagicMock()
        process.communicate.return_value = ("", "")
        process.returncode = 0
        mock_popen.return_value = process

        from skills.os_control.system_cmds import set_privileged_command_callbacks

        try:
            set_privileged_command_callbacks(
                confirm_callback=lambda command: True,
                password_callback=lambda command: "secret",
            )
            result = system_cmds.run_shell_command("apt-get remove cmatrix")
        finally:
            set_privileged_command_callbacks(None, None)

        mock_popen.assert_called_once()
        self.assertEqual(mock_popen.call_args.args[0][:4], ["sudo", "-S", "-p", ""])
        self.assertIn("Exit code: 0", result)

    @patch("skills.os_control.system_cmds.subprocess.Popen")
    def test_run_shell_command_uses_combined_privileged_callback(self, mock_popen):
        process = MagicMock()
        process.communicate.return_value = ("", "")
        process.returncode = 0
        mock_popen.return_value = process

        from skills.os_control.system_cmds import set_privileged_command_callbacks

        try:
            set_privileged_command_callbacks(
                privileged_callback=lambda command: {"confirmed": True, "password": "secret", "auto_confirm": True},
            )
            result = system_cmds.run_shell_command("apt-get remove cmatrix")
        finally:
            set_privileged_command_callbacks(None, None, None)

        mock_popen.assert_called_once()
        self.assertEqual(mock_popen.call_args.args[0][:4], ["sudo", "-S", "-p", ""])
        self.assertIn("Exit code: 0", result)

    @patch("brain.cognitive_loop.execute_tool", return_value="✅ packettracer checked")
    @patch("brain.cognitive_loop.extract_json_from_text", return_value={})
    @patch("brain.cognitive_loop.query_llm", side_effect=[None, "{}", "Retry complete"])
    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    def test_try_again_reuses_previous_install_request(self, _mock_recall, mock_query_llm, _mock_extract_json, mock_execute_tool):
        from brain.cognitive_loop import run_cognitive_loop

        save_conversation(
            "default",
            "check if gnome is installed and working",
            "I’m not sure yet.",
        )

        response = run_cognitive_loop("try again")

        self.assertEqual(response, "Retry complete")
        mock_execute_tool.assert_called_once()
        self.assertEqual(mock_execute_tool.call_args.args[0], "check_installation_status")
        self.assertEqual(mock_execute_tool.call_args.args[1]["target_name"], "gnome")
        self.assertTrue(mock_execute_tool.call_args.args[1]["working"])


if __name__ == "__main__":
    unittest.main()
