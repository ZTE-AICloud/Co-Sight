from pathlib import Path

# 兼容两种运行方式：
# 1) 作为包模块导入/执行：`python -m app.cosight.tool.agent_skills.skill_skill`
# 2) 直接运行文件：`python app/cosight/tool/agent_skills/skill_skill.py`
if __package__:
    from .skills_ref import read_body
else:  # pragma: no cover
    import sys

    this_file = Path(__file__).resolve()
    repo_root = next(
        (p for p in this_file.parents if (p / "app").is_dir() and (p / "skills").is_dir()),
        None,
    )
    if repo_root is not None:
        sys.path.insert(0, str(repo_root))

    from app.cosight.tool.agent_skills.skills_ref import read_body


def skill_skill(skill: str, args=None):

    this_file = Path(__file__).resolve()
    repo_root = next((p for p in this_file.parents if (p / "skills").is_dir()), None)
    if repo_root is None:
        raise FileNotFoundError(f"无法定位工程根目录：未在 {this_file} 的上级目录中找到 skills/ 目录")

    skill_path = repo_root / "skills" / skill

    body = read_body(skill_path)

    output = f"Base directory for this skill: {skill_path}\n\n{body}"

    if args:
        output += f"\n\nARGUMENTS: {args}"

    return output


if __name__ == '__main__':
    import sys

    skill = sys.argv[1] if len(sys.argv) > 1 else "frontend-design"
    args = sys.argv[2:] or None
    output = skill_skill(skill, args=args)
    print(output)
