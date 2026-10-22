"""Two explicit disposable capture outputs, separate from immutable launch inputs."""

import os
import stat


def capture_paths(root):
    return (root / "logs/stdout.log", root / "logs/stderr.log")


def validate_captures(root, *, phase="absent", inputs=(), streams=()):
    if phase not in ("absent", "prepared", "running"):
        raise ValueError("Invalid capture phase")
    paths = capture_paths(root)
    directory = root / "logs"
    if root != root.resolve() or directory != directory.resolve():
        raise ValueError("Aliasing capture directory")
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o777 != 0o700
    ):
        raise ValueError("Capture directory ownership mismatch")
    if set(map(str, paths)) & set(map(str, inputs)):
        raise ValueError("Capture/input collision")
    if streams and (len(streams) != 2 or phase == "absent"):
        raise ValueError("Capture descriptor contract mismatch")
    for index, path in enumerate(paths):
        if path.exists() or path.is_symlink():
            if phase == "absent":
                raise ValueError("Capture output exists before setup")
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o777 != 0o600
                or info.st_nlink != 1
            ):
                raise ValueError("Capture output type/ownership mismatch")
            if phase == "prepared" and info.st_size != 0:
                raise ValueError("Initial capture output must be empty")
            if info.st_size > 262144:
                raise ValueError("Capture output bound exceeded")
            if streams:
                descriptor = os.fstat(streams[index].fileno())
                if (descriptor.st_dev, descriptor.st_ino) != (info.st_dev, info.st_ino):
                    raise ValueError("Capture descriptor/path mismatch")
        elif phase != "absent":
            raise ValueError("Missing capture output")
    return paths


def open_capture(root, path):
    if path not in capture_paths(root):
        raise ValueError("Unapproved capture output path")
    directory = root / "logs"
    if root != root.resolve() or directory != directory.resolve():
        raise ValueError("Aliasing capture directory")
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory_fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
            raise ValueError("Capture directory ownership mismatch")
        fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
    finally:
        os.close(directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("Invalid capture descriptor")
        return os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        raise
