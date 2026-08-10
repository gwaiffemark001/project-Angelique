import os
import tempfile
import unittest
from unittest.mock import patch

from core import config
from brain.memory_manager import save_fact_to_db
from skills.memory.memory_tools import recall_facts, _parse_training_text


class MemoryToolsTests(unittest.TestCase):
    @patch("skills.memory.memory_tools.semantic_search", return_value=[])
    @patch("skills.memory.memory_tools.get_facts_for_entity")
    @patch("skills.memory.memory_tools.get_all_entities", return_value=["User"])
    def test_relationship_query_returns_direct_fact(self, _mock_entities, mock_facts, _mock_semantic):
        mock_facts.return_value = {
            "current": [
                {"key": "girlfriend name", "value": "Angelique Moesha", "importance": 7, "context": "introducing partner", "timestamp": "2026-01-01 12:00:00"}
            ],
            "history": [],
        }

        response = recall_facts(query="who is my girlfriend")

        self.assertIn("Angelique Moesha", response)
        self.assertNotIn("Current facts about", response)
        self.assertNotIn("Memory Search Results", response)

    @patch("skills.memory.memory_tools.semantic_search", return_value=[])
    @patch("skills.memory.memory_tools.get_facts_for_entity")
    @patch("skills.memory.memory_tools.get_all_entities", return_value=["User"])
    def test_personal_name_query_returns_user_name(self, _mock_entities, mock_facts, _mock_semantic):
        mock_facts.return_value = {
            "current": [
                {"key": "name", "value": "Mark", "importance": 8, "context": "self introduction", "timestamp": "2026-01-02 10:00:00"}
            ],
            "history": [],
        }

        response = recall_facts(query="what is my name")

        self.assertEqual(response, "Your name is Mark.")
        self.assertNotIn("Current facts about", response)
        self.assertNotIn("Memory Search Results", response)

    @patch("skills.memory.memory_tools.semantic_search", return_value=[])
    @patch("skills.memory.memory_tools.get_facts_for_entity")
    @patch("skills.memory.memory_tools.get_all_entities", return_value=["User"])
    def test_relationship_name_query_returns_direct_name(self, _mock_entities, mock_facts, _mock_semantic):
        mock_facts.return_value = {
            "current": [
                {"key": "girlfriend name", "value": "Angelique Moesha", "importance": 7, "context": "introducing partner", "timestamp": "2026-01-01 12:00:00"}
            ],
            "history": [],
        }

        response = recall_facts(query="what is my girlfriend's name")

        self.assertEqual(response, "Your girlfriend's name is Angelique Moesha.")
        self.assertNotIn("Current facts about", response)
        self.assertNotIn("Memory Search Results", response)

    @patch("skills.memory.memory_tools.semantic_search")
    def test_relationship_name_query_prefers_real_name_over_relationship_word(self, mock_semantic):
        mock_semantic.return_value = [
            {"entity": "User", "key": "girlfriend name", "value": "girlfriend", "importance": 5, "context": "", "type": "fact"},
            {"entity": "User", "key": "girlfriend name", "value": "Angelique Moesha", "importance": 8, "context": "corrected name", "type": "fact"},
        ]

        response = recall_facts(query="what is my girlfriend's name")

        self.assertIn("Angelique Moesha", response)
        self.assertNotIn("I remember that your girlfriend name is girlfriend", response)

    @patch("skills.memory.memory_tools.semantic_search", return_value=[])
    @patch("skills.memory.memory_tools.get_facts_for_entity")
    @patch("skills.memory.memory_tools.get_all_entities", return_value=["User"])
    def test_preference_query_returns_direct_value(self, _mock_entities, mock_facts, _mock_semantic):
        mock_facts.return_value = {
            "current": [
                {"key": "favorite food", "value": "pizza", "importance": 4, "context": "talking about preferences", "timestamp": "2026-08-02 11:00:00"}
            ],
            "history": [],
        }

        response = recall_facts(query="what is my favourite food")

        self.assertIn("pizza", response)
        self.assertNotIn("Current facts about", response)

    @patch("skills.memory.memory_tools.semantic_search", return_value=[])
    @patch("skills.memory.memory_tools.get_facts_for_entity")
    @patch("skills.memory.memory_tools.get_all_entities", return_value=["User"])
    def test_relationship_query_does_not_return_unrelated_preference(self, _mock_entities, mock_facts, _mock_semantic):
        mock_facts.return_value = {
            "current": [
                {"key": "favorite food", "value": "pizza", "importance": 4, "context": "talking about preferences", "timestamp": "2026-08-02 11:00:00"}
            ],
            "history": [],
        }

        response = recall_facts(query="who is my girlfriend")

        self.assertNotIn("pizza", response)
        self.assertNotIn("Your favorite food is", response)
        self.assertIn("I don't have any information about your girlfriend yet", response)

    @patch("skills.memory.memory_tools.semantic_search", return_value=[])
    @patch("skills.memory.memory_tools.search_conversation_memory", return_value=[
        {"entity": "User", "key": "conversation", "value": "You told me your favorite color is blue.", "importance": 6, "context": "conversation", "type": "conversation"}
    ])
    def test_conversation_recall_returns_chat_snippet(self, _mock_conversation, _mock_semantic):
        response = recall_facts(query="what did i tell you about my favorite color")

        self.assertNotIn("I remember this from our conversation", response)
        self.assertEqual(response, "You told me your favorite color is blue.")

    @patch("skills.memory.memory_tools.semantic_search", return_value=[])
    def test_save_fact_persists_and_recalls_from_sqlite(self, _mock_semantic):
        original_db_path = config.DB_PATH
        with tempfile.TemporaryDirectory() as tmpdir:
            config.DB_PATH = os.path.join(tmpdir, "angelique.db")
            save_fact_to_db("User", "favorite color", "blue", importance=4, context="test")
            response = recall_facts(query="what is my favorite color")
            self.assertIn("blue", response)
        config.DB_PATH = original_db_path

    def test_parse_training_text_detects_plain_directive_style_input(self):
        facts = _parse_training_text(
            "You must always present trade recommendations in a structured format: use clear entry, stop loss, take profit, and risk statements."
        )

        self.assertTrue(facts)
        self.assertEqual(facts[0]["key"], "trade recommendation format")
        self.assertIn("entry", facts[0]["value"])


if __name__ == "__main__":
    unittest.main()
