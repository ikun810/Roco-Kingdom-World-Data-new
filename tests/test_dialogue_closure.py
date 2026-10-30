"""Exercise reference traversal and current-source precedence with small real tables."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import dialogue_closure as mod


class DialogueClosureTests(unittest.TestCase):
    def tables(self):
        current = {"DIALOGUE_CONF": {}, "SELECT_CONF": {
            "10": {"id": 10, "text": "current", "select_next_dialogue": 3,
                   "notimes_dialogue": 4}}}
        history = {"DIALOGUE_CONF": {
            "1": {"id": 1, "next_dialog_id": 2, "select_ids": [10]},
            "2": {"id": 2, "next_dialog_id": 1},
            "3": {"id": 3}, "4": {"id": 4}},
            "SELECT_CONF": {"10": {"id": 10, "text": "before", "select_next_dialogue": 99}}}
        return current, history

    def test_follows_both_branches_and_terminates_a_cycle(self):
        current, history = self.tables()
        result = mod.trace_graph(current, history, [("DIALOGUE_CONF", "1")])
        self.assertEqual([(r["table"], r["id"]) for r in result["additions"]],
                         [("DIALOGUE_CONF", str(i)) for i in [1, 2, 3, 4]])
        self.assertEqual(len(result["nodes"]), 5)
        self.assertEqual(len(result["edges"]), 5)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["text_reviews"][0]["fields"], ["text"])
        self.assertEqual(current["SELECT_CONF"]["10"]["text"], "current")

    def test_current_row_wins_over_history_and_is_not_backfilled(self):
        current, history = self.tables()
        current["DIALOGUE_CONF"]["1"] = {"id": 1, "next_dialog_id": 4}
        result = mod.trace_graph(current, history, [("DIALOGUE_CONF", "1")])
        self.assertEqual([r["id"] for r in result["additions"]], ["4"])
        self.assertEqual(len(result["nodes"]), 2)
        self.assertEqual(result["text_reviews"], [])

    def test_missing_reference_is_retained_with_all_incoming_edges(self):
        current, history = self.tables()
        history["DIALOGUE_CONF"]["2"]["next_dialog_id"] = 99
        current["SELECT_CONF"]["10"]["notimes_dialogue"] = 99
        result = mod.trace_graph(current, history, [("DIALOGUE_CONF", "1")])
        self.assertEqual(result["missing"], [{"table": "DIALOGUE_CONF", "id": "99"}])
        self.assertEqual(sum(e["to_id"] == "99" for e in result["edges"]), 2)
        self.assertNotIn("99", [r["id"] for r in result["additions"]])

    def test_omitted_and_zero_links_are_not_invented(self):
        current, history = self.tables()
        history["DIALOGUE_CONF"]["1"] = {"id": 1, "next_dialog_id": 0, "select_ids": []}
        result = mod.trace_graph(current, history, [("DIALOGUE_CONF", "1")])
        self.assertEqual(result["edges"], [])
        self.assertEqual(len(result["nodes"]), 1)

    def test_record_key_mismatch_is_rejected(self):
        current, history = self.tables()
        history["DIALOGUE_CONF"]["1"]["id"] = 999
        with self.assertRaisesRegex(ValueError, "record ID"):
            mod.trace_graph(current, history, [("DIALOGUE_CONF", "1")])

    def test_boolean_is_not_an_id_and_bad_array_is_rejected(self):
        for bad in [True, "2", {"id": 2}]:
            current, history = self.tables()
            history["DIALOGUE_CONF"]["1"]["next_dialog_id"] = bad
            with self.assertRaises(ValueError):
                mod.trace_graph(current, history, [("DIALOGUE_CONF", "1")])
        current, history = self.tables()
        history["DIALOGUE_CONF"]["1"]["select_ids"] = 10
        with self.assertRaises(ValueError):
            mod.trace_graph(current, history, [("DIALOGUE_CONF", "1")])


if __name__ == "__main__":
    unittest.main()
