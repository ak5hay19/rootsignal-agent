"""Split markdown runbooks into one chunk per "##" section.

Pure functions only: no model, FAISS, or sim imports, so this is cheap to test.
"""

from dataclasses import dataclass
from pathlib import Path

RUNBOOK_DIR = Path(__file__).parent / "runbooks"


@dataclass(frozen=True)
class Chunk:
    runbook: str  # filename, e.g. "oom.md"
    title: str  # the "# " heading
    section: str  # the "## " heading
    text: str  # section body, without the heading line

    @property
    def embed_text(self) -> str:
        """Text that gets embedded: title and section give the chunk its context."""
        return f"{self.title} - {self.section}: {self.text}"


def chunk_markdown(runbook: str, markdown: str) -> list[Chunk]:
    """Split one runbook into chunks. Empty sections are dropped."""
    title = runbook
    section: str | None = None
    body: list[str] = []
    chunks: list[Chunk] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if section is not None and text:
            chunks.append(Chunk(runbook, title, section, text))

    for line in markdown.splitlines():
        if line.startswith("## "):
            flush()
            section, body = line[3:].strip(), []
        elif line.startswith("# "):
            title = line[2:].strip()
        else:
            body.append(line)
    flush()
    return chunks


def chunk_dir(path: Path | str | None = None) -> list[Chunk]:
    """Chunk every *.md file in a directory, in filename order."""
    folder = Path(path) if path else RUNBOOK_DIR
    chunks: list[Chunk] = []
    for file in sorted(folder.glob("*.md")):
        chunks.extend(chunk_markdown(file.name, file.read_text(encoding="utf-8")))
    return chunks
