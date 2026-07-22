from __future__ import annotations

import ntpath
import os
from pathlib import Path
from typing import BinaryIO


class WindowsCacheTrustError(OSError):
    pass


def _normalize_final_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def _is_within_profile(final_path: str, user_home: Path) -> bool:
    try:
        normalized_path = ntpath.normcase(ntpath.abspath(final_path))
        normalized_home = ntpath.normcase(ntpath.abspath(str(user_home.resolve(strict=True))))
        return ntpath.commonpath((normalized_path, normalized_home)) == normalized_home
    except (OSError, ValueError):
        return False


def open_trusted_windows_cache(path: Path, user_home: Path) -> BinaryIO:
    """Open and validate a cache using one Windows kernel handle.

    The final object, owner, and DACL are all inspected through the handle returned
    by CreateFileW. Pathname checks are never used as authorization decisions.
    """
    if os.name != "nt":
        raise WindowsCacheTrustError("Windows cache validation requires Windows")

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    generic_read = 0x80000000
    read_control = 0x00020000
    share_all = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    open_reparse_point = 0x00200000
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    se_file_object = 1
    owner_security_information = 0x00000001
    dacl_security_information = 0x00000004
    token_query = 0x0008
    token_user_class = 1
    error_insufficient_buffer = 122
    invalid_handle_value = ctypes.c_void_p(-1).value

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("User", SidAndAttributes)]

    class AclHeader(ctypes.Structure):
        _fields_ = [
            ("AclRevision", ctypes.c_ubyte),
            ("Sbz1", ctypes.c_ubyte),
            ("AclSize", ctypes.c_ushort),
            ("AceCount", ctypes.c_ushort),
            ("Sbz2", ctypes.c_ushort),
        ]

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    handle = kernel32.CreateFileW(
        str(path),
        generic_read | read_control,
        share_all,
        None,
        open_existing,
        open_reparse_point,
        None,
    )
    if handle == invalid_handle_value:
        raise WindowsCacheTrustError(ctypes.get_last_error(), "CreateFileW failed")

    token = wintypes.HANDLE()
    security_descriptor = ctypes.c_void_p()
    transferred = False
    try:
        information = ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(information)):
            raise WindowsCacheTrustError(
                ctypes.get_last_error(), "GetFileInformationByHandle failed"
            )
        if information.dwFileAttributes & file_attribute_directory:
            raise WindowsCacheTrustError("release policy cache is a directory")
        if information.dwFileAttributes & file_attribute_reparse_point:
            raise WindowsCacheTrustError("release policy cache is a reparse point")

        capacity = 32768
        final_path_buffer = ctypes.create_unicode_buffer(capacity)
        path_length = kernel32.GetFinalPathNameByHandleW(
            handle, final_path_buffer, capacity, 0
        )
        if path_length == 0 or path_length >= capacity:
            raise WindowsCacheTrustError(
                ctypes.get_last_error(), "GetFinalPathNameByHandleW failed"
            )
        final_path = _normalize_final_path(final_path_buffer.value)
        if not _is_within_profile(final_path, user_home):
            raise WindowsCacheTrustError(
                "release policy cache is outside the Windows user profile"
            )

        owner_sid = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        security_status = advapi32.GetSecurityInfo(
            handle,
            se_file_object,
            owner_security_information | dacl_security_information,
            ctypes.byref(owner_sid),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(security_descriptor),
        )
        if security_status != 0:
            raise WindowsCacheTrustError(security_status, "GetSecurityInfo failed")
        if not dacl.value:
            raise WindowsCacheTrustError("release policy cache has a null DACL")

        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
        ):
            raise WindowsCacheTrustError(ctypes.get_last_error(), "OpenProcessToken failed")
        token_size = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, token_user_class, None, 0, ctypes.byref(token_size)
        )
        if ctypes.get_last_error() != error_insufficient_buffer:
            raise WindowsCacheTrustError(
                ctypes.get_last_error(), "GetTokenInformation sizing failed"
            )
        token_buffer = ctypes.create_string_buffer(token_size.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_class,
            token_buffer,
            token_size,
            ctypes.byref(token_size),
        ):
            raise WindowsCacheTrustError(
                ctypes.get_last_error(), "GetTokenInformation failed"
            )
        current_sid = ctypes.cast(
            token_buffer, ctypes.POINTER(TokenUser)
        ).contents.User.Sid
        if not advapi32.EqualSid(owner_sid, current_sid):
            raise WindowsCacheTrustError(
                "release policy cache is not owned by the current user"
            )

        def sid_string(sid: ctypes.c_void_p) -> str:
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise WindowsCacheTrustError(
                    ctypes.get_last_error(), "ConvertSidToStringSidW failed"
                )
            try:
                return text.value
            finally:
                kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))

        allowed_writers = {
            sid_string(current_sid),
            "S-1-5-18",  # LocalSystem
            "S-1-5-32-544",  # Builtin Administrators
            "S-1-3-0",  # Creator Owner
            "S-1-3-4",  # Owner Rights
        }
        write_mask = (
            0x00000002
            | 0x00000004
            | 0x00000010
            | 0x00000100
            | 0x00010000
            | 0x00040000
            | 0x00080000
            | 0x10000000
            | 0x40000000
        )
        allow_ace_types = {0, 5, 9, 11}
        safe_non_allow_ace_types = {
            1,
            2,
            3,
            6,
            7,
            8,
            10,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
        }
        acl = ctypes.cast(dacl, ctypes.POINTER(AclHeader)).contents
        for index in range(acl.AceCount):
            ace = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
                raise WindowsCacheTrustError(ctypes.get_last_error(), "GetAce failed")
            ace_type = ctypes.c_ubyte.from_address(ace.value).value
            if ace_type not in allow_ace_types:
                if ace_type not in safe_non_allow_ace_types:
                    raise WindowsCacheTrustError("unsupported cache ACL entry")
                continue
            if ace_type != 0:
                raise WindowsCacheTrustError("complex allow ACE is not trusted")
            access_mask = ctypes.c_uint32.from_address(ace.value + 4).value
            if not access_mask & write_mask:
                continue
            ace_sid = ctypes.c_void_p(ace.value + 8)
            if sid_string(ace_sid) not in allowed_writers:
                raise WindowsCacheTrustError(
                    "release policy cache is writable by another principal"
                )

        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        transferred = True
        return os.fdopen(descriptor, "rb")
    finally:
        if token:
            kernel32.CloseHandle(token)
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)
        if not transferred:
            kernel32.CloseHandle(handle)
