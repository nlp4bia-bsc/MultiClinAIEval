import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

REQUIRED_COLUMNS = ["filename", "label", "start_span", "end_span", "text"]


def load_and_validate_tsv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path} is missing columns {missing}. Required: {REQUIRED_COLUMNS}"
        )

    df = df[REQUIRED_COLUMNS].copy()

    df["start_span"] = pd.to_numeric(df["start_span"]).astype(int)
    df["end_span"] = pd.to_numeric(df["end_span"]).astype(int)

    if (df["end_span"] <= df["start_span"]).any():
        raise ValueError("Invalid spans detected (end_span <= start_span).")

    df = df.rename(
        columns={
            "start_span": "off0",
            "end_span": "off1",
            "text": "span",
        }
    )

    return df[["filename", "label", "off0", "off1", "span"]]


def group_by_document(df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:

    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for _, row in df.iterrows():
        grouped.setdefault(row["filename"], []).append(
            {
                "filename": row["filename"],
                "off0": int(row["off0"]),
                "off1": int(row["off1"]),
                "label": row["label"],
            }
        )

    return grouped


def safe_f1(tp: int, fp: int, fn: int):

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0

    if precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def strict_match(g, p):

    return (
        g["filename"] == p["filename"]
        and g["label"] == p["label"]
        and g["off0"] == p["off0"]
        and g["off1"] == p["off1"]
    )


def safe_prf(precision: float, recall: float):

    if precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }

def char_overlap_f1(g, p):

    if g["filename"] != p["filename"]:
        return 0.0

    if g["label"] != p["label"]:
        return 0.0

    inter = max(0, min(g["off1"], p["off1"]) - max(g["off0"], p["off0"]))

    if inter == 0:
        return 0.0

    gold_len = g["off1"] - g["off0"]
    pred_len = p["off1"] - p["off0"]

    recall = inter / gold_len
    precision = inter / pred_len

    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


def compute_strict_metric(gold_docs, pred_docs):

    tp = 0
    fp = 0
    fn = 0

    docs = set(gold_docs.keys()) | set(pred_docs.keys())

    for d in docs:

        gold = gold_docs.get(d, [])
        pred = pred_docs.get(d, [])

        matched_g = set()
        matched_p = set()

        for gi, g in enumerate(gold):

            for pi, p in enumerate(pred):

                if pi in matched_p:
                    continue

                if strict_match(g, p):
                    matched_g.add(gi)
                    matched_p.add(pi)
                    tp += 1
                    break

        fp += len(pred) - len(matched_p)
        fn += len(gold) - len(matched_g)

    return safe_f1(tp, fp, fn)

def compute_char_metric(gold_docs, pred_docs):

    docs = set(gold_docs.keys()) | set(pred_docs.keys())

    gold_scores = []
    pred_scores = []

    for d in docs:

        gold = gold_docs.get(d, [])
        pred = pred_docs.get(d, [])

        for g in gold:
            best_score = 0.0

            for p in pred:
                score = char_overlap_f1(g, p)
                if score > best_score:
                    best_score = score

            gold_scores.append(best_score)

        for p in pred:
            best_score = 0.0

            for g in gold:
                score = char_overlap_f1(g, p)
                if score > best_score:
                    best_score = score

            pred_scores.append(best_score)

    recall = sum(gold_scores) / len(gold_scores) if gold_scores else 0.0
    precision = sum(pred_scores) / len(pred_scores) if pred_scores else 0.0

    result = safe_prf(precision, recall)
    result["n_gold"] = len(gold_scores)
    result["n_pred"] = len(pred_scores)

    return result


def evaluate(reference_path: Path, pred_path: Path, entity=None):

    df_gold = load_and_validate_tsv(reference_path)
    df_pred = load_and_validate_tsv(pred_path)

    df_pred = df_pred.drop_duplicates(
        subset=["filename", "label", "off0", "off1"]
    )

    if entity:
        df_gold = df_gold[df_gold.label == entity]
        df_pred = df_pred[df_pred.label == entity]

    gold_docs = group_by_document(df_gold)
    pred_docs = group_by_document(df_pred)

    strict = compute_strict_metric(gold_docs, pred_docs)
    char_f1 = compute_char_metric(gold_docs, pred_docs)

    return {
        "entity": entity,
        "strict": strict,
        "char_f1": char_f1,
    }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--reference",
        type=Path,
        default=Path("assets/gold_standard.tsv"),
        help="Gold standard TSV",
    )

    parser.add_argument(
        "--pred",
        type=Path,
        required=True,
        help="Prediction TSV",
    )

    parser.add_argument(
        "--entity",
        type=str,
        default=None,
        help="Entity label to evaluate",
    )

    args = parser.parse_args()

    results = evaluate(
        reference_path=args.reference,
        pred_path=args.pred,
        entity=args.entity,
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()