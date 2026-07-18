"""Asana chat ops — writes stay dry-run / blocked."""

from __future__ import annotations

from unittest.mock import patch

from app.integrations.asana_manager import (
    comment_on_asana_task,
    delete_asana_task,
    search_asana_tasks,
    update_asana_task,
)


def test_update_due_date_requires_approval():
    try:
        update_asana_task(task_gid="t1", due_on="2026-07-20", approved=False)
        assert False, "expected PermissionError"
    except PermissionError:
        pass


def test_update_due_date_simulated_when_approved():
    with patch("app.integrations.asana_manager._should_simulate_asana", return_value=True):
        out = update_asana_task(task_gid="t1", due_on="2026-07-20", approved=True)
    assert out["ok"] is True
    assert out.get("dry_run") or out.get("simulated")


def test_delete_simulated():
    with patch("app.integrations.asana_manager._should_simulate_asana", return_value=True):
        out = delete_asana_task(task_gid="t1", approved=True)
    assert out["ok"] is True
    assert out.get("dry_run") or out.get("simulated")


def test_comment_simulated():
    with patch("app.integrations.asana_manager._should_simulate_asana", return_value=True):
        out = comment_on_asana_task(task_gid="t1", comment="Please book Nobu", approved=True)
    assert out["ok"] is True
    assert "Nobu" in out["comment"]


@patch("app.integrations.asana_manager.list_asana_project_options")
@patch("app.integrations.asana_manager.list_asana_tasks")
def test_search_tasks(mock_list, mock_projects):
    mock_projects.return_value = {"projects": [{"gid": "p1", "name": "NON-IFG"}]}
    mock_list.return_value = {
        "tasks": [
            {"gid": "1", "name": "Book dinner reservation"},
            {"gid": "2", "name": "Review deck"},
        ]
    }
    out = search_asana_tasks(query="dinner")
    assert out["ok"] is True
    assert len(out["tasks"]) == 1
    assert "dinner" in out["tasks"][0]["name"].lower()
