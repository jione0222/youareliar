"""정확도 시험: 실제 물건 사진과 검색 문장으로 검색 방법별 정답률을 잰다 (개발 순서 3단계).

준비물 (README의 '정확도 시험' 참고)
  eval/photos/01.jpg, 02.jpg …   물건 사진 (물건 하나에 한 장)
  eval/queries.csv                칸 3개: 사진, 메모, 검색 문장
    - 사진: 파일 이름 (예: 01.jpg)
    - 메모: 물건을 주운 사람이 등록할 때 쓸 법한 짧은 설명 (예: 파란 텀블러).
            AI 없는 '단순 키워드 검색'은 이 메모만 보고 찾는다.
    - 검색 문장: 물건 주인이 사진을 보지 않고, 잃어버렸다고 생각하며 쓴 문장. 한 줄에 하나.
    같은 사진에 검색 문장이 여러 개면 줄을 여러 개 쓴다(메모는 그 사진의 첫 줄에만 써도 된다).

실행
  python -m app.evaluate               키워드·A·B·합치기·재순위 전부 (Claude 사용, 시작 전에 비용을 묻는다)
  python -m app.evaluate --no-claude   Claude 없이: 단순 키워드와 A(사진)만
  python -m app.evaluate --no-rerank   재순위만 빼고

결과
  화면에 표가 나오고, eval/results/ 에 자세한 결과(마크다운, CSV)를 저장한다.
  Claude 답은 eval/cache/ 에 저장해 두고 다시 쓰므로, 같은 자료로 다시 돌리면 사용료가 거의 안 든다.
  모델을 비교하려면 .env의 CLAUDE_MODEL(또는 CLAUDE_RERANK_MODEL)을 바꿔서 한 번 더 돌린다.
"""
import argparse
import csv
import hashlib
import json
import logging
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from . import config, describe, embedding, images, rerank, search

log = logging.getLogger("evaluate")

COLUMNS = {  # 표의 칸 이름(한국어·영어 둘 다 받는다)
    "사진": "photo", "photo": "photo",
    "메모": "memo", "memo": "memo",
    "검색 문장": "query", "검색문장": "query", "query": "query",
}

METHODS = [  # (열쇠, 화면에 보일 이름)
    ("memo_keyword", "단순 키워드 검색 (주운 사람 메모만, AI 없음)"),
    ("image", "A: 사진 벡터 (SigLIP 2)"),
    ("description", "B: Claude 설명 벡터 (KURE-v1)"),
    ("keyword", "키워드 (Claude 설명 + 메모)"),
    ("fused", "A+B 합치기 (지금 검색 1단계)"),
    ("reranked", "A+B + Claude 재순위 (최종)"),
]


# ---------- 자료 읽기 ----------


def read_rows(csv_path: Path) -> list[dict]:
    """CSV를 읽는다. 구글 시트(UTF-8)와 한국어 엑셀(cp949)에서 저장한 파일을 둘 다 받는다."""
    raw = csv_path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit(f"{csv_path}의 글자 방식을 읽지 못했어요. 구글 시트에서 'CSV'로 다시 내려받아 주세요.")
    reader = csv.DictReader(text.splitlines())
    names = {name: COLUMNS.get(name.strip()) for name in reader.fieldnames or []}
    if "photo" not in names.values() or "query" not in names.values():
        sys.exit("표 첫 줄에 '사진'과 '검색 문장' 칸이 있어야 해요. (선택: '메모')")
    rows = []
    for row in reader:
        clean = {names[k]: (v or "").strip() for k, v in row.items() if k in names and names[k]}
        if clean.get("photo"):
            rows.append(clean)
    return rows


def load_dataset(data_dir: Path):
    """→ items: [{id, file, memo, photo_jpeg}], queries: [(검색 문장, 정답 번호)]"""
    rows = read_rows(data_dir / "queries.csv")
    items, by_file, queries = [], {}, []
    for row in rows:
        name = row["photo"]
        if name not in by_file:
            path = data_dir / "photos" / name
            if not path.exists():
                print(f"  ! 사진 파일이 없어서 건너뛰어요: {path}")
                by_file[name] = None
                continue
            photo_jpeg, _ = images.prepare(path.read_bytes())  # 사이트에 등록할 때와 똑같이 줄인다
            item = {"id": len(items) + 1, "file": name, "memo": row.get("memo", ""), "photo_jpeg": photo_jpeg}
            items.append(item)
            by_file[name] = item
        item = by_file[name]
        if item is None:
            continue
        if not item["memo"] and row.get("memo"):
            item["memo"] = row["memo"]
        if row.get("query"):
            queries.append((row["query"], item["id"]))
    return items, queries


# ---------- Claude 답 저장해 두기 (같은 자료로 다시 돌릴 때 사용료 아끼기) ----------


class JsonCache:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def _key(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


# ---------- 순위 계산 ----------


def order_by_similarity(query_vector: np.ndarray, matrix: np.ndarray, ids: list[int]) -> list[int]:
    """코사인 유사도가 큰 순서대로 번호를 줄 세운다(벡터 길이가 1이라 곱이 곧 유사도)."""
    similarities = matrix @ query_vector
    return [ids[i] for i in np.argsort(-similarities)]


def rank_of(order: list[int], answer: int) -> int | None:
    """정답이 몇 등인지. 아예 못 찾았으면 None."""
    return order.index(answer) + 1 if answer in order else None


def summarize(ranks: list[int | None]) -> dict:
    n = len(ranks)
    return {
        "top1": sum(1 for r in ranks if r == 1) / n,
        "top5": sum(1 for r in ranks if r is not None and r <= 5) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
    }


# ---------- 시험 ----------


def main() -> None:
    parser = argparse.ArgumentParser(description="검색 방법별 정답률 시험")
    parser.add_argument("--data", default="eval", help="시험 자료 폴더 (기본: eval)")
    parser.add_argument("--no-claude", action="store_true", help="Claude 없이 단순 키워드와 A만")
    parser.add_argument("--no-rerank", action="store_true", help="재순위만 빼기")
    parser.add_argument("--yes", action="store_true", help="비용 확인 질문 건너뛰기")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    data_dir = Path(args.data)
    if not (data_dir / "queries.csv").exists():
        sys.exit(f"{data_dir / 'queries.csv'} 파일이 없어요. README의 '정확도 시험'을 보고 준비해 주세요.")
    items, queries = load_dataset(data_dir)
    if len(items) < 2 or not queries:
        sys.exit("물건이 2개 이상, 검색 문장이 1개 이상 있어야 해요.")
    ids = [item["id"] for item in items]
    by_id = {item["id"]: item for item in items}
    print(f"물건 {len(items)}개, 검색 문장 {len(queries)}개로 시험해요.")

    use_claude = not args.no_claude and describe.enabled()
    use_rerank = use_claude and not args.no_rerank
    if not args.no_claude and not describe.enabled():
        print("  (.env에 Claude 키가 없어서 Claude가 필요한 시험은 건너뛰어요.)")

    desc_cache = JsonCache(data_dir / "cache" / "descriptions.json")
    rerank_cache = JsonCache(data_dir / "cache" / "rerank.json")
    if use_claude:
        todo = sum(1 for it in items if desc_cache.get(_key(config.CLAUDE_MODEL, hashlib.sha256(it["photo_jpeg"]).hexdigest(), it["memo"])) is None)
        calls = todo + (len(queries) if use_rerank else 0)
        print(f"Claude를 최대 {calls}번 불러요 (사진 정리 {todo}번 + 재순위 최대 {len(queries) if use_rerank else 0}번, 저장해 둔 답은 다시 안 불러요).")
        print("  상위 모델이면 1번에 대략 40원, 저가 모델이면 1~2원쯤이에요.")
        if not args.yes and input("계속할까요? (y/n) ").strip().lower() not in ("y", "yes", "ㅛ"):
            sys.exit("멈췄어요.")

    # 1) A: 사진 벡터
    print("1) 사진 벡터 만드는 중…")
    image_matrix = np.vstack(
        [embedding.embed_image(Image.open(BytesIO(item["photo_jpeg"]))) for item in items]
    )
    query_image_vectors = [embedding.embed_text(q) for q, _ in queries]

    # 2) B: Claude 설명 + 설명 벡터
    infos: dict[int, dict] = {}
    if use_claude:
        print("2) Claude가 사진 정리하는 중…")
        for item in items:
            key = _key(config.CLAUDE_MODEL, hashlib.sha256(item["photo_jpeg"]).hexdigest(), item["memo"])
            info = desc_cache.get(key)
            if info is None:
                try:
                    info = describe.describe_photo(item["photo_jpeg"], item["memo"] or None).model_dump()
                    desc_cache.put(key, info)
                except Exception as error:  # 하나가 실패해도 시험은 계속한다
                    print(f"  ! {item['file']} 정리 실패: {error}")
                    continue
            infos[item["id"]] = info
        described_ids = list(infos)
        description_matrix = (
            np.vstack([embedding.embed_description(describe.document_for_search(infos[i], by_id[i]["memo"])) for i in described_ids])
            if described_ids else None
        )

    # 3) 검색 문장마다 방법별 순위 매기기
    print("3) 검색 문장마다 순위 매기는 중…")
    memo_texts = {item["id"]: item["memo"] for item in items if item["memo"]}
    ai_texts = {item["id"]: search.keyword_text(infos.get(item["id"]), item["memo"]) for item in items}
    results = []  # 검색 문장마다 {query, answer, ranks: {방법: 등수}, orders: {방법: 순서}}
    for (query, answer), query_image_vector in zip(queries, query_image_vectors):
        orders = {"image": order_by_similarity(query_image_vector, image_matrix, ids)}
        if memo_texts:
            orders["memo_keyword"] = search.keyword_ranking(query, memo_texts, limit=len(items))
        if use_claude:
            if description_matrix is not None:
                orders["description"] = order_by_similarity(embedding.embed_description(query), description_matrix, described_ids)
            orders["keyword"] = search.keyword_ranking(query, ai_texts, limit=len(items))
            parts = {m: orders[m][: search.CANDIDATES] for m in ("image", "description", "keyword") if m in orders}
            orders["fused"], _ = search.fuse(parts)
            if use_rerank:
                top = orders["fused"][: rerank.MAX_CANDIDATES]
                candidates = [
                    {"id": i, "ai_info": infos.get(i), "memo": by_id[i]["memo"], "found_place": None, "found_date": None}
                    for i in top
                ]
                key = _key(rerank.model_name(), query, json.dumps(candidates, ensure_ascii=False, sort_keys=True))
                ranking = rerank_cache.get(key)
                if ranking is None:
                    try:
                        ranking = rerank.ask_claude(query, candidates)
                        rerank_cache.put(key, ranking)
                    except Exception as error:
                        print(f"  ! '{query}' 재순위 실패: {error}")
                        ranking = [{"id": i} for i in top]
                reranked = [entry["id"] for entry in ranking]
                orders["reranked"] = reranked + [i for i in orders["fused"] if i not in reranked]
        results.append(
            {"query": query, "answer": answer, "orders": orders,
             "ranks": {method: rank_of(order, answer) for method, order in orders.items()}}
        )

    # 4) 정답률 표
    summary = {}
    for method, label in METHODS:
        method_ranks = [r["ranks"][method] for r in results if method in r["ranks"]]
        if method_ranks:
            summary[method] = summarize(method_ranks)
    print()
    print(f"{'방법':<42} {'1등 정답률':>9} {'5등 안':>7} {'MRR':>6}")
    for method, label in METHODS:
        if method in summary:
            s = summary[method]
            print(f"{label:<42} {s['top1']*100:8.1f}% {s['top5']*100:6.1f}% {s['mrr']:6.3f}")
    print("  (MRR: 정답이 1등이면 1점, 2등이면 0.5점, 3등이면 0.33점… 의 평균. 1에 가까울수록 좋아요.)")

    # 5) 합치는 비중 찾아보기 (사진 비중 × 키워드 비중, 설명 비중은 1로 고정)
    sweep = []
    if use_claude:
        for w_image in (0.0, 0.5, 1.0, 1.5):
            for w_keyword in (0.0, 0.5, 1.0):
                weights = {"image": w_image, "description": 1.0, "keyword": w_keyword}
                ranks = []
                for r in results:
                    parts = {m: r["orders"][m][: search.CANDIDATES] for m in ("image", "description", "keyword") if m in r["orders"]}
                    ranks.append(rank_of(search.fuse(parts, weights)[0], r["answer"]))
                sweep.append((w_image, w_keyword, summarize(ranks)))
        sweep.sort(key=lambda row: (-row[2]["top1"], -row[2]["mrr"]))
        print()
        print("합치는 비중 찾아보기 (설명 비중 1 고정, 좋은 순서 위 5개):")
        for w_image, w_keyword, s in sweep[:5]:
            now = "  ← 지금 설정" if (w_image, w_keyword) == (search.WEIGHTS["image"], search.WEIGHTS["keyword"]) else ""
            print(f"  사진 {w_image:<3} · 키워드 {w_keyword:<3} → 1등 {s['top1']*100:5.1f}%  MRR {s['mrr']:.3f}{now}")

    save_report(data_dir, items, results, summary, sweep, use_claude)


def save_report(data_dir, items, results, summary, sweep, use_claude) -> None:
    """eval/results/ 에 결과를 저장한다: 발표용 마크다운 + 엑셀로 열 수 있는 CSV."""
    out = data_dir / "results"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    files = {item["id"]: item["file"] for item in items}
    used = [(m, label) for m, label in METHODS if m in summary]

    lines = [
        f"# 정확도 시험 결과 ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f"- 물건 {len(items)}개, 검색 문장 {len(results)}개",
        f"- Claude 모델: {config.CLAUDE_MODEL or '사용 안 함'}" + (f" (재순위: {rerank.model_name()})" if use_claude else ""),
        f"- 사진 모델: {config.EMBED_MODEL}, 설명 모델: {config.TEXT_EMBED_MODEL if use_claude else '사용 안 함'}",
        "",
        "## 방법별 정답률",
        "",
        "| 방법 | 1등 정답률 | 5등 안 | MRR |",
        "|---|---|---|---|",
    ]
    lines += [f"| {label} | {summary[m]['top1']*100:.1f}% | {summary[m]['top5']*100:.1f}% | {summary[m]['mrr']:.3f} |" for m, label in used]
    if sweep:
        lines += ["", "## 합치는 비중 (설명 비중 1 고정)", "", "| 사진 | 키워드 | 1등 정답률 | MRR |", "|---|---|---|---|"]
        lines += [f"| {wi} | {wk} | {s['top1']*100:.1f}% | {s['mrr']:.3f} |" for wi, wk, s in sweep]
    lines += ["", "## 검색 문장별 정답 등수 (- 는 못 찾음)", "", "| 검색 문장 | 정답 사진 | " + " | ".join(label.split(" (")[0] for _, label in used) + " |",
              "|---|---|" + "---|" * len(used)]
    for r in results:
        cells = [str(r["ranks"].get(m) or "-") for m, _ in used]
        lines.append(f"| {r['query']} | {files[r['answer']]} | " + " | ".join(cells) + " |")
    md_path = out / f"결과-{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    csv_path = out / f"결과-{stamp}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: 엑셀에서 한글이 안 깨지게
        writer = csv.writer(f)
        writer.writerow(["검색 문장", "정답 사진"] + [label for _, label in used])
        for r in results:
            writer.writerow([r["query"], files[r["answer"]]] + [r["ranks"].get(m) or "" for m, _ in used])
    print()
    print(f"자세한 결과를 저장했어요: {md_path}  /  {csv_path}")


if __name__ == "__main__":
    main()
