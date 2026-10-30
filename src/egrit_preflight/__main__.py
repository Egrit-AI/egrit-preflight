import sys

from .cli import main


def run():
    """Console-script entry point: pass the exit code to the shell."""
    sys.exit(main())


if __name__ == "__main__":
    run()
