from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any, Mapping

import yaml


class PromptManagerError(Exception):
    """Base exception for prompt configuration and rendering errors."""


class PromptNotFoundError(PromptManagerError):
    """Raised when a prompt or prompt version is not configured."""


class PromptRenderError(PromptManagerError):
    """Raised when the variables do not match the prompt template."""


@dataclass(frozen=True)
class RenderedPrompt:
    """A rendered prompt and the version that produced it."""

    name: str
    version: str
    content: str


class PromptManager:
    """Load and render versioned prompt templates from a YAML manifest."""

    def __init__(self, prompts_dir: str | Path, config_name: str = "config.yaml"):
        self.prompts_dir = Path(prompts_dir).resolve()
        self.config_path = self.prompts_dir / config_name
        self._config = self._load_config()

    def _load_config(self) -> Mapping[str, Any]:
        try:
            with self.config_path.open(encoding="utf-8") as config_file:
                config = yaml.safe_load(config_file)
        except FileNotFoundError as exc:
            raise PromptManagerError(
                f"Prompt config does not exist: {self.config_path}"
            ) from exc
        except yaml.YAMLError as exc:
            raise PromptManagerError(
                f"Prompt config is invalid YAML: {self.config_path}"
            ) from exc

        if not isinstance(config, dict) or not isinstance(config.get("prompts"), dict):
            raise PromptManagerError("Prompt config must contain a 'prompts' mapping")
        return config

    def load(self, name: str, version: str | None = None) -> tuple[str, str]:
        """Return the raw template and resolved version for a prompt."""
        prompt_config = self._config["prompts"].get(name)
        if not isinstance(prompt_config, dict):
            raise PromptNotFoundError(f"Prompt is not configured: {name}")

        resolved_version = version or prompt_config.get("default_version")
        versions = prompt_config.get("versions")
        if not resolved_version or not isinstance(versions, dict):
            raise PromptManagerError(f"Prompt configuration is incomplete: {name}")

        version_config = versions.get(resolved_version)
        if not isinstance(version_config, dict) or not version_config.get("file"):
            raise PromptNotFoundError(
                f"Prompt version is not configured: {name}@{resolved_version}"
            )

        template_path = (self.prompts_dir / version_config["file"]).resolve()
        if self.prompts_dir not in template_path.parents:
            raise PromptManagerError(
                f"Prompt file must be inside {self.prompts_dir}: {template_path}"
            )

        try:
            template = template_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PromptManagerError(
                f"Prompt template does not exist: {template_path}"
            ) from exc

        return template, str(resolved_version)

    def render(
        self,
        name: str,
        variables: Mapping[str, Any],
        version: str | None = None,
    ) -> RenderedPrompt:
        """Render a prompt and retain the exact version used."""
        template, resolved_version = self.load(name, version)
        required_variables = {
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name
        }
        missing_variables = required_variables - variables.keys()
        if missing_variables:
            missing = ", ".join(sorted(missing_variables))
            raise PromptRenderError(f"Missing prompt variables: {missing}")

        try:
            content = template.format_map(dict(variables))
        except (KeyError, ValueError, AttributeError, IndexError) as exc:
            raise PromptRenderError(f"Could not render prompt {name}: {exc}") from exc

        return RenderedPrompt(
            name=name,
            version=resolved_version,
            content=content,
        )
