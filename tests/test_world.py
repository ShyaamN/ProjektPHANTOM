"""Shots stop on buildings and bridges, and pass under a bridge."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from combat.world import MapWorld, prism_blocks


def box(base, top, x0, y0, x1, y1):
    return {
        "base": base,
        "top": top,
        "ring": [x0, y0, x1, y0, x1, y1, x0, y1],
        "holes": [],
    }


class PrismTest(unittest.TestCase):
    def test_wall_roof_and_bridge(self):
        building = box(0.0, 20.0, 0.0, 0.0, 10.0, 10.0)
        self.assertTrue(prism_blocks(
            MapWorld.from_prisms([building]).prisms[0],
            (-5.0, 5.0, 5.0), (15.0, 5.0, 5.0),
        ))
        self.assertFalse(prism_blocks(
            MapWorld.from_prisms([building]).prisms[0],
            (-5.0, 5.0, 25.0), (15.0, 5.0, 25.0),
        ))
        self.assertFalse(prism_blocks(
            MapWorld.from_prisms([building]).prisms[0],
            (-5.0, -5.0, 5.0), (15.0, -5.0, 5.0),
        ))
        bridge = box(10.0, 12.0, 0.0, 0.0, 10.0, 10.0)
        world = MapWorld.from_prisms([bridge])
        prism = world.prisms[0]
        self.assertFalse(prism_blocks(prism, (-5.0, 5.0, 5.0), (15.0, 5.0, 5.0)))
        self.assertTrue(prism_blocks(prism, (-5.0, 5.0, 11.0), (15.0, 5.0, 11.0)))
        # The grid has to agree with the direct test, or LOS will miss walls.
        self.assertTrue(world.blocked((-5.0, 5.0, 11.0), (15.0, 5.0, 11.0)))
        self.assertFalse(world.blocked((-5.0, 5.0, 5.0), (15.0, 5.0, 5.0)))


if __name__ == "__main__":
    unittest.main()
