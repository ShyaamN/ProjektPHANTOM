"""Arena line of sight. Buildings, bridges, and terrain stop shots. Trees do not.

The server ignores cars, barriers, and water. A bridge is a prism with a base
above the ground, so a ray under that base is open air.
"""
from __future__ import annotations

import array
import json
import math
import os
import sys

_CACHE = {}


def _ring_points(flat):
    return list(zip(flat[0::2], flat[1::2]))


def _point_in_ring(x: float, y: float, ring) -> bool:
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            dy = yj - yi
            if abs(dy) > 1e-12:
                xcross = (xj - xi) * (y - yi) / dy + xi
                if x < xcross:
                    inside = not inside
        j = i
    return inside


def _prep_prism(raw) -> dict:
    ring = _ring_points(raw["ring"])
    holes = [_ring_points(h) for h in (raw.get("holes") or []) if len(h) >= 6]
    xs = [p[0] for p in ring] or [0.0]
    ys = [p[1] for p in ring] or [0.0]
    return {
        "base": float(raw["base"]),
        "top": float(raw["top"]),
        "ring": ring,
        "holes": holes,
        "minx": min(xs),
        "maxx": max(xs),
        "miny": min(ys),
        "maxy": max(ys),
    }


def _xy_inside(x: float, y: float, prism) -> bool:
    if x < prism["minx"] or x > prism["maxx"] or y < prism["miny"] or y > prism["maxy"]:
        return False
    if not _point_in_ring(x, y, prism["ring"]):
        return False
    for hole in prism["holes"]:
        if _point_in_ring(x, y, hole):
            return False
    return True


def _seg_cross_t(ax, ay, bx, by, cx, cy, dx, dy):
    """Parameter t on AB where it crosses CD, or None."""
    rpx, rpy = bx - ax, by - ay
    qpx, qpy = dx - cx, dy - cy
    den = rpx * qpy - rpy * qpx
    if abs(den) < 1e-12:
        return None
    t = ((cx - ax) * qpy - (cy - ay) * qpx) / den
    u = ((cx - ax) * rpy - (cy - ay) * rpx) / den
    if 0.0 < t < 1.0 and 0.0 <= u <= 1.0:
        return t
    return None


def _aabb_possible(prism, a, b) -> bool:
    sx0, sx1 = (a[0], b[0]) if a[0] <= b[0] else (b[0], a[0])
    sy0, sy1 = (a[1], b[1]) if a[1] <= b[1] else (b[1], a[1])
    sz0, sz1 = (a[2], b[2]) if a[2] <= b[2] else (b[2], a[2])
    if sx1 < prism["minx"] or sx0 > prism["maxx"]:
        return False
    if sy1 < prism["miny"] or sy0 > prism["maxy"]:
        return False
    if sz1 < prism["base"] or sz0 > prism["top"]:
        return False
    return True


def prism_blocks(prism, a, b) -> bool:
    """True when segment a→b intersects the solid vertical prism."""
    if not _aabb_possible(prism, a, b):
        return False
    base = prism["base"]
    top = prism["top"]
    if _xy_inside(a[0], a[1], prism) and base <= a[2] <= top:
        return True
    rings = (prism["ring"],) + tuple(prism["holes"])
    ax, ay, az = a
    bx, by, bz = b
    dz = bz - az
    for ring in rings:
        n = len(ring)
        for i in range(n):
            cx, cy = ring[i]
            dx, dy = ring[(i + 1) % n]
            t = _seg_cross_t(ax, ay, bx, by, cx, cy, dx, dy)
            if t is None:
                continue
            z = az + dz * t
            if base <= z <= top:
                return True
    if abs(dz) > 1e-9:
        for plane in (base, top):
            t = (plane - az) / dz
            if 0.0 < t < 1.0:
                x = ax + (bx - ax) * t
                y = ay + (by - ay) * t
                if _xy_inside(x, y, prism):
                    return True
    return False


class MapWorld:
    """Optional map. ``ok`` is false when the arena files are missing."""

    def __init__(self):
        self.ok = False
        self.prisms = []
        self.grid = {}
        self.cell = 48.0
        self.h = None
        self.nx = 0
        self.ny = 0
        self.minx = 0.0
        self.miny = 0.0
        self.step = 1.0
        self.scale = 0.01

    @classmethod
    def from_prisms(cls, prisms) -> "MapWorld":
        world = cls()
        world.prisms = [_prep_prism(p) for p in prisms]
        world._index()
        world.ok = True
        return world

    @classmethod
    def load(cls, map_dir: str | None) -> "MapWorld":
        if not map_dir:
            return cls()
        key = os.path.abspath(map_dir)
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        world = cls()
        try:
            world._load(key)
        except FileNotFoundError:
            # No arena mounted (a local test, or hello before the files exist).
            # Shots then assume open air, which is the only honest fallback.
            world = cls()
        except Exception as exc:
            sys.stderr.write(f"map load failed ({key}): {exc}\n")
            world = cls()
        _CACHE[key] = world
        return world

    def _load(self, map_dir: str) -> None:
        world_path = os.path.join(map_dir, "v2", "world.json")
        with open(world_path) as f:
            raw = json.load(f)
        terrain = raw["terrain"]
        self.prisms = [_prep_prism(p) for p in raw["prisms"]]
        self._index()
        self.minx = float(terrain["minX"])
        self.miny = float(terrain["minY"])
        self.step = float(terrain["step"])
        self.nx = int(terrain["nx"])
        self.ny = int(terrain["ny"])
        self.scale = float(terrain.get("scale", 0.01))
        path = os.path.join(map_dir, terrain.get("file", "v2/terrain.i16"))
        if not os.path.isabs(terrain.get("file", "")):
            # world.json says "terrain.i16"; the file lives next to world.json.
            name = os.path.basename(terrain.get("file", "terrain.i16"))
            path = os.path.join(map_dir, "v2", name)
        heights = array.array("h")
        expect = self.nx * self.ny
        with open(path, "rb") as f:
            heights.fromfile(f, expect)
        if heights.itemsize != 2:
            raise RuntimeError("int16 array is not 2 bytes on this platform")
        self.h = heights
        self.ok = True

    def _index(self) -> None:
        cell = self.cell
        grid = {}
        for i, prism in enumerate(self.prisms):
            ix0 = math.floor(prism["minx"] / cell)
            ix1 = math.floor(prism["maxx"] / cell)
            iy0 = math.floor(prism["miny"] / cell)
            iy1 = math.floor(prism["maxy"] / cell)
            for ix in range(ix0, ix1 + 1):
                for iy in range(iy0, iy1 + 1):
                    grid.setdefault((ix, iy), []).append(i)
        self.grid = grid

    def ground(self, x: float, y: float):
        if self.h is None:
            return None
        fx = (x - self.minx) / self.step
        fy = (y - self.miny) / self.step
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
        h = self.h
        h00 = h[j * nx + i]
        h10 = h[j * nx + i + 1]
        h01 = h[(j + 1) * nx + i]
        h11 = h[(j + 1) * nx + i + 1]
        return (
            h00 * (1.0 - tx) * (1.0 - ty)
            + h10 * tx * (1.0 - ty)
            + h01 * (1.0 - tx) * ty
            + h11 * tx * ty
        ) * self.scale

    def _cells(self, a, b):
        cell = self.cell
        x0, y0 = a[0], a[1]
        x1, y1 = b[0], b[1]
        ix = math.floor(x0 / cell)
        iy = math.floor(y0 / cell)
        ix1 = math.floor(x1 / cell)
        iy1 = math.floor(y1 / cell)
        dx = x1 - x0
        dy = y1 - y0
        sx = 1 if dx > 0 else -1 if dx < 0 else 0
        sy = 1 if dy > 0 else -1 if dy < 0 else 0
        if dx > 0:
            t_max_x = ((ix + 1) * cell - x0) / dx
            t_dx = cell / dx
        elif dx < 0:
            t_max_x = (ix * cell - x0) / dx
            t_dx = cell / -dx
        else:
            t_max_x = math.inf
            t_dx = math.inf
        if dy > 0:
            t_max_y = ((iy + 1) * cell - y0) / dy
            t_dy = cell / dy
        elif dy < 0:
            t_max_y = (iy * cell - y0) / dy
            t_dy = cell / -dy
        else:
            t_max_y = math.inf
            t_dy = math.inf
        out = []
        for _ in range(96):
            out.append((ix, iy))
            if ix == ix1 and iy == iy1:
                break
            if t_max_x < t_max_y:
                ix += sx
                t_max_x += t_dx
            else:
                iy += sy
                t_max_y += t_dy
        return out

    def terrain_blocks(self, a, b) -> bool:
        if self.h is None:
            return False
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        dz = b[2] - a[2]
        dist = math.hypot(dx, dy)
        steps = int(dist / 6.0)
        if steps < 1:
            return False
        for i in range(1, steps):
            u = i / steps
            g = self.ground(a[0] + dx * u, a[1] + dy * u)
            if g is not None and a[2] + dz * u < g - 0.25:
                return True
        return False

    def blocked(self, a, b) -> bool:
        """True when a shot from a to b hits a solid or the ground."""
        if not self.ok:
            return False
        seen = set()
        for key in self._cells(a, b):
            for idx in self.grid.get(key, ()):
                if idx in seen:
                    continue
                seen.add(idx)
                if prism_blocks(self.prisms[idx], a, b):
                    return True
        if self.terrain_blocks(a, b):
            return True
        return False
