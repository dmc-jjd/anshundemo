"""Resolve task ownership without substituting a customer-specific default."""
from core.packages import context


def resolve_task_package(package=None, *, state=None, store=None, task_id=None):
    """Explicit package, persisted ownership, then configured context/default.

    Empty strings in legacy tasks mean unspecified, not a package directory.
    A missing deployment default remains PackageNotSpecified.
    """
    explicit = str(package or "").strip()
    if explicit:
        return explicit
    if state is None and store is not None and task_id is not None:
        state = store.get_task(task_id)
    owned = str(getattr(state, "package", "") or "").strip()
    if owned:
        return owned
    task_id = task_id or getattr(state, "id", None)
    if store is not None:
        owner = getattr(store, "package_of", None)
        if callable(owner) and task_id:
            owned = str(owner(task_id) or "").strip()
            if owned:
                return owned
        configured = getattr(store, "package", None)
        configured = configured() if callable(configured) else configured
        if configured and str(configured).strip():
            return str(configured).strip()
    return context.current_ref().name
