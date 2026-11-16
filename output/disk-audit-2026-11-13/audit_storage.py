"""Read-only storage inventory; no file contents are opened or deleted."""
from __future__ import annotations

from collections import defaultdict
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta
import heapq
import json
import os
from pathlib import Path
import time


OUTPUT = Path(__file__).parent
USER = Path(r'C:\Users\suici')
WORKSPACE = Path(r'C:\Users\suici\OneDrive\Documents\GitHub\selenium-tests')
NOW = datetime.now().astimezone()
CUTOFF = (NOW - timedelta(days=7)).timestamp()
NEW_FILES = []
CHANGED_FILES = []
LARGE_FILES = []
DIRECTORIES = []
ERRORS = []
COUNTS = {'files': 0, 'directories': 0, 'skipped_links': 0, 'errors': 0}
DAILY = defaultdict(lambda: {'files': 0, 'bytes': 0})
TOP_LIMIT = 120
START = time.monotonic()
LAST_PROGRESS = START
CURRENT_ROOT = ''


def push_top(heap, size, record):
    item = (size, record['path'], record)
    if len(heap) < TOP_LIMIT:
        heapq.heappush(heap, item)
    elif size > heap[0][0]:
        heapq.heapreplace(heap, item)


def log_error(path, error):
    COUNTS['errors'] += 1
    if len(ERRORS) < 100:
        ERRORS.append({'path': str(path), 'error': str(error)})


def empty_stats():
    return {'bytes': 0, 'files': 0, 'new_bytes': 0, 'new_files': 0,
            'existing_modified_bytes': 0, 'existing_modified_files': 0,
            'offline_logical_bytes': 0}


def walk(folder, depth=0):
    global LAST_PROGRESS
    total = empty_stats()
    COUNTS['directories'] += 1
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    metadata = entry.stat(follow_symlinks=False)
                    tag = getattr(metadata, 'st_reparse_tag', 0)
                    if tag in (0xA0000003, 0xA000000C):
                        COUNTS['skipped_links'] += 1
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if depth > 200:
                            log_error(entry.path, 'Depth limit')
                            continue
                        child = walk(entry.path, depth + 1)
                        for key in total:
                            total[key] += child[key]
                    elif entry.is_file(follow_symlinks=False):
                        size = metadata.st_size
                        created = getattr(metadata, 'st_birthtime', metadata.st_ctime)
                        modified = metadata.st_mtime
                        attributes = getattr(metadata, 'st_file_attributes', 0)
                        record = {'path': entry.path, 'bytes': size, 'created': created,
                                  'modified': modified, 'attributes': attributes}
                        total['bytes'] += size
                        total['files'] += 1
                        COUNTS['files'] += 1
                        if attributes & (0x1000 | 0x400000):
                            total['offline_logical_bytes'] += size
                        if CUTOFF <= created <= NOW.timestamp() + 300:
                            total['new_bytes'] += size
                            total['new_files'] += 1
                            push_top(NEW_FILES, size, record)
                            day = datetime.fromtimestamp(created).strftime('%Y-%m-%d')
                            DAILY[day]['files'] += 1
                            DAILY[day]['bytes'] += size
                        elif CUTOFF <= modified <= NOW.timestamp() + 300:
                            total['existing_modified_bytes'] += size
                            total['existing_modified_files'] += 1
                            push_top(CHANGED_FILES, size, record)
                        push_top(LARGE_FILES, size, record)
                        if time.monotonic() - LAST_PROGRESS >= 12:
                            print(json.dumps({'progress_root': CURRENT_ROOT, **COUNTS,
                                              'elapsed_seconds': round(time.monotonic() - START)}, ensure_ascii=False), flush=True)
                            LAST_PROGRESS = time.monotonic()
                except OSError as error:
                    log_error(entry.path, error)
    except OSError as error:
        log_error(folder, error)
    if (total['new_bytes'] >= 10_000_000 or total['existing_modified_bytes'] >= 100_000_000
            or (depth <= 3 and total['bytes'] >= 10_000_000)
            or str(folder).casefold() in {str(WORKSPACE).casefold(), str(WORKSPACE / 'output').casefold()}):
        DIRECTORIES.append({'path': str(folder), **total})
    return total


kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
                                     ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong)]
kernel.GetDiskFreeSpaceExW.restype = wintypes.BOOL
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
kernel.CloseHandle.argtypes = [wintypes.HANDLE]


class FileStandardInfo(ctypes.Structure):
    _fields_ = [('allocated', ctypes.c_longlong), ('logical', ctypes.c_longlong),
                ('links', wintypes.DWORD), ('delete_pending', ctypes.c_ubyte), ('directory', ctypes.c_ubyte)]


def physical_size(path):
    # A zero-access metadata handle, with NO_RECALL and OPEN_REPARSE_POINT,
    # prevents the audit from reading data or downloading cloud placeholders.
    handle = kernel.CreateFileW(path, 0, 7, None, 3, 0x00100000 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        return {'allocated_bytes': None, 'allocation_error': ctypes.get_last_error()}
    try:
        information = FileStandardInfo()
        ok = kernel.GetFileInformationByHandleEx(handle, 1, ctypes.byref(information), ctypes.sizeof(information))
        if ok:
            return {'allocated_bytes': information.allocated, 'metadata_logical_bytes': information.logical}
        return {'allocated_bytes': None, 'allocation_error': ctypes.get_last_error()}
    finally:
        kernel.CloseHandle(handle)


free, capacity, available = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
kernel.GetDiskFreeSpaceExW('C:\\', ctypes.byref(available), ctypes.byref(capacity), ctypes.byref(free))
disk = {'total_bytes': capacity.value, 'free_bytes': free.value}
roots = [USER, Path(r'C:\ProgramData'), Path(r'C:\Windows\SoftwareDistribution'),
         Path(r'C:\Windows\Temp'), Path(r'C:\Windows\Installer'), Path(r'C:\$Recycle.Bin')]
root_results = []
for root in roots:
    CURRENT_ROOT = str(root)
    result = {'path': str(root), **walk(root)}
    root_results.append(result)
    print(json.dumps({'root_complete': result, 'elapsed_seconds': round(time.monotonic() - START)}, ensure_ascii=False), flush=True)

large_by_path = {item[2]['path']: item[2] for heap in (NEW_FILES, CHANGED_FILES, LARGE_FILES) for item in heap}
for record in large_by_path.values():
    record.update(physical_size(record['path']))
    for field in ('created', 'modified'):
        record[field] = datetime.fromtimestamp(record[field]).astimezone().isoformat()

def sorted_heap(heap):
    return [large_by_path[item[2]['path']] for item in sorted(heap, reverse=True)]

report = {
    'audit_time': NOW.isoformat(), 'cutoff': datetime.fromtimestamp(CUTOFF).astimezone().isoformat(),
    'disk': disk, 'counters': COUNTS, 'elapsed_seconds': round(time.monotonic() - START, 1),
    'root_totals_logical': root_results,
    'new_files_by_creation_date': dict(sorted(DAILY.items())),
    'largest_new_files': sorted_heap(NEW_FILES),
    'largest_existing_recently_modified_files': sorted_heap(CHANGED_FILES),
    'largest_files_overall': sorted_heap(LARGE_FILES),
    'directory_totals_logical': sorted(DIRECTORIES, key=lambda row: row['new_bytes'], reverse=True),
    'errors_sample': ERRORS,
    'limitations': [
        'Directory totals are logical file sizes and may include cloud-only or sparse data.',
        'Allocated bytes are queried only for the largest files using metadata-only handles.',
        'Recently modified old file sizes are current sizes, not measured growth.',
        'Creation timestamps show current surviving files; deleted files and earlier disk snapshots are unavailable.',
        'Directory rows overlap; do not add parent and child rows.',
        'Some protected directories may be inaccessible.',
    ],
}
(OUTPUT / 'storage-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'report': str(OUTPUT / 'storage-audit.json'), 'counters': COUNTS,
                  'elapsed_seconds': report['elapsed_seconds']}, ensure_ascii=False), flush=True)
