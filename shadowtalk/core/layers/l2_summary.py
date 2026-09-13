from shadowtalk.data.repositories import SummaryRepository


def extract(friend_id: int) -> list[dict]:
    summaries = SummaryRepository.get_all_high_level_summaries(friend_id)
    return [
        {"role": "system", "content": s["content"], "layer": "L2"}
        for s in summaries
    ]
