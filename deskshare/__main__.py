from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        from .app import run_daemon

        run_daemon()
        return
    from .ctl import main as ctl_main

    ctl_main(sys.argv[1:])


if __name__ == "__main__":
    main()
