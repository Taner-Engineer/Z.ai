"""Эксклюзивный межпроцессный файловый лок (только stdlib, Windows + POSIX).

Хэндл держать открытым всё время работы, release — в finally. Сам файл лока
не удалять: другой процесс может держать его открытым.
"""
import sys


def acquire(path) -> object | None:
    """Захватить лок: успех — открытый хэндл; занято — None (без исключений)."""
    f = open(path, "a+")  # не "w": truncate не трогаем чужой файл лока
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def release(handle) -> None:
    """Отпустить лок и закрыть хэндл."""
    try:
        if sys.platform == "win32":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
