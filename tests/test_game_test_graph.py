from __future__ import annotations

import unittest

from mainflow.langgraph_game_flow_skeleton import build_game_test_graph


class GameTestGraphTest(unittest.TestCase):
    def test_asset_nodes_are_not_registered(self) -> None:
        graph = build_game_test_graph().get_graph()
        node_names = set(graph.nodes)

        self.assertTrue(
            {
                "user_input",
                "parse_input",
                "analysis",
                "logic_analysis",
                "design_game_logic",
                "validate_game",
                "visual_validation",
            }.issubset(node_names)
        )
        self.assertTrue(
            {
                "generate_image",
                "generate_sound",
                "validate_image",
                "validate_sound",
                "apply_assets_to_game",
            }.isdisjoint(node_names)
        )

    def test_validation_order_is_explicit(self) -> None:
        graph = build_game_test_graph().get_graph()
        edges = {(edge.source, edge.target) for edge in graph.edges}

        self.assertIn(("design_game_logic", "validate_game"), edges)
        self.assertIn(("validate_game", "visual_validation"), edges)


if __name__ == "__main__":
    unittest.main()
