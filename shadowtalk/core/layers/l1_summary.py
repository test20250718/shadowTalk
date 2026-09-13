from shadowtalk.data.repositories import SummaryRepository
from shadowtalk.config.settings import Settings


def extract(friend_id: int) -> list[dict]:
    valid_days = Settings.get_int("summary_valid_days")
    summaries = SummaryRepository.get_valid_summaries(friend_id, valid_days)
    return [
        {"role": "system", "content": s["content"], "layer": "L1"}
        for s in summaries
    ]
