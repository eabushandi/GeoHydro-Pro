"""Natural Neighbour interpolation (Sibson, 1981).

For a node q inside the convex hull of the data, insert q into the Voronoi
diagram of the data. The weight of data point p_i is the area that q's new
Voronoi cell "steals" from p_i's original cell, divided by the area of q's
new cell:

    z(q) = sum( A_i / A ) z_i

Computation (Watson, 1992; Sambridge et al., 1995): the Delaunay triangles
whose circumcircles contain q form the Bowyer-Watson cavity. The natural
neighbours are the vertices of the cavity boundary. The region stolen from
p_i is the convex polygon whose vertices are

  * the circumcentres of the two new triangles (q, p_i-1, p_i) and
    (q, p_i, p_i+1) formed with the cavity boundary edges at p_i, and
  * the circumcentres of the old cavity triangles that have p_i as a vertex
    (these are the old Voronoi vertices of p_i that lie inside q's cell).

This is an exact geometric construction, not a raster approximation.
Properties verified by tests: interpolates the data exactly, reproduces
linear functions exactly inside the hull (linear precision), weights are
non-negative and sum to 1.

Nodes outside the convex hull are blank. A node on the hull boundary takes
the linear interpolation along that boundary edge, which is the limit of
Sibson's interpolant there.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import Delaunay, QhullError

from ..errors import GriddingError
from .base import Anisotropy, Interpolator


def _circumcentres(p0, p1, p2):
    """Vectorised circumcentres and squared radii of triangles (arrays (n, 2))."""
    ax, ay = p0[:, 0], p0[:, 1]
    bx, by = p1[:, 0], p1[:, 1]
    cx, cy = p2[:, 0], p2[:, 1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    with np.errstate(divide="ignore", invalid="ignore"):
        ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
        uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r2 = (ux - ax) ** 2 + (uy - ay) ** 2
    return np.column_stack([ux, uy]), r2


def _circumcentre(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if d == 0:
        return None
    a2 = a[0] * a[0] + a[1] * a[1]
    b2 = b[0] * b[0] + b[1] * b[1]
    c2 = c[0] * c[0] + c[1] * c[1]
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    return (ux, uy)


def _convex_area(pts):
    """Area of a convex polygon given its vertices in any order."""
    if len(pts) < 3:
        return 0.0
    p = np.asarray(pts)
    c = p.mean(axis=0)
    order = np.argsort(np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0]))
    p = p[order]
    x, y = p[:, 0], p[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


class NaturalNeighbour(Interpolator):
    key = "natural_neighbour"
    title = "Natural Neighbour"
    exact = True
    min_points_required = 3

    def __init__(self, anisotropy: Anisotropy | None = None):
        super().__init__()
        self.anisotropy = anisotropy or Anisotropy()

    def _fit(self):
        self._x0, self._y0 = float(self.x.mean()), float(self.y.mean())
        tx, ty = self.anisotropy.transform(self.x, self.y, self._x0, self._y0)
        # Scale to unit size for numerical robustness of circumcircle tests.
        self._scale = float(max(np.ptp(tx), np.ptp(ty))) or 1.0
        pts = np.column_stack([tx, ty]) / self._scale
        try:
            self._tri = Delaunay(pts)
        except QhullError as exc:
            raise GriddingError(
                "Natural Neighbour needs at least three non-collinear points."
            ) from exc
        s = self._tri.simplices
        self._pts = pts
        self._cc, self._r2 = _circumcentres(pts[s[:, 0]], pts[s[:, 1]], pts[s[:, 2]])
        self._simp = s.tolist()
        self._nbr = self._tri.neighbors.tolist()
        self._ccl = self._cc.tolist()
        self._r2l = self._r2.tolist()

    def weights(self, qx: float, qy: float):
        """Natural-neighbour (index -> weight) for one point, or None outside the hull."""
        tx, ty = self.anisotropy.transform(np.array([qx]), np.array([qy]), self._x0, self._y0)
        q = (float(tx[0]) / self._scale, float(ty[0]) / self._scale)
        return self._weights(q)

    def _weights(self, q, s=None):
        if s is None:
            s = int(self._tri.find_simplex(np.array([q]))[0])
        if s < 0:
            return None
        pts = self._pts
        verts = self._simp[s]
        for v in verts:
            if (pts[v, 0] - q[0]) ** 2 + (pts[v, 1] - q[1]) ** 2 < 1e-24:
                return {v: 1.0}
        # Bowyer-Watson cavity
        cav = set()
        stack = [s]
        cc, r2 = self._ccl, self._r2l
        while stack:
            t = stack.pop()
            if t in cav:
                continue
            c = cc[t]
            if t != s and not ((c[0] - q[0]) ** 2 + (c[1] - q[1]) ** 2 < r2[t] * (1 - 1e-12)):
                continue
            cav.add(t)
            for n in self._nbr[t]:
                if n >= 0 and n not in cav:
                    stack.append(n)
        # Boundary edges and new circumcentres
        poly: dict[int, list] = {}
        for t in cav:
            sv = self._simp[t]
            for k in range(3):
                n = self._nbr[t][k]
                a, b = sv[(k + 1) % 3], sv[(k + 2) % 3]
                if n >= 0 and n in cav:
                    continue
                c = _circumcentre(q, pts[a], pts[b])
                if c is None or not np.isfinite(c[0]):
                    return self._edge_linear(q, a, b)
                poly.setdefault(a, []).append(c)
                poly.setdefault(b, []).append(c)
            for v in sv:
                poly.setdefault(v, []).append(cc[t])
        areas = {}
        for v, ps in poly.items():
            a = _convex_area(ps)
            if a > 0:
                areas[v] = a
        total = sum(areas.values())
        if not total > 0:
            return None
        return {v: a / total for v, a in areas.items()}

    def _edge_linear(self, q, a, b):
        pa, pb = self._pts[a], self._pts[b]
        ab = pb - pa
        t = float(np.dot(np.asarray(q) - pa, ab) / np.dot(ab, ab))
        t = min(max(t, 0.0), 1.0)
        return {a: 1 - t, b: t}

    def _predict(self, xq, yq):
        tx, ty = self.anisotropy.transform(xq, yq, self._x0, self._y0)
        tx = tx / self._scale
        ty = ty / self._scale
        out = np.full(xq.size, np.nan)
        z = self.z
        ok = np.isfinite(tx) & np.isfinite(ty)
        simp = np.full(xq.size, -1)
        if ok.any():
            simp[ok] = self._tri.find_simplex(np.column_stack([tx[ok], ty[ok]]))
        simp = simp.tolist()
        step = max(1, xq.size // 100)
        for k in range(xq.size):
            if k % step == 0:
                self._report(k / xq.size)
            if simp[k] < 0:
                continue
            w = self._weights((float(tx[k]), float(ty[k])), simp[k])
            if w is not None:
                out[k] = sum(wt * z[v] for v, wt in w.items())
        self._report(1.0)
        return out
