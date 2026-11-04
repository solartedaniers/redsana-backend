try:
    import resource
except ImportError:  # Windows: solo existe en Unix, como el servidor de Render.
    resource = None


def peak_memory() -> str:
    """Pico de memoria residente del proceso en MB, para el log de arranque de cada worker; en Linux ru_maxrss va en
    KB. Sin el módulo resource responde "unknown"."""
    if resource is None:
        return "unknown"
    return f"{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB"
