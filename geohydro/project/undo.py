"""Undo / redo for project edits.

Design
------
Snapshot based. After every completed user action the caller takes a
*checkpoint*: a copy of the project's content (point datasets, grids, maps,
vector layers, images and project properties). Undo restores the previous
checkpoint, redo the next one.

Snapshots are cheap because data arrays are shared, not copied: datasets,
grids, vector layers and images are copied shallowly (their NumPy arrays and
DataFrames are referenced). This is safe because GeoHydro Pro never modifies
those arrays in place; every operation that changes values creates a new
array (this rule is covered by tests). Map documents, which are small and
edited in place, are deep-copied.

The processing history and the list of exported outputs are deliberately
*not* rolled back: the history is an append-only record of what happened, so
an undo adds an ``edit.undo`` entry instead of deleting the original entry,
and an exported file still exists after an undo.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field

from .model import Project

PROJECT_FIELDS = ("name", "description", "author", "default_crs", "units")
STORES = ("datasets", "grids", "maps", "vectors", "images")

_VERBS = {"import": "Import", "create": "Create", "remove": "Remove", "rename": "Rename",
          "assign_crs": "Assign CRS to", "z_units": "Change Z units of", "metadata": "Edit",
          "export": "Export", "export_csv": "Export"}
_NOUNS = {"dataset": "dataset", "grid": "grid", "map": "map", "vector": "vector layer",
          "image": "image", "project": "project properties", "gridmath": "grid"}


def describe(action: str) -> str:
    """Human label for a history action, e.g. ``grid.create`` → ``Create grid``."""
    noun, _, verb = action.partition(".")
    return f"{_VERBS.get(verb, verb.replace('_', ' ').capitalize())} {_NOUNS.get(noun, noun)}".strip()


@dataclass
class _State:
    label: str
    stores: dict
    meta: dict
    fingerprint: str = field(repr=False, default="")


def _copy_store(name: str, store: dict) -> dict:
    if name == "maps":
        return {k: copy.deepcopy(v) for k, v in store.items()}
    out = {}
    for k, v in store.items():
        c = copy.copy(v)
        if hasattr(c, "metadata") and isinstance(c.metadata, dict):
            c.metadata = copy.deepcopy(c.metadata)
        out[k] = c
    return out


def _fingerprint(project: Project) -> str:
    """Cheap description of the content, used to skip checkpoints that change nothing."""
    parts = {f: getattr(project, f) for f in PROJECT_FIELDS}
    parts["settings"] = project.settings
    for name in STORES:
        items = []
        for k, v in getattr(project, name).items():
            if name == "maps":
                items.append([k, v.to_dict()])
            else:
                arrays = [id(getattr(v, a, None)) for a in ("z", "data", "geometry",
                                                            "attributes", "rgba")]
                items.append([k, v.name, getattr(v, "crs", None), getattr(v, "z_units", None),
                              getattr(v, "notes", None), arrays,
                              json.dumps(getattr(v, "metadata", None), sort_keys=True,
                                         default=str)])
        parts[name] = items
    return json.dumps(parts, sort_keys=True, default=str)


class UndoStack:
    """Linear undo history of project checkpoints."""

    def __init__(self, project: Project, limit: int = 30):
        self.limit = max(int(limit), 1)
        self.reset(project)

    # ---- state -----------------------------------------------------------------
    def reset(self, project: Project) -> None:
        """Start a new history whose base state is the project as it is now."""
        self.project = project
        self._states: list[_State] = [self._capture(project, "Open project")]
        self._index = 0
        self._history_len = len(project.history)

    def _capture(self, project: Project, label: str) -> _State:
        return _State(label=label,
                      stores={n: _copy_store(n, getattr(project, n)) for n in STORES},
                      meta={**{f: getattr(project, f) for f in PROJECT_FIELDS},
                            "settings": copy.deepcopy(project.settings)},
                      fingerprint=_fingerprint(project))

    def _restore(self, state: _State) -> None:
        p = self.project
        for n in STORES:
            setattr(p, n, _copy_store(n, state.stores[n]))
        for f in PROJECT_FIELDS:
            setattr(p, f, state.meta[f])
        p.settings = copy.deepcopy(state.meta["settings"])
        p.dirty = True

    # ---- recording -----------------------------------------------------------
    def checkpoint(self, label: str | None = None) -> bool:
        """Record the current project content after a completed action.

        Returns False (and records nothing) when the content is unchanged since
        the last checkpoint, for example after an export.
        """
        fp = _fingerprint(self.project)
        if fp == self._states[self._index].fingerprint:
            self._history_len = len(self.project.history)
            return False
        if label is None:
            new = self.project.history[self._history_len:]
            label = describe(new[-1].action) if new else "Edit"
        del self._states[self._index + 1:]  # a new action discards the redo branch
        self._states.append(self._capture(self.project, label))
        if len(self._states) > self.limit + 1:  # +1: the base state
            del self._states[0]
        self._index = len(self._states) - 1
        self._history_len = len(self.project.history)
        return True

    # ---- undo / redo -----------------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    @property
    def undo_label(self) -> str | None:
        return self._states[self._index].label if self.can_undo else None

    @property
    def redo_label(self) -> str | None:
        return self._states[self._index + 1].label if self.can_redo else None

    def undo(self) -> str | None:
        if not self.can_undo:
            return None
        label = self._states[self._index].label
        self._index -= 1
        self._restore(self._states[self._index])
        self.project.log("edit.undo", undone=label)
        self._history_len = len(self.project.history)
        return label

    def redo(self) -> str | None:
        if not self.can_redo:
            return None
        self._index += 1
        label = self._states[self._index].label
        self._restore(self._states[self._index])
        self.project.log("edit.redo", redone=label)
        self._history_len = len(self.project.history)
        return label

    def labels(self) -> list[str]:
        """Labels of the recorded actions, oldest first (the base state excluded)."""
        return [s.label for s in self._states[1:]]
