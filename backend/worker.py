"""Private child entry point. No listening socket or client-provided pickle."""
import importlib
import os
from pathlib import Path
import pickle
import sys


def main():
    # Apply limits before importing numerical libraries. Linux is the supported
    # anonymous server platform; local mode does not require resource limits.
    import resource
    from backend import config
    memory_mb = config.worker_memory_mb()
    # Native numerical libraries map large shared objects. Limiting virtual
    # address space can crash their loader before any computation starts.
    # Linux RLIMIT_DATA bounds heap/anonymous allocations without counting those
    # file mappings; a deployment must also set its container memory limit.
    if memory_mb is not None:
        resource.setrlimit(resource.RLIMIT_DATA, (memory_mb * 1024 * 1024,) * 2)
    file_mb = config.optional_limit("WORKSPACE_MB")
    if file_mb is not None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_mb * 1024 * 1024,) * 2)
    request, output = map(Path, sys.argv[1:])
    module, name, args, kwargs = pickle.loads(request.read_bytes())
    try:
        function = getattr(importlib.import_module(module), name)
        value = function(*args, **kwargs)
        result = (True, value)
    except MemoryError:
        result = (False, (503, "Computation exceeded available server memory. The local version can use your machine's resources."))
    except Exception as error:
        from fastapi import HTTPException
        if isinstance(error, HTTPException):
            result = (False, (error.status_code, error.detail))
        else:
            # Do not disclose filesystem paths, event values or tracebacks.
            result = (False, (422, "Computation could not complete. Check the inputs and resource limits."))
    temporary = output.with_suffix(".tmp")
    temporary.write_bytes(pickle.dumps(result))
    os.replace(temporary, output)


if __name__ == "__main__":
    main()
