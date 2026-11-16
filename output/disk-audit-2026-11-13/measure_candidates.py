"""Measure disk allocation through metadata handles without reading file data."""
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
from pathlib import Path

OUTPUT = Path(__file__).parent
inventory = json.loads((OUTPUT / 'storage-audit.json').read_text(encoding='utf-8'))
cutoff = datetime.fromisoformat(inventory['cutoff']).timestamp()
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
kernel.CloseHandle.argtypes = [wintypes.HANDLE]

class Standard(ctypes.Structure):
    _fields_ = [('allocated', ctypes.c_longlong), ('logical', ctypes.c_longlong),
                ('links', wintypes.DWORD), ('deleted', ctypes.c_ubyte), ('directory', ctypes.c_ubyte)]

class FileID(ctypes.Structure):
    _fields_ = [('volume', ctypes.c_ulonglong), ('identifier', ctypes.c_ubyte * 16)]

def allocation(path):
    handle = kernel.CreateFileW(path, 0, 7, None, 3, 0x00100000 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        return None, None, 0
    try:
        info = Standard()
        if not kernel.GetFileInformationByHandleEx(handle, 1, ctypes.byref(info), ctypes.sizeof(info)):
            return None, None, 0
        identifier = None
        if info.links > 1:
            file_id = FileID()
            if kernel.GetFileInformationByHandleEx(handle, 18, ctypes.byref(file_id), ctypes.sizeof(file_id)):
                identifier = (file_id.volume, bytes(file_id.identifier))
        return info.allocated, identifier, info.links
    finally:
        kernel.CloseHandle(handle)

def measure(root):
    pending = [root]
    stats = {'path': root, 'files': 0, 'logical_bytes': 0, 'allocated_bytes': 0,
             'new_logical_bytes': 0, 'new_allocated_bytes': 0, 'allocation_unknown_logical_bytes': 0,
             'multi_link_files': 0, 'deduplicated_hard_links': 0, 'errors': 0}
    seen = set()
    while pending:
        current = pending.pop()
        if os.path.isdir(current):
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            st = entry.stat(follow_symlinks=False)
                            if getattr(st, 'st_reparse_tag', 0) not in (0xA0000003, 0xA000000C):
                                pending.append(entry.path)
                        except OSError:
                            stats['errors'] += 1
            except OSError:
                stats['errors'] += 1
            continue
        try:
            st = os.stat(current, follow_symlinks=False)
            size = st.st_size
            new = st.st_birthtime >= cutoff
            allocated, identifier, links = allocation(current)
            stats['files'] += 1
            stats['logical_bytes'] += size
            stats['new_logical_bytes'] += size if new else 0
            if allocated is None:
                stats['allocation_unknown_logical_bytes'] += size
                continue
            if links > 1:
                stats['multi_link_files'] += 1
            if identifier is not None:
                if identifier in seen:
                    stats['deduplicated_hard_links'] += 1
                    continue
                seen.add(identifier)
            stats['allocated_bytes'] += allocated
            stats['new_allocated_bytes'] += allocated if new else 0
        except OSError:
            stats['errors'] += 1
    return stats

roots = [
    r'C:\Windows\SoftwareDistribution\Download',
    r'C:\Users\suici\AppData\Local\Temp',
    r'C:\Users\suici\AppData\Local\Temp\wbjvopzm',
    r'C:\Users\suici\.vscode\extensions\openai.chatgpt-26.1111.21308-win32-x64',
    r'C:\Users\suici\AppData\Roaming\Code\CachedExtensionVSIXs\openai.chatgpt-26.1111.21308-win32-x64',
    r'C:\Users\suici\AppData\Local\Programs\Microsoft VS Code',
    r'C:\Users\suici\AppData\Local\Microsoft\OneDrive\logs',
    r'C:\Users\suici\OneDrive\Documents\GitHub\selenium-tests',
    r'C:\Users\suici\.codex',
]
reports = []
for root in roots:
    record = measure(root)
    reports.append(record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
(OUTPUT / 'allocated-sizes.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
