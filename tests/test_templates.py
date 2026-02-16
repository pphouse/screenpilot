"""Tests for workflow template system."""

import tempfile
from pathlib import Path

from screenpilot.templates.registry import TemplateParam, TemplateRegistry, WorkflowTemplate


def test_builtin_templates():
    registry = TemplateRegistry()
    templates = registry.list_all()
    assert len(templates) >= 5  # At least the built-in templates


def test_get_template():
    registry = TemplateRegistry()
    template = registry.get("web_form_fill")
    assert template is not None
    assert template.name == "Fill Web Form"
    assert template.category == "data_entry"


def test_render_goal():
    template = WorkflowTemplate(
        id="test",
        name="Test",
        description="Test template",
        category="test",
        goal_template="Open {app} and click {button}",
        params=[
            TemplateParam(name="app", description="Application"),
            TemplateParam(name="button", description="Button to click"),
        ],
    )
    goal = template.render_goal({"app": "Chrome", "button": "Submit"})
    assert goal == "Open Chrome and click Submit"


def test_validate_params():
    template = WorkflowTemplate(
        id="test",
        name="Test",
        description="Test",
        category="test",
        goal_template="{name}",
        params=[
            TemplateParam(name="name", description="Name", required=True),
            TemplateParam(name="color", description="Color", required=False),
        ],
    )
    errors = template.validate_params({"name": "hello"})
    assert len(errors) == 0

    errors = template.validate_params({})
    assert len(errors) == 1
    assert "name" in errors[0]


def test_template_choices():
    param = TemplateParam(
        name="browser",
        description="Browser",
        choices=["Chrome", "Firefox", "Safari"],
    )
    assert param.validate("Chrome")
    assert not param.validate("Opera")


def test_search_templates():
    registry = TemplateRegistry()
    results = registry.search("form")
    assert len(results) >= 1
    assert any("Form" in t.name for t in results)


def test_list_by_category():
    registry = TemplateRegistry()
    web_templates = registry.list_by_category("web_automation")
    assert len(web_templates) >= 1


def test_categories():
    registry = TemplateRegistry()
    cats = registry.categories
    assert "data_entry" in cats
    assert "web_automation" in cats


def test_register_custom():
    registry = TemplateRegistry()
    custom = WorkflowTemplate(
        id="custom_test",
        name="Custom Test",
        description="A custom template",
        category="custom",
        goal_template="Do {thing}",
    )
    registry.register(custom)
    assert registry.get("custom_test") is not None


def test_serialize_deserialize():
    template = WorkflowTemplate(
        id="ser_test",
        name="Serialization Test",
        description="Test serialization",
        category="test",
        goal_template="Do {action}",
        params=[TemplateParam(name="action", description="Action to perform")],
        tags=["test", "serialize"],
    )
    data = template.to_dict()
    restored = WorkflowTemplate.from_dict(data)
    assert restored.id == template.id
    assert restored.name == template.name
    assert len(restored.params) == 1
    assert restored.tags == ["test", "serialize"]


def test_save_load_file():
    registry = TemplateRegistry()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name

    registry.save_to_file(path)

    new_registry = TemplateRegistry()
    new_registry.load_from_file(path)

    assert len(new_registry.list_all()) >= 5
    Path(path).unlink()
