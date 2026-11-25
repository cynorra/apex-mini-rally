#!/usr/bin/env python3
"""
Patches Godot 4.x arm64-v8a libgodot_android.so (both standalone .so files and inside
.aar / .apk / .aab / .zip archives such as godot-lib.template_release.aar) so that every
call to glBindBufferBase(target, index, buffer) and glBindBufferRange(target, index, buffer, offset, size)
also invokes glBindBuffer(target, buffer).

Root cause fixed:
In Android emulators (LDPlayer / AOSP emugl libstagefright_gl2enc.so + libOpenglCodecCommon.so),
s_glBindBufferBase checks GLClientState::isIndexedBindNoOp(target, index, buffer, ...).
When the same UBO ID is already bound to that indexed slot from a previous frame,
isIndexedBindNoOp returns true and s_glBindBufferBase returns early WITHOUT updating
the generic GL_UNIFORM_BUFFER target binding (which Godot unbinds to 0 via
glBindBuffer(GL_UNIFORM_BUFFER, 0) after uploading UBOs).
Subsequent glBufferData / glBufferSubData(GL_UNIFORM_BUFFER, ...) calls then fail with:
  GL2Encoder.cpp:s_glBufferData:975 GL error 0x502 condition [bufferId==0]
freezing or corrupting all 3D SceneData / InstanceData / Light UBOs after Frame 1.
"""
import array
import os
import shutil
import struct
import sys
import tempfile
import zipfile


def encode_bl(pc: int, target: int) -> int:
    diff = (target - pc) >> 2
    return 0x94000000 | (diff & 0x03FFFFFF)


def encode_b(pc: int, target: int) -> int:
    diff = (target - pc) >> 2
    return 0x14000000 | (diff & 0x03FFFFFF)


def patch_so_bytes(raw: bytes, label: str = "libgodot_android.so") -> tuple[bytes, int, int]:
    data = bytearray(raw)

    if data[:4] != b"\x7fELF" or data[4] != 2 or struct.unpack_from("<H", data, 0x12)[0] != 183:
        print(f"[skip] {label} is not an ARM64 ELF64 binary")
        return raw, 0, 0

    e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3A)
    sections = [
        struct.unpack_from("<IIQQQQIIQQ", data, e_shoff + i * e_shentsize)
        for i in range(e_shnum)
    ]
    shstr_off = sections[e_shstrndx][4]

    def sec_name(s) -> str:
        end = data.find(b"\x00", shstr_off + s[0])
        return data[shstr_off + s[0] : end].decode("ascii", errors="replace")

    sec_map = {sec_name(s): s for s in sections}
    dynsym_sec = sec_map[".dynsym"]
    dynstr_sec = sec_map[".dynstr"]
    rela_plt_sec = sec_map[".rela.plt"]
    plt_sec = sec_map[".plt"]
    text_sec = sec_map[".text"]

    text_vaddr = text_sec[3]
    text_off = text_sec[4]
    text_size = text_sec[5]
    plt_vaddr = plt_sec[3]

    str_off = dynstr_sec[4]
    sym_names = {}
    cave_vaddr = None

    for idx in range(0, dynsym_sec[5], dynsym_sec[9]):
        st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from(
            "<IBBHQQ", data, dynsym_sec[4] + idx
        )
        end = data.find(b"\x00", str_off + st_name)
        name = data[str_off + st_name : end].decode("ascii", errors="replace")
        sym_names[idx // dynsym_sec[9]] = name
        if name == "UPNP_UpdatePinhole" and st_value != 0 and st_size >= 80:
            cave_vaddr = st_value

    if cave_vaddr is None:
        raise RuntimeError(f"Could not find suitable code cave in {label}")

    plt_targets = {}
    for i in range(0, rela_plt_sec[5], rela_plt_sec[9]):
        r_offset, r_info, r_addend = struct.unpack_from("<QQq", data, rela_plt_sec[4] + i)
        sym_idx = r_info >> 32
        plt_idx = i // rela_plt_sec[9]
        p_vaddr = plt_vaddr + 0x20 + plt_idx * 0x10
        name = sym_names.get(sym_idx, "")
        if name in ("glBindBufferBase", "glBindBufferRange", "glBindBuffer"):
            plt_targets[name] = p_vaddr

    bind_base_plt = plt_targets["glBindBufferBase"]
    bind_range_plt = plt_targets["glBindBufferRange"]
    bind_buf_plt = plt_targets["glBindBuffer"]

    cave1_vaddr = cave_vaddr
    cave2_vaddr = cave_vaddr + 0x28

    def write_u32(vaddr: int, val: int) -> None:
        off = text_off + (vaddr - text_vaddr)
        struct.pack_into("<I", data, off, val)

    t1 = [
        0xA9BF7BFD,  # stp x29, x30, [sp, #-16]!
        0xA9BF53F3,  # stp x19, x20, [sp, #-16]!
        0x2A0003F3,  # mov w19, w0 (target)
        0x2A0203F4,  # mov w20, w2 (buffer)
        encode_bl(cave1_vaddr + 16, bind_base_plt),
        0x2A1303E0,  # mov w0, w19
        0x2A1403E1,  # mov w1, w20
        0xA8C153F3,  # ldp x19, x20, [sp], #16
        0xA8C17BFD,  # ldp x29, x30, [sp], #16
        encode_b(cave1_vaddr + 36, bind_buf_plt),
    ]
    for i, w in enumerate(t1):
        write_u32(cave1_vaddr + i * 4, w)

    t2 = [
        0xA9BF7BFD,
        0xA9BF53F3,
        0x2A0003F3,
        0x2A0203F4,
        encode_bl(cave2_vaddr + 16, bind_range_plt),
        0x2A1303E0,
        0x2A1403E1,
        0xA8C153F3,
        0xA8C17BFD,
        encode_b(cave2_vaddr + 36, bind_buf_plt),
    ]
    for i, w in enumerate(t2):
        write_u32(cave2_vaddr + i * 4, w)

    insns = array.array("I")
    insns.frombytes(data[text_off : text_off + text_size])

    patched_base = 0
    patched_range = 0
    for idx, insn in enumerate(insns):
        pc = text_vaddr + idx * 4
        if cave1_vaddr <= pc < cave2_vaddr + 40:
            continue
        if (insn & 0xFC000000) == 0x94000000:
            imm26 = insn & 0x03FFFFFF
            if imm26 & 0x02000000:
                imm26 -= 0x04000000
            t = pc + imm26 * 4
            if t == bind_base_plt:
                write_u32(pc, encode_bl(pc, cave1_vaddr))
                patched_base += 1
            elif t == bind_range_plt:
                write_u32(pc, encode_bl(pc, cave2_vaddr))
                patched_range += 1

    print(
        f"[patched] {label}: {patched_base} glBindBufferBase + {patched_range} glBindBufferRange calls"
    )
    return bytes(data), patched_base, patched_range


def patch_so(so_path: str) -> None:
    with open(so_path, "rb") as f:
        raw = f.read()
    patched, _, _ = patch_so_bytes(raw, so_path)
    with open(so_path, "wb") as f:
        f.write(patched)


def patch_zip_archive(archive_path: str) -> bool:
    """Patches any arm64-v8a/libgodot_android.so inside a .aar, .apk, .aab, or .zip archive."""
    if not zipfile.is_zipfile(archive_path):
        return False
    with zipfile.ZipFile(archive_path, "r") as zin:
        targets = [
            name
            for name in zin.namelist()
            if name.endswith("libgodot_android.so") and "arm64-v8a" in name
        ]
        if not targets:
            return False

        fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        modified = False
        try:
            with zipfile.ZipFile(tmp_path, "w") as zout:
                for info in zin.infolist():
                    if info.filename.startswith("META-INF/") and (
                        info.filename.endswith((".SF", ".RSA", ".DSA", ".EC"))
                        or info.filename == "META-INF/MANIFEST.MF"
                    ):
                        continue
                    content = zin.read(info.filename)
                    if info.filename in targets:
                        new_content, b_cnt, r_cnt = patch_so_bytes(
                            content, f"{archive_path}!{info.filename}"
                        )
                        if b_cnt > 0 or r_cnt > 0:
                            content = new_content
                            modified = True
                    zout.writestr(info, content, compress_type=info.compress_type)
            if modified:
                shutil.move(tmp_path, archive_path)
            return modified
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def process_path(arg: str) -> None:
    if os.path.isfile(arg):
        if arg.endswith(".so"):
            patch_so(arg)
        elif arg.endswith((".aar", ".apk", ".aab", ".zip")):
            patch_zip_archive(arg)
    elif os.path.isdir(arg):
        for root, _, files in os.walk(arg):
            for f in files:
                full = os.path.join(root, f)
                if f == "libgodot_android.so" and "arm64-v8a" in root:
                    patch_so(full)
                elif f.endswith((".aar", ".apk")) and (
                    "godot-lib" in f or "android_release" in f or "android_debug" in f
                ):
                    patch_zip_archive(full)


def main() -> None:
    for arg in sys.argv[1:]:
        process_path(arg)


if __name__ == "__main__":
    main()
