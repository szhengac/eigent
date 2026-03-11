# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

"""
Skill Toolkit with multi-tier hierarchy:

Agent access control is managed via skills-config.json.
User isolation is managed via ~/.eigent/<user_id>/skills-config.json.
"""

import logging
from pathlib import Path
from typing import TypedDict

from camel.toolkits.skill_toolkit import SkillToolkit as BaseSkillToolkit

logger = logging.getLogger(__name__)


class SkillScopeConfig(TypedDict, total=False):
    isGlobal: bool
    selectedAgents: list[str]


class SkillEntryConfig(TypedDict, total=False):
    enabled: bool
    scope: SkillScopeConfig
    agents: list[str]


class SkillToolkit(BaseSkillToolkit):
    """Enhanced SkillToolkit with Eigent-specific features.

    Extends CAMEL's SkillToolkit with:
    - Eigent-specific skill paths (.eigent/skills)
    - Dynamic skill discovery: skills are rescanned on every access so that
      newly installed skills (e.g. created by the agent during the task)
      are visible without restarting.

    Skill Discovery Priority (highest to lowest):
    1. Repo scope: <wd>/skills, <wd>/.eigent/skills, <wd>/.camel/skills
    2. User scope: ~/.eigent/skills, ~/.camel/skills, ~/.config/camel/skills
    3. System scope: /etc/camel/skills
    """

    @classmethod
    def toolkit_name(cls) -> str:
        return "SkillToolkit"

    def _get_skills(self):
        """Return current skills, rescanned each time so new installs are visible.

        The base implementation caches skills once. We clear the cache before
        delegating so that skills added by the agent during the task (e.g.
        via terminal or file write) appear on the next list_skills/load_skill.
        """
        self.clear_cache()
        return super()._get_skills()

    def __init__(
        self,
        api_task_id: str,
        agent_name: str | None = None,
        working_directory: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """Initialize SkillToolkit with Eigent-specific context.

        Args:
            api_task_id: Task/project identifier for logging
            agent_name: Name of the agent (e.g., "developer", "browser")
            working_directory: Base directory for skill discovery
            timeout: Optional timeout for skill execution
        """
        self.api_task_id = api_task_id
        self.agent_name = agent_name
        logger.info(
            f"Initialized SkillToolkit for agent '{agent_name}' "
            f"in task '{api_task_id}'"
        )
        super().__init__(
            working_directory=working_directory,
            timeout=timeout,
        )

    def _skill_roots(self) -> list[tuple[str, Path]]:
        """Return skill roots with Eigent + CAMEL paths.

        Integrates Eigent-specific paths with CAMEL standard paths.
        Priority order (highest to lowest):
        1. Repo scope: project-specific skills
        2. User scope: user-level skills
        3. System scope: system-wide skills

        Returns:
            List of (scope, path) tuples in priority order
        """
        roots: list[tuple[str, Path]] = []

        # 1. Repo scope - project-specific skills (highest priority)
        roots.append(("repo", self.working_directory / "skills"))
        roots.append(("repo", self.working_directory / ".eigent" / "skills"))
        roots.append(("repo", self.working_directory / ".camel" / "skills"))
        roots.append(("repo", self.working_directory / ".agents" / "skills"))

        # 2. User scope - user-level skills
        roots.append(("user", Path.home() / ".eigent" / "skills"))
        roots.append(("user", Path.home() / ".camel" / "skills"))
        roots.append(("user", Path.home() / ".agents" / "skills"))
        roots.append(("user", Path.home() / ".config" / "camel" / "skills"))

        # 3. System scope - system-wide skills (lowest priority)
        roots.append(("system", Path("/etc/camel/skills")))

        logger.debug(
            f"Skill roots configured for {self.agent_name}: {len(roots)} paths"
        )

        return roots
