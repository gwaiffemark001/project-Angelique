import unittest
from unittest.mock import patch

from brain.cognitive_loop import run_cognitive_loop
from brain.memory_manager import get_connection
from skills.conversation.chat_skill import clear_session, save_conversation


class CognitiveLoopTests(unittest.TestCase):
    def _clear_memory_db(self):
        conn = get_connection()
        conn.execute("DELETE FROM memory_log")
        conn.commit()
        conn.close()

    def setUp(self):
        clear_session("default")
        self._clear_memory_db()

    def tearDown(self):
        clear_session("default")
        self._clear_memory_db()

    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    @patch("brain.cognitive_loop.query_llm")
    def test_yes_uses_previous_question_as_followup(self, mock_query_llm, _mock_recall_facts):
        mock_query_llm.return_value = "Yes, I can check that for you now."
        save_conversation(
            "default",
            "remove packettracer 9.0.0",
            "Would you like me to check if it is installed and provide the correct command?",
        )

        response = run_cognitive_loop("yes")

        self.assertEqual(response, "Yes, I can check that for you now.")
        self.assertEqual(mock_query_llm.call_count, 1)

    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    @patch("brain.cognitive_loop.query_llm")
    def test_verify_then_continue_reply_stays_in_followup_context(self, mock_query_llm, _mock_recall_facts):
        mock_query_llm.return_value = "I verified it and I’ll continue executing now."
        save_conversation(
            "default",
            "remove packettracer 9.0.0",
            "Would you like me to check if it is installed and provide the correct command?",
        )

        response = run_cognitive_loop("verify that it’s true then continue executing")

        self.assertEqual(response, "I verified it and I’ll continue executing now.")
        self.assertEqual(mock_query_llm.call_count, 1)

    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    @patch("brain.cognitive_loop.query_llm")
    def test_recent_conversation_history_is_included_in_prompt(self, mock_query_llm, _mock_recall_facts):
        mock_query_llm.return_value = "In forex, a fair value gap is a price imbalance that often attracts reactions."
        save_conversation("default", "what is a fair value gap", "A fair value gap is a price imbalance between buyers and sellers.")

        run_cognitive_loop("explain it in terms of forex trading")

        messages = mock_query_llm.call_args.args[0]
        self.assertTrue(any(msg.get("role") == "user" and msg.get("content") == "what is a fair value gap" for msg in messages))
        self.assertTrue(any(msg.get("role") == "assistant" and "price imbalance" in msg.get("content", "") for msg in messages))
        self.assertTrue(any(msg.get("role") == "user" and msg.get("content") == "explain it in terms of forex trading" for msg in messages))

    @patch("brain.cognitive_loop.execute_tool")
    @patch("brain.cognitive_loop.extract_json_from_text", return_value={})
    @patch("brain.cognitive_loop.query_llm", return_value="I can answer that directly.")
    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    def test_questions_do_not_force_memory_lookup_before_reasoning(self, _mock_recall_facts, mock_query_llm, _mock_extract_json, mock_execute_tool):
        response = run_cognitive_loop("what is the capital of france?")

        self.assertEqual(response, "I can answer that directly.")
        self.assertGreaterEqual(mock_query_llm.call_count, 1)
        _mock_recall_facts.assert_not_called()
        mock_execute_tool.assert_not_called()

    @patch("brain.cognitive_loop.memory_manager.query_fact_memory", return_value=[])
    @patch("brain.cognitive_loop.memory_manager.get_facts_for_entity", return_value={"current": []})
    @patch("brain.cognitive_loop.execute_tool")
    @patch("brain.cognitive_loop.extract_json_from_text", return_value={})
    @patch("brain.cognitive_loop.query_llm", return_value="I am Angelique, your assistant.")
    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    def test_identity_questions_use_the_normal_loop(self, _mock_recall_facts, mock_query_llm, _mock_extract_json, mock_execute_tool, _mock_get_facts, _mock_query_fact_memory):
        response = run_cognitive_loop("what is your name?")

        self.assertEqual(response, "I am Angelique, your assistant.")
        self.assertGreaterEqual(mock_query_llm.call_count, 1)
        _mock_recall_facts.assert_not_called()
        mock_execute_tool.assert_not_called()

    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    def test_reexplain_without_subject_asks_for_clarification(self, _mock_recall_facts):
        response = run_cognitive_loop("please reexplain")

        self.assertEqual(response, "Sure, what exactly would you like me to reexplain?")
        _mock_recall_facts.assert_not_called()

    @patch("brain.cognitive_loop.train_angelique", return_value="Training complete.")
    @patch("brain.cognitive_loop.query_llm", return_value="I can answer that directly.")
    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    def test_plain_directive_text_triggers_training_flow(self, _mock_recall_facts, _mock_query_llm, mock_train_angelique):
        response = run_cognitive_loop("My primary trading platform is TradingView")

        self.assertEqual(response, "Training complete.")
        mock_train_angelique.assert_called_once_with("My primary trading platform is TradingView")

    @patch("brain.cognitive_loop.train_angelique", return_value="Training complete.")
    @patch("brain.cognitive_loop.query_llm", return_value="I can answer that directly.")
    @patch("brain.cognitive_loop.recall_facts", return_value="No new valid facts")
    def test_explicit_training_prefix_triggers_training_flow(self, _mock_recall_facts, _mock_query_llm, mock_train_angelique):
        response = run_cognitive_loop("[[TRAINING_MODE]] My primary trading platform is TradingView")

        self.assertEqual(response, "Training complete.")
        mock_train_angelique.assert_called_once_with("My primary trading platform is TradingView")


if __name__ == "__main__":
    unittest.main()