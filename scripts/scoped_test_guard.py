"""Process-local accidental write/network guard for scoped test subprocesses."""
import os
from pathlib import Path
import sys


def install():
    root = Path(os.environ['V5_SCOPED_ROOT']).resolve()

    def writable(value):
        if value is None or isinstance(value, int) or str(value).lower() in (':memory:', 'nul', '\\\\.\\nul'):
            return
        path = Path(os.fsdecode(value)).resolve()
        if path != root and root not in path.parents:
            raise PermissionError('scoped_write_denied:' + str(path))

    def audit(event, args):
        if event == 'open':
            path, mode, flags = args
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                writable(path)
        elif event == 'sqlite3.connect':
            writable(args[0])
        elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime', 'os.truncate'):
            if event == 'os.mkdir' and os.path.isdir(args[0]):
                return
            writable(args[0])
        elif event in ('os.rename', 'os.link', 'os.symlink'):
            writable(args[0]); writable(args[1])
        elif event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto'):
            # Windows stdlib socketpair uses loopback IPC to implement asyncio.
            frame = sys._getframe(1)
            while frame:
                if event == 'socket.connect' and frame.f_globals.get('__name__') == 'socket' and frame.f_code.co_name == '_fallback_socketpair':
                    return
                frame = frame.f_back
            raise RuntimeError('scoped_real_network_denied')
        elif event == 'subprocess.Popen':
            executable, argv, cwd, env = args
            # CPython Windows audit receives a command-line string, often executable=None.
            # Only recognize the exact current Python prefix; never parse the -c body.
            expected = str(Path(sys.executable).resolve())
            if executable:
                allowed = str(Path(executable).resolve()).casefold() == expected.casefold()
            elif isinstance(argv, str):
                allowed = argv.casefold().startswith(('"' + expected + '" ').casefold()) or argv.casefold().startswith((expected + ' ').casefold())
            else:
                allowed = bool(argv) and str(Path(argv[0]).resolve()).casefold() == expected.casefold()
            if not allowed:
                raise RuntimeError('scoped_non_python_subprocess_denied')
            if env is not None and (env.get('V5_SCOPED_ROOT') != str(root) or env.get('PYTHONPATH') != os.environ.get('PYTHONPATH')):
                raise RuntimeError('scoped_child_environment_denied')
    sys.addaudithook(audit)
