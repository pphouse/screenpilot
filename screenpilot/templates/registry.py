"""Workflow template system for reusable automation patterns.

Enables non-technical users to automate tasks by selecting from
pre-built templates with configurable parameters, addressing the
#1 business need: replacing brittle RPA with adaptable AI automation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TemplateParam:
    """A configurable parameter in a workflow template."""

    name: str
    description: str
    param_type: str = "string"  # string, int, float, bool, choice, file_path
    required: bool = True
    default: Any = None
    choices: list[str] | None = None

    def validate(self, value: Any) -> bool:
        """Validate a parameter value."""
        if self.required and value is None:
            return False
        if self.choices and value not in self.choices:
            return False
        return True


@dataclass
class WorkflowTemplate:
    """A reusable workflow template.

    Templates define common automation patterns (e.g., "fill a web form",
    "extract data from a spreadsheet") with configurable parameters.
    The LLM agent uses the template's goal_template and step hints to
    execute the workflow more reliably.
    """

    id: str
    name: str
    description: str
    category: str  # data_entry, web_automation, file_management, system_admin, testing
    goal_template: str  # Template string with {param} placeholders
    params: list[TemplateParam] = field(default_factory=list)
    step_hints: list[str] = field(default_factory=list)
    estimated_steps: int = 10
    tags: list[str] = field(default_factory=list)

    def render_goal(self, params: dict[str, Any]) -> str:
        """Render the goal template with provided parameters."""
        return self.goal_template.format(**params)

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate all parameters, return list of error messages."""
        errors = []
        for p in self.params:
            value = params.get(p.name)
            if p.required and value is None:
                errors.append(f"Missing required parameter: {p.name}")
            elif value is not None and not p.validate(value):
                errors.append(f"Invalid value for {p.name}: {value}")
        return errors

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "goal_template": self.goal_template,
            "params": [
                {
                    "name": p.name,
                    "description": p.description,
                    "param_type": p.param_type,
                    "required": p.required,
                    "default": p.default,
                    "choices": p.choices,
                }
                for p in self.params
            ],
            "step_hints": self.step_hints,
            "estimated_steps": self.estimated_steps,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowTemplate:
        """Deserialize from dictionary."""
        params = [TemplateParam(**p) for p in data.get("params", [])]
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            category=data.get("category", "general"),
            goal_template=data["goal_template"],
            params=params,
            step_hints=data.get("step_hints", []),
            estimated_steps=data.get("estimated_steps", 10),
            tags=data.get("tags", []),
        )


class TemplateRegistry:
    """Registry of available workflow templates."""

    def __init__(self):
        self._templates: dict[str, WorkflowTemplate] = {}
        self._load_builtins()

    def _load_builtins(self) -> None:
        """Load built-in templates."""
        builtins = [
            WorkflowTemplate(
                id="web_form_fill",
                name="Fill Web Form",
                description="Navigate to a website and fill out a form with provided data",
                category="data_entry",
                goal_template=(
                    "Open {browser} and navigate to {url}. "
                    "Fill in the form with the following data: {form_data}. "
                    "Then click the submit button."
                ),
                params=[
                    TemplateParam(name="browser", description="Browser to use", default="Chrome"),
                    TemplateParam(name="url", description="URL of the form"),
                    TemplateParam(name="form_data", description="Key-value pairs for form fields"),
                ],
                step_hints=[
                    "Open the specified browser",
                    "Navigate to the URL",
                    "Identify form fields",
                    "Fill in each field with the provided data",
                    "Click the submit/save button",
                    "Verify submission was successful",
                ],
                estimated_steps=15,
                tags=["web", "form", "data-entry"],
            ),
            WorkflowTemplate(
                id="file_rename_batch",
                name="Batch Rename Files",
                description="Rename multiple files in a directory according to a pattern",
                category="file_management",
                goal_template=(
                    "Open the file manager and navigate to {directory}. "
                    "Rename all files matching '{pattern}' using the naming convention: {new_pattern}"
                ),
                params=[
                    TemplateParam(name="directory", description="Directory containing files"),
                    TemplateParam(name="pattern", description="File pattern to match (e.g., *.pdf)"),
                    TemplateParam(name="new_pattern", description="New naming pattern"),
                ],
                step_hints=[
                    "Open file manager",
                    "Navigate to directory",
                    "Sort files to identify matches",
                    "Select and rename each matching file",
                ],
                estimated_steps=20,
                tags=["files", "rename", "batch"],
            ),
            WorkflowTemplate(
                id="data_extract_table",
                name="Extract Table Data",
                description="Extract data from a table in an application and save to clipboard or file",
                category="data_entry",
                goal_template=(
                    "Open {application} and navigate to the table/spreadsheet at {location}. "
                    "Select all data in the table and copy it. "
                    "{output_action}"
                ),
                params=[
                    TemplateParam(name="application", description="Application containing the data"),
                    TemplateParam(name="location", description="Where the table is (file path, URL, etc.)"),
                    TemplateParam(
                        name="output_action",
                        description="What to do with the data",
                        default="Copy to clipboard",
                    ),
                ],
                step_hints=[
                    "Open the target application",
                    "Navigate to data location",
                    "Select all table data (Ctrl+A or manual selection)",
                    "Copy data (Ctrl+C)",
                    "Perform output action",
                ],
                estimated_steps=12,
                tags=["data", "extract", "table", "copy"],
            ),
            WorkflowTemplate(
                id="screenshot_report",
                name="Screenshot Report",
                description="Take screenshots of multiple application states for documentation",
                category="testing",
                goal_template=(
                    "Open {application} and take screenshots of the following screens: {screens}. "
                    "Save each screenshot to {output_directory} with descriptive names."
                ),
                params=[
                    TemplateParam(name="application", description="Application to screenshot"),
                    TemplateParam(name="screens", description="Comma-separated list of screens to capture"),
                    TemplateParam(name="output_directory", description="Directory to save screenshots", default="~/Screenshots"),
                ],
                step_hints=[
                    "Open the application",
                    "Navigate to each specified screen",
                    "Take a screenshot",
                    "Save with descriptive filename",
                    "Move to next screen",
                ],
                estimated_steps=20,
                tags=["screenshot", "documentation", "testing"],
            ),
            WorkflowTemplate(
                id="app_login",
                name="Application Login",
                description="Log into an application with provided credentials",
                category="web_automation",
                goal_template=(
                    "Open {browser} and navigate to {url}. "
                    "Enter username '{username}' and password. "
                    "Click the login/sign-in button and verify successful login."
                ),
                params=[
                    TemplateParam(name="browser", description="Browser to use", default="Chrome"),
                    TemplateParam(name="url", description="Login page URL"),
                    TemplateParam(name="username", description="Username/email"),
                ],
                step_hints=[
                    "Open browser",
                    "Navigate to login URL",
                    "Find and click username field",
                    "Type username",
                    "Find and click password field",
                    "Type password",
                    "Click login button",
                    "Verify login success (look for dashboard/profile)",
                ],
                estimated_steps=10,
                tags=["login", "authentication", "web"],
            ),
            WorkflowTemplate(
                id="email_send",
                name="Send Email",
                description="Compose and send an email via a mail client",
                category="web_automation",
                goal_template=(
                    "Open {email_client} and compose a new email. "
                    "Set the recipient to {recipient}, subject to '{subject}', "
                    "and body to: {body}. Then send the email."
                ),
                params=[
                    TemplateParam(name="email_client", description="Email client or web URL", default="Gmail"),
                    TemplateParam(name="recipient", description="Email recipient address"),
                    TemplateParam(name="subject", description="Email subject"),
                    TemplateParam(name="body", description="Email body text"),
                ],
                step_hints=[
                    "Open email client",
                    "Click compose/new email",
                    "Enter recipient",
                    "Enter subject",
                    "Enter body text",
                    "Click send",
                    "Verify email was sent",
                ],
                estimated_steps=12,
                tags=["email", "communication"],
            ),
        ]

        for t in builtins:
            self._templates[t.id] = t

    def get(self, template_id: str) -> WorkflowTemplate | None:
        """Get a template by ID."""
        return self._templates.get(template_id)

    def list_all(self) -> list[WorkflowTemplate]:
        """List all available templates."""
        return list(self._templates.values())

    def list_by_category(self, category: str) -> list[WorkflowTemplate]:
        """List templates in a specific category."""
        return [t for t in self._templates.values() if t.category == category]

    def search(self, query: str) -> list[WorkflowTemplate]:
        """Search templates by name, description, or tags."""
        query = query.lower()
        results = []
        for t in self._templates.values():
            if (
                query in t.name.lower()
                or query in t.description.lower()
                or any(query in tag for tag in t.tags)
            ):
                results.append(t)
        return results

    def register(self, template: WorkflowTemplate) -> None:
        """Register a new template."""
        self._templates[template.id] = template

    def load_from_file(self, path: str | Path) -> None:
        """Load templates from a JSON file."""
        with open(path) as f:
            data = json.load(f)

        templates = data if isinstance(data, list) else data.get("templates", [])
        for t_data in templates:
            template = WorkflowTemplate.from_dict(t_data)
            self._templates[template.id] = template
            logger.info("Loaded template: %s", template.name)

    def save_to_file(self, path: str | Path) -> None:
        """Save all templates to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"templates": [t.to_dict() for t in self._templates.values()]}
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @property
    def categories(self) -> list[str]:
        """Get all unique categories."""
        return sorted(set(t.category for t in self._templates.values()))
