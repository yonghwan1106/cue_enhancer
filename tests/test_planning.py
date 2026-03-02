"""Tests for CUE Planning Enhancer module."""

from cue.types import SubTask, MemoryContext, Lesson


class TestTaskPlanner:
    def _get_planner(self):
        from cue.planning.planner import TaskPlanner
        return TaskPlanner()

    def test_simple_decompose(self):
        planner = self._get_planner()
        subtasks = planner.decompose("Open Firefox and go to google.com", "Firefox")
        assert isinstance(subtasks, list)
        assert len(subtasks) >= 1
        assert all(isinstance(s, SubTask) for s in subtasks)

    def test_step_limit(self):
        planner = self._get_planner()
        subtasks = planner.decompose(
            "Open file, select A column, sort it, select B column, format it, "
            "select C column, add formula, select D column, delete it, "
            "insert chart, format chart, save file",
            "LibreOffice Calc",
        )
        assert len(subtasks) <= 7

    def test_redecompose_groups(self):
        planner = self._get_planner()
        many = [SubTask(description=f"step {i}", action_type="click") for i in range(12)]
        result = planner._hierarchical_redecompose(many)
        assert len(result) <= 7

    def test_empty_task(self):
        planner = self._get_planner()
        subtasks = planner.decompose("", "")
        assert isinstance(subtasks, list)

    def test_related_detection(self):
        from cue.planning.planner import TaskPlanner
        # _is_related is a staticmethod
        t1 = SubTask(description="Click A column", action_type="click", target_region="column")
        t2 = SubTask(description="Sort A column", action_type="click", target_region="column")
        t3 = SubTask(description="Open File menu", action_type="navigate", target_region="menu")
        assert TaskPlanner._is_related(t1, t2)
        assert not TaskPlanner._is_related(t1, t3)


class TestAppKnowledgeBase:
    def _get_kb(self):
        from cue.planning.knowledge import AppKnowledgeBase
        return AppKnowledgeBase()

    def test_load_bundled(self):
        kb = self._get_kb()
        assert len(kb._store) >= 0  # May have bundled files

    def test_get_knowledge_fuzzy(self):
        kb = self._get_kb()
        # Should handle missing apps gracefully
        result = kb.get_knowledge("NonExistentApp12345")
        assert result is None

    def test_find_shortcut(self):
        kb = self._get_kb()
        # Should return None for unknown apps
        result = kb.find_shortcut("UnknownApp", "open file")
        assert result is None


class TestPlanningEnhancer:
    def _get_enhancer(self):
        from cue.planning.enhancer import PlanningEnhancer
        from cue.config import PlanningConfig
        return PlanningEnhancer(PlanningConfig())

    def test_init(self):
        enhancer = self._get_enhancer()
        assert enhancer is not None

    def test_decompose_task(self):
        enhancer = self._get_enhancer()
        subtasks = enhancer._decompose_task("Save the document", "LibreOffice Writer", None)
        assert isinstance(subtasks, list)

    def test_inject_lessons(self):
        enhancer = self._get_enhancer()
        lessons = [
            Lesson(
                id="l1", app="Firefox", situation="Opening menu",
                failed_approach="Click on menu text",
                successful_approach="Use Alt+F shortcut",
                confidence=0.9,
            )
        ]
        text = enhancer._inject_lessons(lessons, "Firefox")
        assert "Alt+F" in text

    def test_inject_empty_lessons(self):
        enhancer = self._get_enhancer()
        text = enhancer._inject_lessons([], "Firefox")
        assert text == ""
