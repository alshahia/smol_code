"""Tool binding helper (M2).

Why this exists
---------------
smolagents' Docker executor serialises a Tool by calling
``instance_to_source(tool, base_cls=Tool)``. The serialiser:

1. Reads class attributes from ``cls.__dict__`` (NOT inherited ones).
2. Reads methods from ``cls.__dict__`` (inherited methods are skipped
   unless they are explicitly redefined on the immediate class).
3. Calls ``get_source(cls)`` to obtain the class source for
   ``validate_tool_attributes``.

The remote side then executes the source and instantiates the class
with NO arguments (``tool_name = ClassName()``). That means any state
passed via ``__init__`` is **lost** the moment the class is
re-instantiated on the remote.

The smolagents docs explicitly call this out:
    "Args chosen at init are not traceable, so we cannot rebuild the
    source code for them, thus any important arg should be defined as a
    class attribute."
    -- smolagents/tool_validation.py:validate_tool_attributes

So we need each per-build piece of state (workspace path, command
allowlist, git cwd) to live as a CLASS attribute of a one-off subclass
that we generate per ``build_*_tools`` call.

How it works
------------
``bind_attrs(base_cls, attrs)`` returns a NEW class with:

* All attributes copied from ``base_cls.__dict__`` (so ``forward``,
  ``__init__``, ``name``, ``description``, etc. become attrs of the
  new class and therefore visible to ``instance_to_source``).
* The extra ``attrs`` merged on top.
* ``__source__`` set to ``base_cls``'s source so ``get_source(cls)``
  in ``tool_validation.validate_tool_attributes`` can find it.

Constraints
-----------
* ``validate_tool_attributes`` rejects class attributes that are
  "complex" (``ast.walk(node.value)`` must contain ONLY Constant,
  Dict, List, or Set nodes — ast.Load contexts cause lists to
  fail). In practice this means list/tuple/empty-list class
  attributes are rejected. We sidestep that by encoding collections
  as pipe-separated strings (``"python|git|pytest"``) and splitting
  them inside ``forward()``.
"""

from __future__ import annotations

import inspect


def bind_attrs(base_cls, attrs):
    """Return a subclass of ``base_cls`` with ``attrs`` merged in.

    The returned class has all of ``base_cls``'s own attributes
    (methods + class attrs) copied into its own ``__dict__``, plus
    ``attrs``. ``__source__`` is set to ``base_cls``'s source so
    ``get_source`` works for ``validate_tool_attributes``.
    """
    new_dict = {}
    # Copy all of base_cls's own attributes (methods + class attrs).
    # vars(base_cls) is base_cls.__dict__ which excludes inherited.
    for key, value in vars(base_cls).items():
        # Skip __doc__ to avoid surprising the remote; we let the
        # serialised source carry the docstring.
        if key == "__doc__":
            continue
        new_dict[key] = value
    for key, value in attrs.items():
        new_dict[key] = value
    new_cls = type(base_cls.__name__, (base_cls,), new_dict)
    try:
        new_cls.__source__ = inspect.getsource(base_cls)
    except (OSError, TypeError):
        # Should not happen for module-level classes, but stay safe.
        new_cls.__source__ = ""
    return new_cls
