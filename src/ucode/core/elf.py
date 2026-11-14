"""ELF binaries: recognise them, describe them, and dump them as hex.

Only the parts of the format the editor shows are read — the identity in the header and
the section table — so a malformed file cannot take the editor down.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from ucode.core.graph import FileGraph, FolderBox, Node, node_size
from ucode.core.graph import PADDING, folder_size

MAGIC = b"\x7fELF"

HEX_CAP = 16 * 1024  # bytes shown; a longer file keeps its tail untouched on save
BYTES_PER_LINE = 16

_MACHINES = {
    3: "x86",
    8: "MIPS",
    20: "PowerPC",
    40: "ARM",
    62: "x86-64",
    183: "AArch64",
    243: "RISC-V",
}

_TYPES = {
    0: "no type",
    1: "relocatable",
    2: "executable",
    3: "shared object",
    4: "core dump",
}

def is_elf(path: Path) -> bool:
    """True when the file starts with the ELF magic."""
    if not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(4) == MAGIC
    except OSError:
        return False


@dataclass(slots=True)
class ElfHeader:
    """What the header says about a binary."""

    bits: int  # 32 or 64
    endian: str  # "little" or "big"
    kind: str  # executable, shared object, ...
    machine: str
    entry: int
    sections: int
    machine_id: int = 0  # e_machine, for choosing a disassembler

    def summary(self, path: Path) -> str:
        return (
            f"{path.name}: ELF {self.bits}-bit {self.endian}-endian {self.machine} "
            f"{self.kind}, entry 0x{self.entry:x}, {self.sections} sections"
        )


def header(path: Path) -> ElfHeader | None:
    """Read the ELF identity, or None when the file is not a readable ELF."""
    try:
        data = path.read_bytes()[:64]
    except OSError:
        return None

    if len(data) < 52 or data[:4] != MAGIC:
        return None

    bits = 64 if data[4] == 2 else 32
    endian = ">" if data[5] == 2 else "<"

    try:
        kind, machine = struct.unpack_from(f"{endian}HH", data, 16)
        shoff, shentsize, shnum = section_table(bits, endian, data)
        entry = struct.unpack_from(f"{endian}{'Q' if bits == 64 else 'I'}", data, 24)[0]
    except struct.error:
        return None

    return ElfHeader(
        bits=bits,
        endian="little" if endian == "<" else "big",
        kind=_TYPES.get(kind, f"type {kind}"),
        machine=_MACHINES.get(machine, f"machine {machine}"),
        entry=entry,
        sections=shnum,
        machine_id=machine,
    )


def section_table(bits: int, endian: str, data: bytes) -> tuple[int, int, int]:
    """(offset of the section table, entry size, entry count) from an ELF header."""
    if bits == 64:
        shoff = struct.unpack_from(f"{endian}Q", data, 40)[0]
        shentsize = struct.unpack_from(f"{endian}H", data, 58)[0]
        shnum = struct.unpack_from(f"{endian}H", data, 60)[0]
    else:
        shoff = struct.unpack_from(f"{endian}I", data, 32)[0]
        shentsize = struct.unpack_from(f"{endian}H", data, 46)[0]
        shnum = struct.unpack_from(f"{endian}H", data, 48)[0]

    return shoff, shentsize, shnum


def hex_dump(data: bytes, start: int = 0, limit: int | None = None) -> str:
    """A hex editor's text: offset, bytes, and the same bytes as characters."""
    lines: list[str] = []
    end = len(data) if limit is None else min(len(data), limit)

    for offset in range(0, end, BYTES_PER_LINE):
        row = data[offset : min(offset + BYTES_PER_LINE, end)]
        hexed = " ".join(f"{byte:02x}" for byte in row)
        hexed = hexed.ljust(BYTES_PER_LINE * 3 - 1)
        text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in row)
        lines.append(f"{start + offset:08x}  {hexed}  |{text.ljust(BYTES_PER_LINE)}|")

    return "\n".join(lines)


def parse_hex_dump(text: str) -> bytes | None:
    """Turn an edited hex view back into bytes, or None when a line is not hex."""
    out = bytearray()

    for line in text.split("\n"):
        body = line.split("|", 1)[0].strip()
        if not body or body.startswith("#"):
            continue

        parts = body.split()
        if not parts or not _is_offset(parts[0]):
            return None

        for token in parts[1:]:
            if len(token) != 2:
                return None
            try:
                out.append(int(token, 16))
            except ValueError:
                return None

    return bytes(out)


def _is_offset(token: str) -> bool:
    if len(token) < 4 or len(token) % 2:
        return False
    return all(character in "0123456789abcdefABCDEF" for character in token)


def build_hex_graph(path: Path) -> FileGraph:
    """One node holding the file's bytes as a hex editor."""
    try:
        data = path.read_bytes()
    except OSError:
        data = b""

    shown = data[:HEX_CAP]
    text = hex_dump(shown)

    if len(data) > HEX_CAP:
        note = (
            f"# first {HEX_CAP // 1024} KiB of {len(data)} bytes shown;"
            " the rest of the file is kept as it is when this is saved"
        )
        text = f"{note}\n{text}"

    graph = _single_node_graph(
        path, text, mode="hex", label=f"{path.name} (hex)"
    )
    graph.tail = data[HEX_CAP:]
    return graph


WRAP = 240  # characters per line before a long one is split for display


def build_text_graph(path: Path) -> FileGraph:
    """One node holding the file as text, however unreadable it is.

    A binary has no line breaks, so its text is split every ``WRAP`` characters to keep
    it inside a node. Split text cannot be saved back — that would corrupt the file — so
    a wrapped view is read-only, while ordinary source text stays editable.
    """
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        text = ""

    wrapped = _wrap(text)
    mode = "readonly" if wrapped != text else None
    return _single_node_graph(path, wrapped, mode=mode, label=path.name)


def _wrap(text: str) -> str:
    """Split lines longer than WRAP characters, so any file fits a node."""
    if all(len(line) <= WRAP for line in text.split("\n")):
        return text

    out: list[str] = []
    for line in text.split("\n"):
        out.extend(line[index : index + WRAP] for index in range(0, len(line), WRAP))
        if not line:
            out.append("")

    return "\n".join(out)


def _single_node_graph(
    path: Path, text: str, *, mode: str | None, label: str
) -> FileGraph:
    """A workspace of one node, so a lone file can be opened without its folder."""
    lines = text.split("\n") or [""]
    rows = max(1, len(lines))
    columns = max(1, min(300, max((len(line) for line in lines), default=1)))
    size = node_size(rows, columns)

    node = Node(
        path=path.name,
        label=label,
        folder="",
        tile=(PADDING, PADDING),
        size=size,
        rows=rows,
        columns=columns,
        kind="file",
    )
    box = FolderBox(
        folder="",
        label=path.name,
        tile=(0.0, 0.0),
        size=folder_size((size[0], size[1]), path.name),
    )

    graph = FileGraph(root=path.parent, nodes=[node], folders=[box], edges=[])
    if mode is not None:
        graph.synthetic[node.path] = (text, mode)
    return graph
