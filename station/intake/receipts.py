from dataclasses import dataclass

from station.acquisition.probe import RawReading


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    receipt_id: int
    raw: RawReading

    def matches(self, reading: RawReading) -> bool:
        return self.raw == reading


def receipt_from_admission(receipt_id: int, raw: RawReading) -> AdmissionReceipt:
    return AdmissionReceipt(receipt_id, raw)
