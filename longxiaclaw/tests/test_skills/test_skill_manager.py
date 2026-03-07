"""Tests for SkillManager: loading, lookup, trigger matching, and formatting."""

from __future__ import annotations

from pathlib import Path

import pytest

from longxiaclaw.skills.skill_manager import Skill, SkillManager

# Path to the real skills/ directory in the project
_PROJECT_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "skills"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def skills_dir(tmp_project):
    """Create a skills directory with a prompt-only and a tool skill."""
    d = tmp_project / "skills"

    # Prompt-only skill (no triggers)
    (d / "greet.md").write_text(
        "---\nname: greet\ndescription: Greet user\nversion: '1.0'\nenabled: true\nauthor: test\n---\nGreet the user warmly.\n",
        encoding="utf-8",
    )
    # Tool skill (has triggers)
    (d / "deploy.md").write_text(
        "---\nname: deploy\ndescription: Deploy app\nversion: '1.0'\ntriggers:\n  - deploy\nenabled: true\nauthor: test\n---\nDeploy the application.\n",
        encoding="utf-8",
    )
    (d / "_template.md").write_text(
        "---\nname: template\nenabled: false\n---\nTemplate\n",
        encoding="utf-8",
    )

    return d


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestLoading:
    def test_load_skill(self, sample_skill_file):
        mgr = SkillManager(sample_skill_file.parent)
        skill = mgr._load_skill(sample_skill_file)
        assert skill.name == "test_skill"
        assert skill.description == "A test skill for unit tests"
        assert skill.version == "1.0"
        assert skill.enabled is True
        assert "Test Skill" in skill.body

    def test_load_all_skips_underscore(self, tmp_project):
        skills_dir = tmp_project / "skills"
        (skills_dir / "_template.md").write_text(
            "---\nname: template\nenabled: false\n---\nBody\n",
            encoding="utf-8",
        )
        (skills_dir / "greet.md").write_text(
            "---\nname: greet\ndescription: Greet\nversion: '1.0'\nenabled: true\nauthor: test\n---\nGreet the user.\n",
            encoding="utf-8",
        )
        mgr = SkillManager(skills_dir)
        skills = mgr.get_active_skills()
        assert len(skills) == 1
        assert skills[0].name == "greet"

    def test_load_all_skips_disabled(self, tmp_project):
        skills_dir = tmp_project / "skills"
        (skills_dir / "disabled.md").write_text(
            "---\nname: disabled\ndescription: Off\nversion: '1.0'\nenabled: false\nauthor: test\n---\nBody\n",
            encoding="utf-8",
        )
        mgr = SkillManager(skills_dir)
        assert mgr.count == 0

    def test_load_all_empty_dir(self, tmp_project):
        skills_dir = tmp_project / "skills"
        mgr = SkillManager(skills_dir)
        assert mgr.get_active_skills() == []

    def test_load_all_nonexistent_dir(self, tmp_path):
        mgr = SkillManager(tmp_path / "nonexistent")
        assert mgr.get_active_skills() == []

    def test_load_skill_no_frontmatter(self, tmp_project):
        path = tmp_project / "skills" / "bad.md"
        path.write_text("No frontmatter here\n", encoding="utf-8")
        mgr = SkillManager(tmp_project / "skills")
        with pytest.raises(ValueError, match="No valid YAML frontmatter"):
            mgr._load_skill(path)

    def test_load_skill_invalid_yaml(self, tmp_project):
        path = tmp_project / "skills" / "bad.md"
        path.write_text("---\n{{invalid yaml: [\n---\nBody\n", encoding="utf-8")
        mgr = SkillManager(tmp_project / "skills")
        with pytest.raises(Exception):
            mgr._load_skill(path)

    def test_load_skill_defaults(self, tmp_project):
        path = tmp_project / "skills" / "minimal.md"
        path.write_text("---\nname: minimal\n---\nBody content\n", encoding="utf-8")
        mgr = SkillManager(tmp_project / "skills")
        skill = mgr._load_skill(path)
        assert skill.name == "minimal"
        assert skill.description == ""
        assert skill.triggers == []
        assert skill.enabled is True

    def test_reload(self, skills_dir):
        mgr = SkillManager(skills_dir)
        assert mgr.count == 2

        (skills_dir / "new.md").write_text(
            "---\nname: new\ndescription: New\nversion: '1.0'\nenabled: true\nauthor: test\n---\nNew skill.\n",
            encoding="utf-8",
        )
        mgr.reload()
        assert mgr.count == 3


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestLookup:
    def test_get_active_skills(self, skills_dir):
        mgr = SkillManager(skills_dir)
        active = mgr.get_active_skills()
        assert len(active) == 2
        names = {s.name for s in active}
        assert "greet" in names
        assert "deploy" in names

    def test_get_skill_by_name(self, skills_dir):
        mgr = SkillManager(skills_dir)
        skill = mgr.get_skill("greet")
        assert skill is not None
        assert skill.name == "greet"

    def test_get_skill_missing(self, skills_dir):
        mgr = SkillManager(skills_dir)
        assert mgr.get_skill("nonexistent") is None


# ---------------------------------------------------------------------------
# Skill types: prompt-only vs tool
# ---------------------------------------------------------------------------

class TestSkillTypes:
    def test_tool_skill_has_triggers(self):
        skill = Skill(name="search", description="", version="1.0",
                      triggers=["search for"], enabled=True, author="", body="")
        assert skill.is_tool_skill is True

    def test_prompt_skill_no_triggers(self):
        skill = Skill(name="greet", description="", version="1.0",
                      triggers=[], enabled=True, author="", body="")
        assert skill.is_tool_skill is False

    def test_get_prompt_skills(self, skills_dir):
        mgr = SkillManager(skills_dir)
        prompt_skills = mgr.get_prompt_skills()
        assert len(prompt_skills) == 1
        assert prompt_skills[0].name == "greet"

    def test_get_triggered_skills_only_matches_tool_skills(self, tmp_project):
        skills_dir = tmp_project / "skills"
        (skills_dir / "prompt.md").write_text(
            "---\nname: prompt\nenabled: true\n---\nPrompt skill\n",
            encoding="utf-8",
        )
        (skills_dir / "tool.md").write_text(
            "---\nname: tool\ntriggers:\n  - do thing\nenabled: true\n---\nTool skill\n",
            encoding="utf-8",
        )
        mgr = SkillManager(skills_dir)
        matched = mgr.get_triggered_skills("please do thing now")
        assert len(matched) == 1
        assert matched[0].name == "tool"


# ---------------------------------------------------------------------------
# Trigger matching
# ---------------------------------------------------------------------------

class TestTriggerMatching:
    def _make_mgr(self, skills):
        mgr = SkillManager.__new__(SkillManager)
        mgr._skills = skills
        return mgr

    def test_match_single_trigger(self):
        mgr = self._make_mgr([
            Skill(name="search", description="", version="1.0",
                  triggers=["search for"], enabled=True, author="", body=""),
        ])
        matched = mgr.get_triggered_skills("please search for python")
        assert len(matched) == 1
        assert matched[0].name == "search"

    def test_match_case_insensitive(self):
        mgr = self._make_mgr([
            Skill(name="search", description="", version="1.0",
                  triggers=["Search For"], enabled=True, author="", body=""),
        ])
        matched = mgr.get_triggered_skills("SEARCH FOR something")
        assert len(matched) == 1

    def test_no_match(self):
        mgr = self._make_mgr([
            Skill(name="search", description="", version="1.0",
                  triggers=["search for"], enabled=True, author="", body=""),
        ])
        matched = mgr.get_triggered_skills("hello world")
        assert len(matched) == 0

    def test_match_multiple_skills(self):
        mgr = self._make_mgr([
            Skill(name="a", description="", version="1.0",
                  triggers=["hello"], enabled=True, author="", body=""),
            Skill(name="b", description="", version="1.0",
                  triggers=["world"], enabled=True, author="", body=""),
        ])
        matched = mgr.get_triggered_skills("hello world")
        assert len(matched) == 2

    def test_match_only_first_trigger(self):
        """A skill with multiple triggers should only match once."""
        mgr = self._make_mgr([
            Skill(name="search", description="", version="1.0",
                  triggers=["search for", "look up"], enabled=True,
                  author="", body=""),
        ])
        matched = mgr.get_triggered_skills("search for and look up")
        assert len(matched) == 1

    def test_skips_prompt_only_skills(self):
        mgr = self._make_mgr([
            Skill(name="prompt", description="", version="1.0",
                  triggers=[], enabled=True, author="", body="always loaded"),
        ])
        matched = mgr.get_triggered_skills("always loaded")
        assert len(matched) == 0


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_format_skills_context(self, skills_dir):
        mgr = SkillManager(skills_dir)
        context = mgr.format_skills_context(mgr.get_active_skills())
        assert '<skill name="greet">' in context
        assert '<skill name="deploy">' in context
        assert "</skill>" in context

    def test_format_skills_context_empty(self, tmp_path):
        mgr = SkillManager(tmp_path / "nonexistent")
        assert mgr.format_skills_context([]) == ""


# ---------------------------------------------------------------------------
# Real skills/ directory — verify all shipped skills load correctly
# ---------------------------------------------------------------------------

class TestRealSkills:
    def test_all_skill_files_load(self):
        """Every .md in skills/ (except _-prefixed) must parse without error."""
        mgr = SkillManager(_PROJECT_SKILLS_DIR)
        for path in sorted(_PROJECT_SKILLS_DIR.glob("*.md")):
            if path.name.startswith("_"):
                continue
            skill = mgr._load_skill(path)
            assert skill.name, f"{path.name} has no name"
            assert skill.description, f"{path.name} has no description"
            assert skill.body, f"{path.name} has no body"

    def test_enabled_skills_count(self):
        """We ship 3 enabled skills: summarize, translate, web_search."""
        mgr = SkillManager(_PROJECT_SKILLS_DIR)
        assert mgr.count == 3
        names = {s.name for s in mgr.get_active_skills()}
        assert names == {"summarize", "translate", "web_search"}

    def test_prompt_only_skills(self):
        """summarize and translate are prompt-only (no triggers)."""
        mgr = SkillManager(_PROJECT_SKILLS_DIR)
        prompt = mgr.get_prompt_skills()
        names = {s.name for s in prompt}
        assert names == {"summarize", "translate"}
        for s in prompt:
            assert not s.is_tool_skill

    def test_tool_skills(self):
        """web_search is a tool skill (has triggers)."""
        mgr = SkillManager(_PROJECT_SKILLS_DIR)
        ws = mgr.get_skill("web_search")
        assert ws is not None
        assert ws.is_tool_skill
        assert len(ws.triggers) > 0

    def test_web_search_triggers_match(self):
        """web_search triggers should fire on common search phrases."""
        mgr = SkillManager(_PROJECT_SKILLS_DIR)
        for phrase in ["search for python", "look up the weather", "google it"]:
            matched = mgr.get_triggered_skills(phrase)
            assert any(s.name == "web_search" for s in matched), (
                f"web_search should trigger on: {phrase}"
            )

    def test_all_skills_have_instructions_section(self):
        """Every enabled skill body should contain '## Instructions'."""
        mgr = SkillManager(_PROJECT_SKILLS_DIR)
        for skill in mgr.get_active_skills():
            assert "## Instructions" in skill.body, (
                f"{skill.name} missing '## Instructions' section"
            )

    def test_template_is_skipped(self):
        """_template.md must not appear in active skills."""
        mgr = SkillManager(_PROJECT_SKILLS_DIR)
        assert mgr.get_skill("template") is None


# ---------------------------------------------------------------------------
# New skills following the template
# ---------------------------------------------------------------------------

class TestNewSkillFromTemplate:
    def test_prompt_only_skill(self, tmp_project):
        """A new prompt-only skill following the template loads correctly."""
        skills_dir = tmp_project / "skills"
        (skills_dir / "code_review.md").write_text(
            "---\n"
            "name: code_review\n"
            "description: Review code for quality and bugs\n"
            'version: "1.0"\n'
            "enabled: true\n"
            "author: user\n"
            "---\n\n"
            "# Code Review\n\n"
            "Review the user's code.\n\n"
            "## Instructions\n\n"
            "- Check for bugs and edge cases\n"
            "- Suggest improvements\n",
            encoding="utf-8",
        )
        mgr = SkillManager(skills_dir)
        skill = mgr.get_skill("code_review")
        assert skill is not None
        assert not skill.is_tool_skill
        assert skill in mgr.get_prompt_skills()
        assert "## Instructions" in skill.body

    def test_tool_skill(self, tmp_project):
        """A new tool skill following the template loads and triggers correctly."""
        skills_dir = tmp_project / "skills"
        (skills_dir / "deploy.md").write_text(
            "---\n"
            "name: deploy\n"
            "description: Deploy the application\n"
            'version: "1.0"\n'
            "triggers:\n"
            '  - "deploy to"\n'
            '  - "ship it"\n'
            "enabled: true\n"
            "author: user\n"
            "---\n\n"
            "# Deploy\n\n"
            "Deploy the application to production.\n\n"
            "## Instructions\n\n"
            "- Run the deploy pipeline\n",
            encoding="utf-8",
        )
        mgr = SkillManager(skills_dir)
        skill = mgr.get_skill("deploy")
        assert skill is not None
        assert skill.is_tool_skill
        assert skill not in mgr.get_prompt_skills()
        matched = mgr.get_triggered_skills("please deploy to staging")
        assert len(matched) == 1
        assert matched[0].name == "deploy"

    def test_disabled_skill_ignored(self, tmp_project):
        """A new skill with enabled: false should not load."""
        skills_dir = tmp_project / "skills"
        (skills_dir / "wip.md").write_text(
            "---\n"
            "name: wip\n"
            "description: Work in progress\n"
            'version: "1.0"\n'
            "enabled: false\n"
            "author: user\n"
            "---\n\n"
            "# WIP\n\n"
            "## Instructions\n\n"
            "Not ready yet.\n",
            encoding="utf-8",
        )
        mgr = SkillManager(skills_dir)
        assert mgr.get_skill("wip") is None
        assert mgr.count == 0
