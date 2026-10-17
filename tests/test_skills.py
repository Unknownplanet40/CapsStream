import os
import re

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", ".agents", "skills")

def test_skills_have_frontmatter():
    skills = [
        "create-issue", "issue", "fix-bug", "new-feature",
        "handoff-mode", "project-log", "ui-redesign", "commit-workflow", "ponytail"
    ]
    for skill in skills:
        skill_md = os.path.join(SKILLS_DIR, skill, "SKILL.md")
        assert os.path.isfile(skill_md), f"Missing SKILL.md for {skill}"
        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()
        assert content.startswith("---"), f"Missing YAML frontmatter in {skill}/SKILL.md"
        assert re.search(r"^name:\s*" + re.escape(skill), content, re.MULTILINE), f"Mismatched name in {skill}/SKILL.md"
        assert re.search(r"^description:", content, re.MULTILINE), f"Missing description in {skill}/SKILL.md"

def test_create_issue_links():
    skill_md = os.path.join(SKILLS_DIR, "create-issue", "SKILL.md")
    with open(skill_md, "r", encoding="utf-8") as f:
        content = f.read()
    assert "ISSUE_TEMPLATE" in content, "create-issue must reference ISSUE_TEMPLATE"
    assert "fix-bug" in content, "create-issue must link to fix-bug"
    assert "new-feature" in content, "create-issue must link to new-feature"
    assert "commit-workflow" in content, "create-issue must link to commit-workflow"

if __name__ == "__main__":
    test_skills_have_frontmatter()
    test_create_issue_links()
    print("All skill checks passed successfully.")
