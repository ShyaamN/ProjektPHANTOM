"""Cached path follower and stuck detection. Replans are requested, not run here."""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from navigation.grid import NavGrid

Point = Tuple[float, float]


class Pilot:
    def __init__(self) -> None:
        self.path: List[Point] = []
        self.goal: Optional[Point] = None
        self.goal_state = ""
        self.goal_t = -1e9
        self.dirty = True
        self.last_plan_t = -1e9
        self.anchor: Optional[Tuple[float, float, float]] = None
        self.stuck = False
        self.unstick_until = -1e9
        self.unstick_sign = 1
        self.jump_until = -1e9

    def set_goal(self, goal: Point, state: str, t: float, quantize: bool) -> Point:
        if quantize:
            stored = (round(goal[0] / 16.0) * 16.0, round(goal[1] / 16.0) * 16.0)
        else:
            stored = (float(goal[0]), float(goal[1]))
        changed_state = state != self.goal_state
        far = self.goal is None or math.hypot(stored[0] - self.goal[0], stored[1] - self.goal[1]) > (6.0 if not quantize else 18.0)
        stale = t - self.goal_t > 5.0
        if changed_state or far or stale or self.goal is None:
            self.goal = stored
            self.goal_state = state
            self.goal_t = t
            self.dirty = True
        return self.goal

    def note_motion(self, x: float, y: float, t: float, commanded: bool) -> None:
        if self.anchor is None:
            self.anchor = (x, y, t)
            return
        ax, ay, at = self.anchor
        if t - at < 1.0:
            return
        moved = math.hypot(x - ax, y - ay)
        self.stuck = commanded and moved < 2.0
        self.anchor = (x, y, t)
        if self.stuck:
            self.unstick_until = t + 1.2
            self.jump_until = t + 0.35
            self.unstick_sign = -self.unstick_sign
            self.dirty = True
            self.path = []

    def unsticking(self, t: float) -> bool:
        return t < self.unstick_until

    def should_jump(self, t: float) -> bool:
        return t < self.jump_until

    def should_replan(self, t: float) -> bool:
        if self.dirty or not self.path:
            return True
        return t - self.last_plan_t > 2.5

    def steer(self, grid: Optional[NavGrid], x: float, y: float, fallback: Point) -> List[float]:
        tx, ty = fallback
        if self.path:
            while len(self.path) > 1 and math.hypot(self.path[0][0] - x, self.path[0][1] - y) < 7.0:
                self.path.pop(0)
            tx, ty = self.path[0]
            for px, py in self.path[:5]:
                if math.hypot(px - x, py - y) < 30.0:
                    tx, ty = px, py
        dx, dy = tx - x, ty - y
        if grid is None:
            mag = math.hypot(dx, dy)
            if mag < 1e-6:
                return [0.0, 0.0]
            return [dx / mag, dy / mag]
        return grid.slide(x, y, dx, dy)
