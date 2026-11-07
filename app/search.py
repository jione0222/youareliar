"""AI 검색: 세 가지 방법으로 찾은 순위를 합쳐서(RRF) 최종 순서를 정한다.

1. 사진 벡터 (A, SigLIP 2): 검색 문장과 '사진'의 뜻이 가까운 순서
2. 설명 벡터 (B, KURE-v1): 검색 문장과 'Claude가 쓴 설명'의 뜻이 가까운 순서
3. 키워드: 검색 문장의 글자가 설명·메모·장소에 직접 많이 들어 있는 순서

합치는 법 (RRF, Reciprocal Rank Fusion)
- 각 방법에서 받은 등수로 점수를 준다: 비중 / (60 + 등수). 1등일수록 점수가 크다.
- 세 방법의 점수를 더해서 큰 순서대로 보여 준다.
- 점수(유사도)는 방법마다 크기가 제각각이라 바로 더할 수 없지만, '등수'는 공평하게 비교할 수 있다.

비중은 한국어 시험(검색 문장 62개)에서 설명 벡터가 가장 정확했고(1등 96.8%),
키워드는 비중을 0.5로 낮췄을 때 정확도를 떨어뜨리지 않았던 결과를 따랐다.
사진 벡터 비중은 실제 물건 사진으로 정확도 시험을 해서 다시 정한다.
"""
from collections import defaultdict

from . import config, db, describe, embedding

RRF_K = 60
WEIGHTS = {"image": 1.0, "description": 1.0, "keyword": 0.5}
CANDIDATES = 50  # 방법마다 상위 몇 개까지 후보로 볼지


def _bigrams(text: str) -> set[str]:
    """글을 두 글자씩 쪼갠다. 예: '텀블러를' → {'텀블', '블러', '러를'}
    한국어는 '텀블러를', '텀블러가'처럼 뒤에 붙는 말이 바뀌어도 두 글자 조각은 대부분 겹친다."""
    pieces = set()
    for word in text.replace(",", " ").replace("/", " ").replace(".", " ").split():
        pieces |= {word} if len(word) < 2 else {word[i : i + 2] for i in range(len(word) - 1)}
    return pieces


def _keyword_ranking(query: str) -> list[int]:
    """검색 문장의 두 글자 조각이 물건 글에 몇 %나 들어 있는지로 순서를 매긴다."""
    query_pieces = _bigrams(query)
    if not query_pieces:
        return []
    scored = []
    for row in db.keyword_rows():
        text = " ".join(
            [
                describe.document_for_search(row["ai_info"] or {}, row["memo"]),
                row["found_place"] or "",
                row["storage_place"] or "",
            ]
        )
        score = len(query_pieces & _bigrams(text)) / len(query_pieces)
        if score > 0:
            scored.append((score, row["id"]))
    scored.sort(reverse=True)
    return [item_id for _, item_id in scored[:CANDIDATES]]


def search(query: str, limit: int = 20) -> list[dict]:
    """검색 문장으로 물건을 찾아, 비슷한 순서대로 카드 정보를 돌려준다.
    각 결과에는 방법별 등수(ranks)도 붙여 둔다. 예: {"image": 2, "description": 1}"""
    rankings: dict[str, list[int]] = {}

    image_hits = db.search_by_vector(embedding.embed_text(query), config.EMBED_MODEL, "image", CANDIDATES)
    rankings["image"] = [row["id"] for row in image_hits]

    if embedding.text_status() == "ready":
        description_hits = db.search_by_vector(
            embedding.embed_description(query), config.TEXT_EMBED_MODEL, "description", CANDIDATES
        )
        rankings["description"] = [row["id"] for row in description_hits]

    rankings["keyword"] = _keyword_ranking(query)

    # RRF로 합치기
    scores: dict[int, float] = defaultdict(float)
    ranks: dict[int, dict] = defaultdict(dict)
    for method, item_ids in rankings.items():
        for rank, item_id in enumerate(item_ids, start=1):
            scores[item_id] += WEIGHTS[method] / (RRF_K + rank)
            ranks[item_id][method] = rank

    top_ids = sorted(scores, key=scores.get, reverse=True)[:limit]
    items = db.items_by_ids(top_ids)
    results = []
    for item_id in top_ids:
        if item_id in items:  # 그 사이 숨겨진 물건은 뺀다
            item = items[item_id]
            item["ranks"] = ranks[item_id]
            results.append(item)
    return results
