#!/usr/bin/env python3
"""Requirements workflows are distributed exclusively by the Yiddiy package."""
import sys

def install(*args, **kwargs):
    raise ValueError("Install the Yiddiy package through agent-skill-distro/scripts/bootstrap-skills.sh; use yiddiy:requirements-traceability.")

if __name__ == '__main__':
    try:
        install()
    except ValueError as error:
        sys.exit(str(error))
