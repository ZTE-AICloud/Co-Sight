from pathlib import Path
from .skills_ref import read_body


def skill_skill(skill: str, args=None):

    skill_path = "/home/10350383@zte.intra/code/github/Co-Sight/skills/" + skill

    body = read_body(Path(skill_path))

    output = f"Base directory for this skill: {skill_path}\n\n{body}"

    if args:
        output += f"\n\nARGUMENTS: {args}"

    return output


if __name__ == '__main__':
    output = skill_skill("algorithmic-art")
    print(output)