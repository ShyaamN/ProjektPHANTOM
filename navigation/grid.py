"""Coarse walk grid and time-boxed A*. Built once during hello, then cached."""
from __future__ import annotations

import heapq
import math
import time
from array import array
from typing import List, Optional, Sequence, Tuple

from navigation.map import Solids, load_world

Cell = Tuple[int, int]
Point = Tuple[float, float]

_NEI = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, 1.41421356237),
    (1, -1, 1.41421356237),
    (-1, 1, 1.41421356237),
    (-1, -1, 1.41421356237),
)


class NavGrid:
    def __init__(
        self,
        min_x: float,
        min_y: float,
        w: int,
        h: int,
        cell: float,
        block: bytearray,
        ground: array,
        step_up: float = 1.2,
        max_slope: float = math.radians(50.0),
    ) -> None:
        self.min_x = min_x
        self.min_y = min_y
        self.w = w
        self.h = h
        self.cell = cell
        self.block = block
        self.ground = ground
        self.step_up = step_up
        self.max_slope = max_slope

    def cell_of(self, x: float, y: float) -> Cell:
        return math.floor((x - self.min_x) / self.cell), math.floor((y - self.min_y) / self.cell)

    def in_bounds(self, i: int, j: int) -> bool:
        return 0 <= i < self.w and 0 <= j < self.h

    def _free(self, i: int, j: int) -> bool:
        return self.in_bounds(i, j) and not self.block[j * self.w + i]

    def center(self, i: int, j: int) -> Point:
        return (self.min_x + (i + 0.5) * self.cell, self.min_y + (j + 0.5) * self.cell)

    def walkable(self, x: float, y: float) -> bool:
        return self._free(*self.cell_of(x, y))

    def nearest_free(self, x: float, y: float, rad: int = 6) -> Cell:
        i, j = self.cell_of(x, y)
        if self._free(i, j):
            return i, j
        for r in range(1, rad + 1):
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    ni, nj = i + di, j + dj
                    if self._free(ni, nj):
                        return ni, nj
        return i, j

    def _slope_ok(self, i: int, j: int, ni: int, nj: int) -> bool:
        dz = self.ground[nj * self.w + ni] - self.ground[j * self.w + i]
        if dz <= self.step_up:
            return True
        dist = self.cell * (1.41421356237 if (i != ni and j != nj) else 1.0)
        return math.atan2(dz, dist) <= self.max_slope

    def astar(self, start: Sequence[float], goal: Sequence[float], limit: int = 800) -> List[Point]:
        """Weighted A* capped at `limit` expansions. Partial paths head toward the goal."""
        si, sj = self.nearest_free(start[0], start[1])
        gi, gj = self.nearest_free(goal[0], goal[1])
        if not self.in_bounds(si, sj):
            return []
        if (si, sj) == (gi, gj):
            return [self.center(gi, gj)]
        w = self.w
        n = w * self.h
        inf = 1e30
        g = [inf] * n
        parent = [-1] * n
        start_i = sj * w + si
        goal_i = gj * w + gi
        g[start_i] = 0.0

        def heur(i: int, j: int) -> float:
            return math.hypot(i - gi, j - gj)

        heap: List[Tuple[float, int]] = [(heur(si, sj), start_i)]
        closed = bytearray(n)
        best = start_i
        best_h = heur(si, sj)
        expanded = 0
        block = self.block
        h = self.h
        while heap and expanded < limit:
            _, cur = heapq.heappop(heap)
            if closed[cur]:
                continue
            closed[cur] = 1
            expanded += 1
            ci = cur % w
            cj = cur // w
            hcur = heur(ci, cj)
            if hcur < best_h:
                best_h = hcur
                best = cur
            if cur == goal_i:
                best = cur
                break
            gc = g[cur]
            for di, dj, cost in _NEI:
                ni = ci + di
                nj = cj + dj
                if ni < 0 or nj < 0 or ni >= w or nj >= h:
                    continue
                nidx = nj * w + ni
                if block[nidx]:
                    continue
                if di and dj and (block[cj * w + ni] or block[nj * w + ci]):
                    continue
                if not self._slope_ok(ci, cj, ni, nj):
                    continue
                ng = gc + cost
                if ng >= g[nidx]:
                    continue
                g[nidx] = ng
                parent[nidx] = cur
                heapq.heappush(heap, (ng + heur(ni, nj) * 1.2, nidx))
                if len(heap) > limit * 6:
                    heap.clear()
                    break
        pts: List[Point] = []
        cur = best
        guard = 0
        seen = 0
        while cur != -1 and guard < n:
            pts.append(self.center(cur % w, cur // w))
            if cur == start_i:
                break
            cur = parent[cur]
            guard += 1
            seen += 1
        pts.reverse()
        return _simplify(pts)

    def slide(self, x: float, y: float, dx: float, dy: float) -> List[float]:
        """Steer, sliding along a blocked cell instead of walking into it."""
        mag = math.hypot(dx, dy)
        if mag < 1e-8:
            return [0.0, 0.0]
        ux, uy = dx / mag, dy / mag
        reach = self.cell * 0.9
        if self.walkable(x + ux * reach, y + uy * reach):
            return [ux, uy]
        lx, ly = -uy, ux
        left = self.walkable(x + lx * reach, y + ly * reach)
        right = self.walkable(x - lx * reach, y - ly * reach)
        if left and not right:
            return _norm(ux * 0.25 + lx, uy * 0.25 + ly)
        if right and not left:
            return _norm(ux * 0.25 - lx, uy * 0.25 - ly)
        if left and right:
            return _norm(lx, ly)
        if self.walkable(x + ux * reach * 0.4, y + uy * reach * 0.4):
            return [ux, uy]
        return [ux, uy]

    def segment_hits_block(self, ax: float, ay: float, bx: float, by: float) -> bool:
        dist = math.hypot(bx - ax, by - ay)
        if dist < self.cell * 0.5:
            return False
        steps = max(1, int(dist / (self.cell * 0.5)))
        for k in range(1, steps):
            t = k / steps
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            i, j = self.cell_of(x, y)
            if not self.in_bounds(i, j) or self.block[j * self.w + i]:
                return True
        return False


def _norm(x: float, y: float) -> List[float]:
    mag = math.hypot(x, y)
    if mag < 1e-8:
        return [0.0, 0.0]
    return [x / mag, y / mag]


def _simplify(pts: List[Point]) -> List[Point]:
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    px, py = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
    for i in range(1, len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        if abs(dx - px) > 0.01 or abs(dy - py) > 0.01:
            out.append(pts[i])
            px, py = dx, dy
    out.append(pts[-1])
    return out


def build_grid(arena_dir: str, cell: float = 8.0, mech_h: float = 9.0, step_up: float = 1.2) -> Tuple[NavGrid, Solids, dict]:
    t0 = time.perf_counter()
    world, heightmap, solids = load_world(arena_dir)
    bounds = world["bounds"]
    min_x = float(bounds["minX"])
    min_y = float(bounds["minY"])
    max_x = float(bounds["maxX"])
    max_y = float(bounds["maxY"])
    w = max(2, int(math.ceil((max_x - min_x) / cell)))
    h = max(2, int(math.ceil((max_y - min_y) / cell)))
    block = bytearray(w * h)
    ground = array("f", [0.0]) * (w * h)
    for j in range(h):
        y = min_y + (j + 0.5) * cell
        row = j * w
        for i in range(w):
            x = min_x + (i + 0.5) * cell
            z = heightmap.height(x, y)
            if z is None:
                block[row + i] = 1
                continue
            ground[row + i] = z
            if solids.occupies_body(x, y, z, mech_h, step_up):
                block[row + i] = 1
    # Map edge is a wall. Keep a one-cell margin so routes don't ride the boundary.
    for j in range(h):
        block[j * w] = 1
        block[j * w + w - 1] = 1
    for i in range(w):
        block[i] = 1
        block[(h - 1) * w + i] = 1
    grid = NavGrid(min_x, min_y, w, h, cell, block, ground, step_up=step_up, max_slope=math.radians(50.0))
    info = {
        "cells": w * h,
        "blocked": sum(block),
        "ms": (time.perf_counter() - t0) * 1000.0,
        "w": w,
        "h": h,
    }
    return grid, solids, info
