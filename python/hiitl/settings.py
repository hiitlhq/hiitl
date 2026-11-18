"""The variables a component's settings read, and the set names of its families that none reads.

Each component's settings models are the one list of the variables it reads (docs/specs/sync_engine.md section 9):
a set variable of one of the component's families that none of its models reads is refused, naming its replacement
or the names the family's settings read (row 207). Each component passes its own families and the names its own
models read; none holds a copy of another's (row 222).
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional


def variable(model, name: str) -> str:
    """The variable a settings model's field is read from: its alias, else the model's prefix and the field's name."""
    alias = model.model_fields[name].validation_alias
    return alias if isinstance(alias, str) else model.model_config["env_prefix"] + name.upper()


def read_variables(*models) -> frozenset:
    """Every variable the settings models' fields are read from."""
    return frozenset(variable(model, name) for model in models for name in model.model_fields)


def unread_variables(environ: Mapping[str, str], families: Iterable[str], read: Iterable[str],
                     earlier: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Each set variable of the families that no setting reads, named with its replacement (`earlier`, a name an
    earlier release read and the name read now) or the names the family's settings read; None when there is none
    (row 207: "a set `HIITL_*` variable no setting reads is refused at construction, naming its replacement"). A
    variable set to the empty string carries no value and is not read."""
    families, read, earlier = tuple(families), frozenset(read), earlier or {}
    refused = []
    for name_set in sorted(name for name, value in environ.items() if value != ""):
        name = name_set.upper()
        family = next((f for f in families if name.startswith(f)), None)
        if family is None or name in read:
            continue
        if name in earlier:
            refused.append(f"{name_set} is a name an earlier release read; this release reads "
                           f"{earlier[name]}. Set {earlier[name]} instead, and unset {name_set}.")
        else:
            names = ", ".join(sorted(v for v in read if v.startswith(family)))
            refused.append(f"{name_set} is set, and no setting reads it. The {family}* variables a setting reads: "
                           f"{names}.")
    return "\n".join(refused) or None
