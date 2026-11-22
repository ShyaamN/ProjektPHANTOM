"""Arena terrain and solid prisms. Movement rules match protocol.md sections 5 and 11."""
from __future__ import annotations

import array
import json
import math
import os
from typing import List, Optional, Sequence, Tuple


def _point_in_ring(xs: Sequence[float], ys: Sequence[float], x: float, y: float) -> bool:
    n = len(xs)
    inside = False
    j = n - 1
    for i in range(n):
        yi = ys[i]
        yj = ys[j]
        if (yi > y) != (yj > y):
            xi = xs[i]
            xj = xs[j]
            denom = yj - yi
            if denom != 0.0 and x < (xj - xi) * (y - yi) / denom + xi:
                inside = not inside
        j = i
    return inside


class Heightmap:
    def __init__(self, world: dict, arena_dir: str) -> None:
        terrain = world["terrain"]
        self.min_x = float(terrain["minX"])
        self.min_y = float(terrain["minY"])
        self.step = float(terrain["step"])
        self.nx = int(terrain["nx"])
        self.ny = int(terrain["ny"])
        raw = array.array("h")
        path = os.path.join(arena_dir, "v2", terrain["file"])
        with open(path, "rb") as f:
            raw.frombytes(f.read())
        if len(raw) < self.nx * self.ny:
            raise ValueError(f"terrain {path} is short: {len(raw)} < {self.nx * self.ny}")
        self.heights = raw

    def height(self, x: float, y: float) -> Optional[float]:
        fx = (x - self.min_x) / self.step
        fy = (y - self.min_y) / self.step
        if fx < 0.0 or fy < 0.0 or fx > self.nx - 1 or fy > self.ny - 1:
            return None
        i = int(fx)
        j = int(fy)
        if i >= self.nx - 1:
            i = self.nx - 2
        if j >= self.ny - 1:
            j = self.ny - 2
        tx = fx - i
        ty = fy - j
        nx = self.nx
        h = self.heights
        h00 = h[j * nx + i]
        h10 = h[j * nx + i + 1]
        h01 = h[(j + 1) * nx + i]
        h11 = h[(j + 1) * nx + i + 1]
        return ((h00 * (1.0 - tx) + h10 * tx) * (1.0 - ty) + (h01 * (1.0 - tx) + h11 * tx) * ty) * 0.01


class _Prism:
    __slots__ = ("base", "top", "xs", "ys", "minx", "maxx", "miny", "maxy", "holes")

    def __init__(self, raw: dict) -> None:
        ring = raw["ring"]
        xs = ring[0::2]
        ys = ring[1::2]
        self.base = float(raw["base"])
        self.top = float(raw["top"])
        self.xs = xs
        self.ys = ys
        self.minx = min(xs)
        self.maxx = max(xs)
        self.miny = min(ys)
        self.maxy = max(ys)
        holes = []
        for hole in raw.get("holes") or []:
            holes.append((hole[0::2], hole[1::2]))
        self.holes = holes

    def contains_xy(self, x: float, y: float) -> bool:
        if x < self.minx or x > self.maxx or y < self.miny or y > self.maxy:
            return False
        if not _point_in_ring(self.xs, self.ys, x, y):
            return False
        for xs, ys in self.holes:
            if _point_in_ring(xs, ys, x, y):
                return False
        return True


class Solids:
    """Building, stadium, and bridge prisms. Trees do not stop shots."""

    def __init__(self, world: dict, bucket: float = 48.0) -> None:
        self.prisms: List[_Prism] = [_Prism(p) for p in world.get("prisms") or []]
        self.bucket = bucket
        self.buckets = {}
        for idx, prism in enumerate(self.prisms):
            i0 = math.floor(prism.minx / bucket)
            i1 = math.floor(prism.maxx / bucket)
            j0 = math.floor(prism.miny / bucket)
            j1 = math.floor(prism.maxy / bucket)
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    self.buckets.setdefault((i, j), []).append(idx)

    def blocks_point(self, x: float, y: float, z: float) -> bool:
        key = (math.floor(x / self.bucket), math.floor(y / self.bucket))
        for idx in self.buckets.get(key, ()):
            prism = self.prisms[idx]
            if z < prism.base or z > prism.top:
                continue
            if prism.contains_xy(x, y):
                return True
        return False

    def blocks_segment(self, a: Sequence[float], b: Sequence[float], step: float = 5.0) -> bool:
        """True when a solid sits on the segment, ignoring the last ~10 m (the target)."""
        ax, ay, az = float(a[0]), float(a[1]), float(a[2])
        bx, by, bz = float(b[0]), float(b[1]), float(b[2])
        dist = math.hypot(bx - ax, by - ay)
        if dist < 8.0:
            return False
        steps = max(1, int(dist / step))
        last = max(1, steps - 2)
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        for k in range(1, last):
            t = k / steps
            if self.blocks_point(ax + dx * t, ay + dy * t, az + dz * t):
                return True
        return False

    def occupies_body(self, x: float, y: float, ground: float, height: float, step_up: float) -> bool:
        """True if a prism stops a mech standing on `ground` at this x, y.

        Bridges clear the body when their underside is at least `height` above the ground.
        A deck at or below step_up is walked over.
        """
        key = (math.floor(x / self.bucket), math.floor(y / self.bucket))
        top = ground + height
        for idx in self.buckets.get(key, ()):
            prism = self.prisms[idx]
            if not prism.contains_xy(x, y):
                continue
            if prism.base >= top - 0.25:
                continue
            if prism.top <= ground + step_up:
                continue
            if prism.base < top and prism.top > ground + 0.35:
                return True
        return False


def load_world(arena_dir: str) -> Tuple[dict, Heightmap, Solids]:
    path = os.path.join(arena_dir, "v2", "world.json")
    with open(path) as f:
        world = json.load(f)
    return world, Heightmap(world, arena_dir), Solids(world)
