from dataclasses import dataclass


def validate_probe_id(probe_id: str) -> str:
    if not isinstance(probe_id, str) or not probe_id.strip():
        raise ValueError('probe_id must be a nonblank string')
    return probe_id


@dataclass(frozen=True, slots=True)
class ProbeIdentity:
    probe_id: str

    def __post_init__(self) -> None:
        validate_probe_id(self.probe_id)
