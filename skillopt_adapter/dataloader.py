"""SkillOptDataLoader — loads benchmark tasks from HuggingFace for SkillOpt training.

Supports multiple benchmarks via ``dataset_name`` parameter:
  - ``litble/Multi-Docker-Eval`` (MDE, default)
  - ``ernie-research/MEnvBench`` (MEnvBench)

Uses deterministic splits (by instance_id hash or pre-computed split file),
and returns :class:`~skillopt.datasets.base.BatchSpec` batches.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from typing import Any

from datasets import load_dataset
from skillopt.datasets.base import BaseDataLoader, BatchSpec


class SkillOptDataLoader(BaseDataLoader):
    """Generic dataloader for SkillOpt that loads from a HuggingFace dataset."""

    def __init__(
        self,
        dataset_name: str = "litble/Multi-Docker-Eval",
        split_path: str = "",
        train_size: int = 20,
        val_size: int = 5,
        test_size: int = 5,
        seed: int = 42,
        limit: int = 0,
        language_filter: str | None = None,
    ) -> None:
        self.dataset_name = dataset_name
        self.split_path = split_path
        self.train_size = train_size
        self.val_size = val_size
        self.test_size = test_size
        self.seed = seed
        self.limit = limit
        self.language_filter = language_filter

        self.train_items: list[dict[str, Any]] = []
        self.val_items: list[dict[str, Any]] = []
        self.test_items: list[dict[str, Any]] = []

    def setup(self, cfg: dict) -> None:
        # cfg is a flat dict from flatten_config()
        ds_name = cfg.get("dataset_name", self.dataset_name)
        lang_filter = cfg.get("language_filter", self.language_filter)

        split_name = "test" if ds_name == "litble/Multi-Docker-Eval" else "train"
        ds = load_dataset(ds_name, split=split_name)
        id_to_item: dict[str, dict] = {}
        for ex in ds:
            d = dict(ex)
            iid = d.get("instance_id", "")
            if lang_filter and d.get("language", "") != lang_filter:
                continue
            if iid:
                id_to_item[iid] = d

        print(f"[DataLoader] Loaded {len(id_to_item)} items from {ds_name}"
              f"{' (filter: ' + lang_filter + ')' if lang_filter else ''}")

        if self.split_path and os.path.exists(self.split_path):
            with open(self.split_path) as f:
                split = json.load(f)
            train_ids = split.get("train", [])[: self.train_size] if self.train_size else split.get("train", [])
            val_ids = split.get("val", [])[: self.val_size] if self.val_size else split.get("val", [])
            test_ids = split.get("test", [])[: self.test_size] if self.test_size else split.get("test", [])
        else:
            train_ids, val_ids, test_ids = self._compute_split(list(id_to_item.keys()))

        self.train_items = [id_to_item[iid] for iid in train_ids if iid in id_to_item]
        self.val_items = [id_to_item[iid] for iid in val_ids if iid in id_to_item]
        self.test_items = [id_to_item[iid] for iid in test_ids if iid in id_to_item]

        missing_train = [iid for iid in train_ids if iid not in id_to_item]
        if missing_train:
            print(f"  [WARN] {len(missing_train)} train IDs not found in dataset")

        print(f"  {len(self.train_items)} train, {len(self.val_items)} val, {len(self.test_items)} test")

    def _compute_split(self, all_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
        hashed = [(hashlib.md5(iid.encode()).hexdigest(), iid) for iid in all_ids]
        hashed.sort(key=lambda x: x[0])
        sorted_ids = [h[1] for h in hashed]
        n = len(sorted_ids)
        n_train = int(n * 0.6)
        n_val = int(n * 0.15)
        train = sorted_ids[:n_train]
        val = sorted_ids[n_train : n_train + n_val]
        test = sorted_ids[n_train + n_val :]
        if self.train_size > 0:
            train = train[: self.train_size]
        if self.val_size > 0:
            val = val[: self.val_size]
        if self.test_size > 0:
            test = test[: self.test_size]
        return train, val, test

    def build_train_batch(self, batch_size: int, seed: int, **kwargs) -> BatchSpec:
        n = min(batch_size, len(self.train_items)) if batch_size > 0 else len(self.train_items)
        items = random.Random(seed).sample(self.train_items, n)
        return BatchSpec(phase="train", split="train", seed=seed, batch_size=n, payload=items)

    def build_eval_batch(self, env_num: int, split: str, seed: int, **kwargs) -> BatchSpec:
        pool = self.val_items if "valid" in split else self.test_items
        n = min(env_num, len(pool)) if env_num > 0 else len(pool)
        items = random.Random(seed).sample(pool, n)
        return BatchSpec(phase="eval", split=split, seed=seed, batch_size=n, payload=items)
