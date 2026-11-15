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

# llvm-objdump names the same machines differently from GNU objdump's -m.
LLVM_ARCH = {
    "i386:x86-64": "x86-64",
    "i386": "i386",
    "arm": "arm",
    "aarch64": "aarch64",
    "mips": "mips",
    "powerpc": "powerpc",
    "riscv:rv32": "riscv32",
    "riscv:rv64": "riscv64",
}

LLVM_NAMES = (
    "llvm-objdump",
    "llvm-objdump-20",
    "llvm-objdump-19",
    "llvm-objdump-18",
    "llvm-objdump-17",
    "llvm-objdump-16",
    "llvm-objdump-15",
)

_HEADER = re.compile(r"^\s*([0-9a-fA-F]+) <([^>]+)>:\s*$")
_INSN = re.compile(r"^\s*([0-9a-fA-F]+):\s+(.+?)\s*$")
# objdump -l puts "source.c:12" (sometimes with a discriminator) on its own line.
_LOCATION = re.compile(r"^(\S.*?):(\d+)(?:\s+\(discriminator\s+\d+\))?\s*$")
_TARGET = re.compile(r"<([^>+]+)")

# Branch instructions, per family: x86 conditional jumps, ARM/AArch64 bl/b.cond,
# MIPS/RISC-V jal, PowerPC bctr. A call or branch to a known function is an edge.
_FLOW_OPS = {
    "call", "callq", "jmp", "jmpq", "bl", "blr", "blx", "b", "br", "bx",
    "bal", "jal", "jalr", "jalx", "j", "jr", "jsr", "bc", "bcl", "bclr",
    "bctr", "cbz", "cbnz", "tbz", "tbnz",
}
_CONDITIONS = {
    "eq", "ne", "lt", "le", "gt", "ge", "hs", "hi", "lo", "ls", "mi",
    "pl", "vs", "vc", "cs", "cc", "al", "nz", "z",
}

_RELOC_HEAD = re.compile(r"RELOCATION RECORDS FOR \[(?P<section>[^\]]+)\]")
_RELOC_ROW = re.compile(r"^([0-9a-fA-F]+)\s+(R_\S+)\s+(.+?)\s*$")
_CODE_SECTIONS = (".text", ".plt", ".init", ".fini", ".plt.sec")


def _is_flow(asm: str) -> bool:
    """True when an instruction can lead to another function."""
    head = asm.split(None, 1)
    if not head:
        return False

    op = head[0].lower()
    if op in _FLOW_OPS:
        return True
    if op.startswith("j") and op[1:].isalpha() and len(op) <= 5:  # je, jne, jg, jle
        return True
    if op.startswith("b."):  # AArch64 conditional branch
        return True
    return op.startswith("b") and op[1:] in _CONDITIONS  # beq, bne, blt, bge


SOURCE_WIDTH = 72  # characters of the source line shown before it is cut


@dataclass(slots=True)
class Instruction:
    """One machine instruction, and where DWARF says it came from."""

    address: int
    asm: str
    source: str = ""  # the source file DWARF points at
    line: int = 0


@dataclass(slots=True)
class Function:
    """One function's instructions, in address order."""

    name: str
    address: int
    instructions: list[Instruction] = field(default_factory=list)
    callees: list[tuple[str, int]] = field(default_factory=list)  # (name, line)
    source: str = ""  # the file the code came from, as DWARF names it
    source_label: str = ""  # what the graph files it under


def available() -> bool:
    """True when some disassembler can be run."""
    return shutil.which("objdump") is not None or llvm_objdump() is not None


def llvm_objdump() -> str | None:
    """llvm-objdump, which can read every architecture LLVM supports.

    GNU objdump is built for one target: on an x86 host it prints a header and no
    instructions for an aarch64 binary, which looks exactly like an empty file.
    """
    for name in LLVM_NAMES:
        found = shutil.which(name)
        if found:
            return found

    for candidate in sorted(
        Path("/usr/lib").glob("llvm-*/bin/llvm-objdump"), reverse=True
    ):
        if candidate.is_file():
            return str(candidate)

    return None


def _commands(path: Path, machine: str | None) -> list[tuple[str, list[str]]]:
    """The disassemblers to try, in order, with their arguments."""
    commands: list[tuple[str, list[str]]] = []
    target = ["-m", machine] if machine else []

    if shutil.which("objdump"):
        commands.append(
            (
                "objdump",
                ["objdump", "-d", "-l", "--no-show-raw-insn", *target, str(path)],
            )
        )

    llvm = llvm_objdump()
    if llvm:
        arch = [f"--arch-name={LLVM_ARCH[machine]}"] if machine in LLVM_ARCH else []
        commands.append(
            (
                "llvm-objdump",
                [llvm, "-d", "-l", "--no-show-raw-insn", *arch, str(path)],
            )
        )

    return commands


def run_objdump(
    path: Path, machine: str | None = None, timeout: float = 20.0
) -> tuple[str, str]:
    """Disassembly text for ``path`` and the tool that produced it.

    ``-l`` adds the DWARF line table when the binary has one and prints nothing when it
    does not, so asking for it always is harmless. A run that prints no instruction is
    not accepted: GNU objdump happily prints a header for a foreign architecture.
    """
    for name, args in _commands(path, machine):
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

        if done.returncode != 0 or not done.stdout.strip():
            continue
        if any(_INSN.match(raw) for raw in done.stdout.splitlines()):
            return done.stdout, name

    return "", ""


def parse(text: str) -> list[Function]:
    """Split objdump's output into functions, keeping each instruction's source line."""
    functions: list[Function] = []
    current: Function | None = None
    source = ""
    number = 0

    for raw in text.splitlines():
        # llvm-objdump marks its own notes — source lines, function names — with ';'.
        body = raw.strip()
        if body.startswith(";"):
            body = body[1:].strip()
            location = _LOCATION.match(body)
            if location is not None:
                source = location.group(1)
                number = int(location.group(2))
            continue

        location = _LOCATION.match(raw)
        if location is not None and not _INSN.match(raw):
            source = location.group(1)
            number = int(location.group(2))
            continue

        header = _HEADER.match(raw)
        if header is not None:
            current = Function(name=header.group(2), address=int(header.group(1), 16))
            functions.append(current)
            # A location belongs to the code that follows it, never to the next symbol.
            source = ""
            number = 0
            continue

        if current is None:
            continue

        instruction = _INSN.match(raw)
        if instruction is None:
            continue

        # llvm-objdump separates mnemonics with tabs; one spacing for both tools.
        mnemonic = " ".join(instruction.group(2).split())
        found = Instruction(
            address=int(instruction.group(1), 16),
            asm=mnemonic,
            source=source if number else "",
            line=number,
        )
        if found.source and not current.source:
            current.source = found.source

        current.instructions.append(found)

    return [function for function in functions if function.instructions]


def run_relocations(
    path: Path, machine: str | None = None, timeout: float = 20.0
) -> dict[int, str]:
    """Instruction address -> the symbol a call there relocates to.

    An object file calls through an unresolved offset, so the operand alone cannot say
    which function is reached; the relocation table can.
    """
    commands: list[list[str]] = []
    llvm = llvm_objdump()
    if llvm:
        commands.append([llvm, "-r", str(path)])
    if shutil.which("objdump"):
        commands.append(["objdump", "-r", str(path)])

    for args in commands:
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

        if done.returncode != 0 or _RELOC_HEAD.search(done.stdout) is None:
            continue

        return _parse_relocations(done.stdout)

    return {}


def _parse_relocations(text: str) -> dict[int, str]:
    """Read the relocation records of the code sections."""
    found: dict[int, str] = {}
    in_code = False

    for raw in text.splitlines():
        header = _RELOC_HEAD.search(raw)
        if header is not None:
            section = header.group("section")
            in_code = section == ".text" or section.startswith(_CODE_SECTIONS)
            continue

        if not in_code:
            continue

        row = _RELOC_ROW.match(raw.strip())
        if row is None:
            continue

        value = row.group(3).split()[-1]  # GNU prints an offset before the name
        for separator in ("+", "-"):
            head, _sep, tail = value.partition(separator)
            if tail.startswith("0x"):
                value = head
                break

        found[int(row.group(1), 16)] = value

    return found


def _link(functions: list[Function], relocations: dict[int, str]) -> None:
    """Record which function each call or jump instruction reaches."""
    known = {function.name for function in functions}

    for function in functions:
        seen: set[str] = set()
        addresses = [instruction.address for instruction in function.instructions]

        for index, instruction in enumerate(function.instructions):
            if not _is_flow(instruction.asm):
                continue

            # A relocation names the callee in unlinked code; a linked binary has the
            # symbol in the operand itself. The relocation points at the operand field,
            # which on x86 sits one byte past the opcode, so look inside the instruction.
            end = (
                addresses[index + 1]
                if index + 1 < len(addresses)
                else instruction.address + 8
            )
            name = next(
                (
                    relocations[offset]
                    for offset in range(instruction.address, end)
                    if offset in relocations
                ),
                "",
            )
            if not name:
                target = _TARGET.search(instruction.asm)
                name = target.group(1) if target is not None else ""

            if not name or name not in known:
                continue
            if name == function.name or name in seen:
                continue  # one edge per callee, at the first place it is reached
            seen.add(name)
            function.callees.append((name, index + 1))


def _body(
    function: Function, label_of: dict[str, str], sources: dict[str, list[str]]
) -> str:
    """The node's text: the symbol line, then an instruction per line with its source.

    The DWARF location and the source text appear only where they change, so the
    assembly stays the thing you read while the source explains it.
    """
    lines = [f"{function.name}:   /* 0x{function.address:x} */"]

    width = max(
        (len(f"0x{instruction.address:x}") for instruction in function.instructions),
        default=4,
    )
    headings = [_heading(instruction, label_of) for instruction in function.instructions]
    location_width = min(LOCATION_WIDTH, max((len(h) for h in headings), default=0))
    previous = ""
    for instruction, heading in zip(function.instructions, headings):
        left = heading if heading != previous else ""
        fresh = heading != previous
        previous = heading

        address = f"0x{instruction.address:x}"
        parts = []
        if location_width:
            parts.append(f"{left:<{location_width}}  ")
        parts.append(f"{address:<{width}}  {instruction.asm}")

        text = _source_text(instruction, sources) if fresh else ""
        if text:
            parts.append(f"  | {text}")

        lines.append("".join(parts).rstrip())

    return "\n".join(lines)


def _heading(instruction: Instruction, label_of: dict[str, str]) -> str:
    """``main.c:12`` for an instruction, or "" when DWARF does not place it."""
    if not instruction.source or not instruction.line:
        return ""
    label = label_of.get(instruction.source)
    return f"{label}:{instruction.line}" if label else ""


def _source_text(instruction: Instruction, sources: dict[str, list[str]]) -> str:
    """The source line an instruction came from, when the file can still be read."""
    rows = sources.get(instruction.source)
    if not rows or not 0 < instruction.line <= len(rows):
        return ""

    text = rows[instruction.line - 1].strip()
    if len(text) > SOURCE_WIDTH:
        text = text[: SOURCE_WIDTH - 1] + "\u2026"
    return text


def _read_sources(paths: list[str], binary_dir: Path) -> dict[str, list[str]]:
    """Read the files DWARF names, once each; missing ones are simply absent."""
    found: dict[str, list[str]] = {}

    for name in paths:
        candidate = Path(name)
        for option in (
            candidate,
            binary_dir / candidate,
            binary_dir.parent / candidate,
        ):
            if not option.is_file():
                continue
            try:
                found[name] = option.read_text(
                    encoding="utf-8", errors="replace"
                ).split("\n")
            except OSError:
                pass
            break

    return found


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

    text, tool = run_objdump(path, machine)
    if not text:
        tools = "objdump and llvm-objdump" if llvm_objdump() else "objdump"
        if machine:
            name = next(
                (label for label, target, _ in ARCHITECTURES if target == machine),
                machine,
            )
            detail = f" as {name}"
        else:
            detail = ""

        hint = ""
        if llvm_objdump() is None:
            hint = (
                " GNU objdump only reads the architecture it was built for;"
                " install llvm for the others."
            )
        return None, f"{tools} could not disassemble {path.name}{detail}.{hint}"

    functions = parse(text)
    if not functions:
        return None, f"{path.name} has no machine code {tool} can show."

    functions.sort(key=lambda function: function.address)
    truncated = len(functions) > MAX_FUNCTIONS
    functions = functions[:MAX_FUNCTIONS]
    _link(functions, run_relocations(path, machine))

    has_lines = any(
        instruction.line
        for function in functions
        for instruction in function.instructions
    )
    files = sorted(
        {
            instruction.source
            for function in functions
            for instruction in function.instructions
            if instruction.source
        }
    )
    labels = _label_source(files)
    # The source itself, when the files the binary was built from are still around.
    sources = _read_sources(files, path.parent)
    for function in functions:
        function.source_label = labels.get(function.source, "")

    bodies = {
        function.name: _body(function, labels, sources) for function in functions
    }

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
    if tool and tool != "objdump":
        note += f" · {tool}"
    shown = len([label for label in groups if label])
    if has_lines and shown:
        detail = "DWARF + source" if sources else "DWARF line info"
        note += f" · {detail} · {shown} files"
    else:
        note += " · no DWARF"
    if truncated:
        note += f" (capped at {MAX_FUNCTIONS})"
    return graph, note
