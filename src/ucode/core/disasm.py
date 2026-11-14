"""Disassembly: one node per function, an edge for every call or jump.

The instructions come from ``objdump``, which is part of binutils and present wherever a
C toolchain is. Nothing here executes the binary: it is only read.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ucode.core.graph import (
    GAP,
    PADDING,
    Edge,
    FileGraph,
    FolderBox,
    Node,
    folder_size,
    node_size,
)

MAX_FUNCTIONS = 200  # past this the graph is no longer something a person can read

_HEADER = re.compile(r"^([0-9a-fA-F]+) <([^>]+)>:\s*$")
_INSN = re.compile(r"^\s*([0-9a-fA-F]+):\s+(.+?)\s*$")
_TARGET = re.compile(r"<([^>+]+)")
_FLOW = re.compile(r"^(callq?|jmpq?|j[a-z]{1,3})\b")


@dataclass(slots=True)
class Function:
    """One function's instructions, in address order."""

    name: str
    address: int
    instructions: list[tuple[int, str]] = field(default_factory=list)
    callees: list[tuple[str, int]] = field(default_factory=list)  # (name, line)


def available() -> bool:
    """True when objdump can be run."""
    return shutil.which("objdump") is not None


def run_objdump(path: Path, timeout: float = 20.0) -> str:
    """The disassembly text for ``path``, or "" when objdump cannot provide it."""
    for args in (
        ["objdump", "-d", "--no-show-raw-insn", str(path)],
        ["objdump", "-d", str(path)],
    ):
        try:
            done = subprocess.run(
                args,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue

        if done.returncode == 0 and done.stdout.strip():
            return done.stdout

    return ""


def parse(text: str) -> list[Function]:
    """Split objdump's output into functions, keeping each instruction's line."""
    functions: list[Function] = []
    current: Function | None = None

    for raw in text.splitlines():
        header = _HEADER.match(raw)
        if header is not None:
            current = Function(name=header.group(2), address=int(header.group(1), 16))
            functions.append(current)
            continue

        if current is None:
            continue

        instruction = _INSN.match(raw)
        if instruction is None:
            continue

        current.instructions.append(
            (int(instruction.group(1), 16), instruction.group(2))
        )

    return [function for function in functions if function.instructions]


def _link(functions: list[Function]) -> None:
    """Record which function each call or jump instruction reaches."""
    known = {function.name for function in functions}

    for function in functions:
        seen: set[str] = set()
        for index, (_address, asm) in enumerate(function.instructions):
            if not _FLOW.match(asm):
                continue
            target = _TARGET.search(asm)
            if target is None or target.group(1) not in known:
                continue
            name = target.group(1)
            if name == function.name or name in seen:
                continue  # one edge per callee, at the first place it is reached
            seen.add(name)
            function.callees.append((name, index + 1))


def _body(function: Function) -> str:
    """The node's text: the symbol line, then one line per instruction."""
    lines = [f"{function.name}:   /* 0x{function.address:x} */"]
    width = max((len(f"0x{address:x}") for address, _ in function.instructions), default=4)
    for address, asm in function.instructions:
        lines.append(f"{f'0x{address:x}'.ljust(width)}  {asm}")
    return "\n".join(lines)


def _pack(sizes: list[tuple[float, float]], gap: float) -> tuple[list, tuple[float, float]]:
    """Columns of nodes: a stack per column, columns left to right."""
    from ucode.core.graph import _pack_columns

    return _pack_columns(sizes, gap)


def build_graph(path: Path) -> tuple[FileGraph | None, str]:
    """A call graph of the binary's functions; the second value explains a failure."""
    if not available():
        return None, "objdump is not installed (binutils), so there is nothing to disassemble."

    text = run_objdump(path)
    if not text:
        return None, f"objdump could not read {path.name}."

    functions = parse(text)
    if not functions:
        return None, f"{path.name} has no machine code objdump can show."

    functions.sort(key=lambda function: function.address)
    truncated = len(functions) > MAX_FUNCTIONS
    functions = functions[:MAX_FUNCTIONS]
    _link(functions)

    bodies = {function.name: _body(function) for function in functions}
    sizes: list[tuple[float, float]] = []
    nodes: list[Node] = []

    for function in functions:
        text_of_node = bodies[function.name]
        lines = text_of_node.split("\n")
        rows = max(1, len(lines))
        columns = max(1, min(300, max(len(line) for line in lines)))
        sizes.append(node_size(rows, columns))

    offsets, width, height = _pack(sizes, GAP)
    label = path.name + (f" (first {MAX_FUNCTIONS} functions)" if truncated else "")
    box = FolderBox(
        folder="",
        label=label,
        tile=(0.0, 0.0),
        size=folder_size((width, height), label),
    )

    for function, size, offset in zip(functions, sizes, offsets):
        lines = bodies[function.name].split("\n")
        nodes.append(
            Node(
                path=f"{path.name}!{function.name}",
                label=function.name,
                folder="",
                tile=(box.tile[0] + PADDING + offset[0], box.tile[1] + 1 + PADDING + offset[1]),
                size=size,
                rows=max(1, len(lines)),
                columns=max(1, min(300, max(len(line) for line in lines))),
                kind="file",
            )
        )

    edges: list[Edge] = []
    by_name = {function.name: f"{path.name}!{function.name}" for function in functions}
    for function in functions:
        for callee, line in function.callees:
            target = by_name.get(callee)
            if target is None:
                continue
            edges.append(
                Edge(
                    source=by_name[function.name],
                    target=target,
                    source_line=line + 1,
                    target_line=1,
                    kind="call",
                )
            )

    graph = FileGraph(root=path.parent, nodes=nodes, folders=[box], edges=edges)
    for node in nodes:
        name = node.path.split("!", 1)[1]
        graph.synthetic[node.path] = (bodies[name], "readonly")

    note = f"{len(functions)} functions"
    if truncated:
        note += f" (capped at {MAX_FUNCTIONS})"
    return graph, note
