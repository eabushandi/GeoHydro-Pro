"""Undo/redo engine."""

import numpy as np
import pandas as pd
import pytest
import shapely

from geohydro.engine.gridding.grid import Grid, GridGeometry
from geohydro.engine.mapping.model import ContourLayer, MapDocument
from geohydro.engine.vector import VectorDataset
from geohydro.project import Project
from geohydro.project.undo import UndoStack, describe


def _grid(name="G"):
    return Grid(GridGeometry(0, 10, 0, 10, 11, 11), np.arange(121.0).reshape(11, 11), name=name)


def test_undo_redo_add_rename_remove():
    p = Project()
    u = UndoStack(p)
    assert not u.can_undo and not u.can_redo
    g = p.add_grid(_grid())
    assert u.checkpoint() and u.undo_label == "Create grid"
    p.rename_grid(g.id, "Head")
    u.checkpoint()
    p.remove_grid(g.id)
    u.checkpoint()
    assert u.labels() == ["Create grid", "Rename grid", "Remove grid"]
    assert u.undo() == "Remove grid" and p.grids[g.id].name == "Head"
    assert u.undo() == "Rename grid" and p.grids[g.id].name == "G"
    assert u.undo() == "Create grid" and p.grids == {}
    assert u.undo() is None
    assert u.redo() == "Create grid" and p.grids[g.id].name == "G"
    assert u.redo() == "Rename grid" and p.grids[g.id].name == "Head"
    assert p.dirty


def test_restored_objects_are_independent_of_snapshots():
    p = Project()
    u = UndoStack(p)
    g = p.add_grid(_grid())
    u.checkpoint()
    p.rename_grid(g.id, "B")
    u.checkpoint()
    u.undo()
    p.grids[g.id].name = "mutated outside the stack"
    u.redo()
    u.undo()
    assert p.grids[g.id].name == "G"


def test_arrays_are_shared_not_copied():
    p = Project()
    u = UndoStack(p)
    g = p.add_grid(_grid())
    u.checkpoint()
    p.rename_grid(g.id, "B")
    u.checkpoint()
    u.undo()
    assert p.grids[g.id].z is g.z          # no memory duplication of grid values


def test_map_edits_are_deep_copied():
    p = Project()
    u = UndoStack(p)
    g = p.add_grid(_grid())
    m = p.add_map(MapDocument(name="M", layers=[ContourLayer(grid_id=g.id)]))
    u.checkpoint()
    m.title = "Edited"
    m.layers[0].line_width = 3.0
    assert u.checkpoint("Edit map") and u.undo_label == "Edit map"
    u.undo()
    assert p.maps[m.id].title != "Edited" and p.maps[m.id].layers[0].line_width != 3.0
    u.redo()
    assert p.maps[m.id].title == "Edited" and p.maps[m.id].layers[0].line_width == 3.0


def test_new_action_discards_redo_and_noop_checkpoints_skip():
    p = Project()
    u = UndoStack(p)
    p.add_grid(_grid("A"))
    u.checkpoint()
    p.add_grid(_grid("B"))
    u.checkpoint()
    u.undo()
    p.add_grid(_grid("C"))
    u.checkpoint()
    assert not u.can_redo and sorted(g.name for g in p.grids.values()) == ["A", "C"]
    p.log("grid.export", path="x.grd")       # history grows, content does not
    assert not u.checkpoint()
    assert u.labels() == ["Create grid", "Create grid"]


def test_history_is_append_only():
    p = Project()
    u = UndoStack(p)
    p.add_grid(_grid())
    u.checkpoint()
    n = len(p.history)
    u.undo()
    u.redo()
    assert [h.action for h in p.history[n:]] == ["edit.undo", "edit.redo"]
    assert p.history[n].details == {"undone": "Create grid"}


def test_limit():
    p = Project()
    u = UndoStack(p, limit=3)
    for i in range(6):
        p.add_grid(_grid(f"G{i}"))
        u.checkpoint()
    n = 0
    while u.undo():
        n += 1
    assert n == 3 and len(p.grids) == 3


def test_project_properties_and_vector_layers():
    p = Project()
    u = UndoStack(p)
    p.set_metadata(name="Wadi study", default_crs="EPSG:32639")
    u.checkpoint()
    v = p.add_vector(VectorDataset("rivers", np.array([shapely.Point(0, 0)], dtype=object),
                                   pd.DataFrame({"a": [1]})))
    u.checkpoint()
    u.undo()
    assert p.vectors == {} and p.name == "Wadi study"
    u.undo()
    assert p.name == "Untitled Project" and p.default_crs is None
    u.redo()
    u.redo()
    assert p.vectors[v.id].name == "rivers"


@pytest.mark.parametrize("action,label", [("grid.create", "Create grid"),
                                          ("dataset.assign_crs", "Assign CRS to dataset"),
                                          ("vector.import", "Import vector layer"),
                                          ("project.metadata", "Edit project properties")])
def test_describe(action, label):
    assert describe(action) == label
