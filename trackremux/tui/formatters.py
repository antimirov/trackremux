def format_duration(seconds):
    """Format seconds into a human-readable duration (e.g., 3h 48m 06s)."""
    if seconds < 60:
        return f"{seconds:.2f}s"

    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}h {mins}m {secs}s"
    return f"{mins}m {secs}s"


def format_size(size_mb, precision=2):
    """Format size in MB to GB if large enough."""
    if size_mb >= 1024:
        return f"{size_mb / 1024:.{precision}f} GB"
    return f"{size_mb:.{precision}f} MB"
