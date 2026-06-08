"""Tests for the task/subtask manager: CRUD, auto progress, fuzzy name
resolution, persistence and the heuristic recommendation."""
import pytest

from task_manager import TaskManager


@pytest.fixture
def manager(tmp_path):
    return TaskManager(store_path=str(tmp_path / "tasks.json"))


class TestTaskCrud:
    def test_create_and_list(self, manager):
        task = manager.create_task("Tareas para la fiesta", "Cumple de Adrián")
        assert task["title"] == "Tareas para la fiesta"
        assert task["progress"] == 0
        assert manager.list_tasks()[0]["id"] == task["id"]

    def test_create_empty_title_rejected(self, manager):
        assert manager.create_task("   ") is None

    def test_update_and_delete_task(self, manager):
        task = manager.create_task("Fiesta")
        updated = manager.update_task(task["id"], title="Gran Fiesta")
        assert updated["title"] == "Gran Fiesta"
        assert manager.delete_task(task["id"]) is True
        assert manager.get_task(task["id"]) is None


class TestProgress:
    def test_progress_is_auto_computed(self, manager):
        task = manager.create_task("Fiesta")
        tid = task["id"]
        for name in ["Contratar payaso", "Comprar comida", "Comprar sillas", "Invitar a gente", "Comprar velas"]:
            manager.add_subtask(tid, name)

        task = manager.get_task(tid)
        assert task["subtask_count"] == 5
        assert task["progress"] == 0

        subs = task["subtasks"]
        manager.update_subtask(tid, subs[0]["id"], completed=True)
        manager.update_subtask(tid, subs[1]["id"], completed=True)

        task = manager.get_task(tid)
        assert task["completed_count"] == 2
        assert task["pending_count"] == 3
        assert task["progress"] == 40  # 2 / 5

    def test_unmark_subtask_updates_progress(self, manager):
        task = manager.create_task("Fiesta")
        tid = task["id"]
        manager.add_subtask(tid, "A")
        manager.add_subtask(tid, "B")
        sub_a = manager.get_task(tid)["subtasks"][0]["id"]
        manager.update_subtask(tid, sub_a, completed=True)
        assert manager.get_task(tid)["progress"] == 50
        manager.update_subtask(tid, sub_a, completed=False)
        assert manager.get_task(tid)["progress"] == 0

    def test_empty_task_progress_is_zero(self, manager):
        task = manager.create_task("Vacía")
        assert manager.get_task(task["id"])["progress"] == 0


class TestSubtaskCrud:
    def test_add_with_metadata_and_delete(self, manager):
        task = manager.create_task("Fiesta")
        tid = task["id"]
        manager.add_subtask(tid, "Contratar payaso", estimated_duration="2h", priority="high")
        sub = manager.get_task(tid)["subtasks"][0]
        assert sub["priority"] == "high"
        assert sub["estimated_duration"] == "2h"
        assert sub["completed"] is False

        result = manager.delete_subtask(tid, sub["id"])
        assert result["subtask_count"] == 0

    def test_invalid_priority_is_dropped(self, manager):
        task = manager.create_task("Fiesta")
        manager.add_subtask(task["id"], "X", priority="urgentísimo")
        assert manager.get_task(task["id"])["subtasks"][0]["priority"] is None


class TestFuzzyResolution:
    def test_find_task_by_partial_name(self, manager):
        manager.create_task("Tareas para la fiesta")
        found = manager.find_task_by_name("la fiesta")
        assert found is not None
        assert "fiesta" in found["title"].lower()

    def test_find_task_accent_insensitive(self, manager):
        manager.create_task("Organización del evento")
        assert manager.find_task_by_name("organizacion") is not None

    def test_find_subtask_by_name(self, manager):
        task = manager.create_task("Fiesta")
        manager.add_subtask(task["id"], "Comprar comida")
        full = manager._find(task["id"])
        sub = manager._find_subtask_by_name(full, "comida")
        assert sub is not None
        assert sub["title"] == "Comprar comida"


class TestPersistence:
    def test_reload_from_disk(self, tmp_path):
        path = str(tmp_path / "tasks.json")
        m1 = TaskManager(store_path=path)
        task = m1.create_task("Fiesta")
        m1.add_subtask(task["id"], "Comprar comida")

        m2 = TaskManager(store_path=path)
        tasks = m2.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["subtask_count"] == 1


class TestRecommendation:
    def test_heuristic_orders_by_priority_then_duration(self, manager):
        import os
        # Force the deterministic path regardless of any ambient API key.
        key = os.environ.pop("GEMINI_API_KEY", None)
        try:
            task = manager.create_task("Fiesta")
            tid = task["id"]
            manager.add_subtask(tid, "Comprar velas", priority="low", estimated_duration="10 min")
            manager.add_subtask(tid, "Invitar a gente", priority="high", estimated_duration="1h")
            manager.add_subtask(tid, "Comprar sillas", priority="medium", estimated_duration="30 min")

            rec = manager.recommend_order(tid)
            assert rec["success"] is True
            assert rec["method"] == "heuristic"
            titles = [o["title"] for o in rec["order"]]
            assert titles[0] == "Invitar a gente"   # high priority first
            assert titles[-1] == "Comprar velas"     # low priority last
        finally:
            if key is not None:
                os.environ["GEMINI_API_KEY"] = key

    def test_recommend_no_pending(self, manager):
        task = manager.create_task("Fiesta")
        manager.add_subtask(task["id"], "A")
        sub = manager.get_task(task["id"])["subtasks"][0]["id"]
        manager.update_subtask(task["id"], sub, completed=True)
        rec = manager.recommend_order(task["id"])
        assert rec["success"] is True
        assert rec["order"] == []
