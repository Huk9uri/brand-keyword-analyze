from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class DailyEstimate:
    search_date: date
    ratio: float
    estimated_pc: int
    estimated_mobile: int
    estimated_total: int

    def to_dict(self) -> dict:
        data = asdict(self)
        data["search_date"] = self.search_date.isoformat()
        return data
