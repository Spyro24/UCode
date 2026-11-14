"""Disassembly: one node per function, an edge for every call or jump.

The instructions come from ``objdump``, which is part of binutils and present wherever a
C toolchain is. When the binary carries DWARF debug info, objdump's line table is read
too: every instruction is labelled with the source line it was compiled from, and each
function is filed under the source file it belongs to. Nothing here executes the binary.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ucode.core.graph import (
    BOX_GAP,
    GAP,
    PADDING,
    Edge,
    FileGraph,
    FolderBox,
    Node,
    _pack_boxes,
    _pack_columns,
    folder_size,
    node_size,
)

MAX_FUNCTIONS = 200  # past this the graph is no longer something a person can read
LOCATION_WIDTH = 28  # characters of "file.c:123" shown before an instruction

# The architectures objdump can be pointed at, and the e_machine each one comes from.
ARCHITECTURES: tuple[tuple[str, str, int], ...] = (
    ("x86-64", "i386:x86-64", 62),
    ("x86 (i386)", "i386", 3),
    ("ARM", "arm", 40),
    ("AArch64", "aarch64", 183),
    ("MIPS", "mips", 8),
    ("PowerPC", "powerpc", 20),
    ("RISC-V 32", "riscv:rv32", 243),
    ("RISC-V 64", "riscv:rv64", 243),
)

_HEADER = re.compile(r"^([0-9a-fA-F]+) <([^>]+)>:\s*$")
_INSN = re.compile(r"^\s*([0-9a-fA-F]+):\s+(.+?)\s*$")
# objdump -l puts "source.c:12" (sometimes with a discriminator) on its own line.
_LOCATION = re.compile(r"^(\S.*?):(\d+)(?:\s+\(discriminator\s+\d+\))?\s*$")
_TARGET = re.compile(r"<([^>+]+)")
_FLOW = re.compile(r"^(callq?|jmpq?|j[a-z]{1,3})\b")


@dataclass(slots=True)
class Function:
    """One function's instructions, in address order."""

    name: str
    address: int
    # (address, assembly, "source.c:12" or "")
    instructions: list[tuple[int, str, str]] = field(default_factory=list)
    callees: list[tuple[str, int]] = field(default_factory=list)  # (name, line)
    source: str = ""  # the file the code came from, as DWARF names it
    source_label: str = ""  # what the graph files it under


def available() -> bool:
    """True when objdump can be run."""
    return shutil.which("objdump") is not None


def run_objdump(path: Path, machine: str | None = None, timeout: float = 20.0) -> str:
    """The disassembly text for ``path``, or "" when objdump cannot provide it.

    ``-l`` adds the DWARF line table when the binary has one and prints nothing when it
    does not, so asking for it always is harmless.
    """
    target = ["-m", machine] if machine else []
    for args in (
        ["objdump", "-d", "-l", "--no-show-raw-insn", *target, str(path)],
        ["objdump", "-d", "-l", *target, str(path)],
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
    """Split objdump's output into functions, keeping each instruction's source line."""
    functions: list[Function] = []
    current: Function | None = None
    source = ""
    line = ""

    for raw in text.splitlines():
        location = _LOCATION.match(raw)
        if location is not None and not _INSN.match(raw):
            source = location.group(1)
            line = f"{Path(source).name}:{location.group(2)}"
            continue

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

        if line and not current.source:
            current.source = source

        current.instructions.append(
            (int(instruction.group(1), 16), instruction.group(2), line)
        )

    return [function for function in functions if function.instructions]


def _link(functions: list[Function]) -> None:
    """Record which function each call or jump instruction reaches."""
    known = {function.name for function in functions}

    for function in functions:
        seen: set[str] = set()
        for index, (_address, asm, _line) in enumerate(function.instructions):
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
    """The node's text: the symbol line, then an instruction per line with its source."""
    lines = [f"{function.name}:   /* 0x{function.address:x} */"]

    width = max(
        (len(f"0x{address:x}") for address, _asm, _line in function.instructions),
        default=4,
    )
    location_width = min(
        LOCATION_WIDTH,
        max((len(line) for _a, _s, line in function.instructions), default=0),
    )

    previous = ""
    for address, asm, line in function.instructions:
        # The source line only where it changes; repeating it on every instruction
        # would bury the assembly.
        left = line if line != previous else ""
        previous = line
        if location_width:
            lines.append(f"{left:<{location_width}}  {f'0x{address:x}':<{width}}  {asm}")
        else:
            lines.append(f"{f'0x{address:x}':<{width}}  {asm}")

    return "\n".join(lines)


def _label_source(files: list[str]) -> dict[str, str]:
    """Short, unique names for the source files DWARF mentions."""
    labels: dict[str, str] = {}
    seen: set[str] = set()

    for path in files:
        name = Path(path).name
        if name in seen:
            # Two files with the same name: keep one more directory level.
            name = f"{Path(path).parent.name}/{name}"
        seen.add(name)
        labels[path] = name

    return labels


def build_graph(
    path: Path, machine: str | None = None
) -> tuple[FileGraph | None, str]:
    """A call graph of the binary's functions; the second value explains a failure."""
    if not available():
        return None, "objdump is not installed (binutils), so there is nothing to disassemble."

    text = run_objdump(path, machine)
    if not text:
        if machine:
            name = next(
                (label for label, target, _ in ARCHITECTURES if target == machine),
                machine,
            )
            return None, f"objdump could not disassemble {path.name} as {name}."
        return None, f"objdump could not read {path.name}."

    functions = parse(text)
    if not functions:
        return None, f"{path.name} has no machine code objdump can show."

    functions.sort(key=lambda function: function.address)
    truncated = len(functions) > MAX_FUNCTIONS
    functions = functions[:MAX_FUNCTIONS]
    _link(functions)

    has_lines = any(line for function in functions for _a, _s, line in function.instructions)
    labels = _label_source(
        sorted({function.source for function in functions if function.source})
    )
    for function in functions:
        function.source_label = labels.get(function.source, "")

    bodies = {function.name: _body(function) for function in functions}

    # One box per source file: DWARF tells which file each function was built from.
    groups: dict[str, list[Function]] = {}
    for function in functions:
        groups.setdefault(function.source_label, []).append(function)

    boxes: list[FolderBox] = []
    offsets: dict[str, list[tuple[float, float]]] = {}
    sizes: dict[str, list[tuple[float, float]]] = {}

    # Files DWARF knows about lead the layout; the binary's own unnamed code follows,
    # so a debug build opens on the code the user wrote.
    ordered = sorted(groups, key=lambda label: (label == "", label))

    for label in ordered:
        members = groups[label]
        member_sizes = []
        for function in members:
            text_of_node = bodies[function.name]
            rows = max(1, text_of_node.count("\n") + 1)
            columns = max(1, min(300, max(len(line) for line in text_of_node.split("\n"))))
            member_sizes.append(node_size(rows, columns))

        packed, width, height = _pack_columns(member_sizes, GAP)
        sizes[label] = member_sizes
        offsets[label] = packed
        boxes.append(
            FolderBox(
                folder=label,
                label=label or path.name,
                tile=(0.0, 0.0),
                size=folder_size((width, height), label or path.name),
            )
        )

    # DWARF files are packed together at the top; anything unlabelled goes underneath,
    # so a debug build opens on the code the user wrote.
    sourced = [box for box in boxes if box.folder]
    leftover = [box for box in boxes if not box.folder]
    _pack_boxes(sourced, BOX_GAP)

    below = max((box.tile[1] + box.size[1] for box in sourced), default=0.0)
    top = below + BOX_GAP if sourced else 0.0
    edge = 0.0
    for box in leftover:
        box.tile = (edge, top)
        edge += box.size[0] + BOX_GAP

    where = {box.folder: box for box in boxes}

    nodes: list[Node] = []
    node_paths: dict[str, str] = {}

    for label in ordered:
        members = groups[label]
        box = where[label]
        for function, size, offset in zip(members, sizes[label], offsets[label]):
            text_of_node = bodies[function.name]
            lines = text_of_node.split("\n")
            node_path = f"{path.name}!{function.name}"
            node_paths[function.name] = node_path
            nodes.append(
                Node(
                    path=node_path,
                    label=function.name,
                    folder=label,
                    tile=(
                        box.tile[0] + PADDING + offset[0],
                        box.tile[1] + 1 + PADDING + offset[1],
                    ),
                    size=size,
                    rows=max(1, len(lines)),
                    columns=max(1, min(300, max(len(line) for line in lines))),
                    kind="file",
                )
            )

    edges: list[Edge] = []
    for function in functions:
        for callee, line in function.callees:
            target = node_paths.get(callee)
            if target is None:
                continue
            edges.append(
                Edge(
                    source=node_paths[function.name],
                    target=target,
                    source_line=line + 1,
                    target_line=1,
                    kind="call",
                )
            )

    graph = FileGraph(root=path.parent, nodes=nodes, folders=boxes, edges=edges)
    for function in functions:
        graph.synthetic[node_paths[function.name]] = (bodies[function.name], "readonly")

    note = f"{len(functions)} functions"
    files = len([label for label in groups if label])
    if has_lines and files:
        note += f" · DWARF line info · {files} files"
    else:
        note += " · no DWARF"
    if truncated:
        note += f" (capped at {MAX_FUNCTIONS})"
    return graph, note
