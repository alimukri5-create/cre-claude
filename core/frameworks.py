from pathlib import Path

FW_DIR = Path(__file__).resolve().parent.parent / "frameworks"


def honesty_rules() -> str:
    return (FW_DIR / "00_honesty_rules.md").read_text()


def list_frameworks():
    """[(id, title, text)] for every framework file except the honesty rules. Edit the .md files to change behaviour."""
    out = []
    for p in sorted(FW_DIR.glob("*.md")):
        if p.name.startswith("00_"):
            continue
        text = p.read_text()
        title = text.splitlines()[0].lstrip("# ").strip()
        out.append((p.stem, title, text))
    return out
