"""Tests for Task Memory Tree."""

from screenpilot.planner.memory import TaskMemoryTree, TaskNodeStatus


def test_memory_tree_creation():
    tree = TaskMemoryTree("Open Chrome and search for cats")
    assert tree.root.description == "Open Chrome and search for cats"
    assert tree.root.status == TaskNodeStatus.IN_PROGRESS


def test_add_subtasks():
    tree = TaskMemoryTree("Complete task")
    t1 = tree.add_subtask("Step 1: Open app")
    tree.add_subtask("Step 2: Click button")
    tree.add_subtask("Step 3: Type text")

    assert len(tree.root.children) == 3
    assert tree._nodes[t1].description == "Step 1: Open app"


def test_task_lifecycle():
    tree = TaskMemoryTree("Main goal")
    t1 = tree.add_subtask("Subtask 1")

    tree.start_task(t1)
    assert tree._nodes[t1].status == TaskNodeStatus.IN_PROGRESS
    assert tree._active_id == t1

    tree.complete_task(t1, "Done successfully")
    assert tree._nodes[t1].status == TaskNodeStatus.COMPLETED
    assert tree._nodes[t1].result == "Done successfully"
    assert tree._active_id == "root"  # Back to parent


def test_task_failure():
    tree = TaskMemoryTree("Main goal")
    t1 = tree.add_subtask("Subtask 1")
    tree.start_task(t1)
    tree.fail_task(t1, "Element not found")

    assert tree._nodes[t1].status == TaskNodeStatus.FAILED
    assert tree._nodes[t1].result == "Element not found"


def test_add_action_and_observation():
    tree = TaskMemoryTree("Test goal")
    t1 = tree.add_subtask("Click button")
    tree.start_task(t1)

    tree.add_action({"action_type": "click", "x": 100, "y": 200})
    tree.add_observation("Button was clicked, dialog appeared")

    node = tree._nodes[t1]
    assert len(node.actions_taken) == 1
    assert len(node.observations) == 1
    assert node.actions_taken[0]["action_type"] == "click"


def test_get_context():
    tree = TaskMemoryTree("Open Chrome and search")
    t1 = tree.add_subtask("Open Chrome")
    t2 = tree.add_subtask("Navigate to Google")
    tree.add_subtask("Type search query")

    tree.start_task(t1)
    tree.add_action({"action_type": "click", "reasoning": "Click Chrome icon"})
    tree.complete_task(t1, "Chrome opened")

    tree.start_task(t2)

    context = tree.get_context()
    assert "Task Memory" in context
    assert "Open Chrome" in context
    assert "Navigate to Google" in context


def test_get_progress():
    tree = TaskMemoryTree("Main")
    t1 = tree.add_subtask("A")
    t2 = tree.add_subtask("B")
    tree.add_subtask("C")

    tree.start_task(t1)
    tree.complete_task(t1)
    tree.start_task(t2)

    progress = tree.get_progress()
    assert progress["completed"] == 1
    assert progress["in_progress"] == 1
    assert progress["pending"] == 1


def test_to_dict():
    tree = TaskMemoryTree("Test goal")
    tree.add_subtask("Step 1")
    tree.add_subtask("Step 2")

    d = tree.to_dict()
    assert "root_id" in d
    assert "nodes" in d
    assert len(d["nodes"]) == 3  # root + 2 subtasks


def test_nested_subtasks():
    tree = TaskMemoryTree("Complex task")
    t1 = tree.add_subtask("Phase 1")
    tree.start_task(t1)
    t1a = tree.add_subtask("Phase 1a", parent_id=t1)
    tree.add_subtask("Phase 1b", parent_id=t1)

    assert len(tree._nodes[t1].children) == 2
    assert tree._nodes[t1a].parent_id == t1
