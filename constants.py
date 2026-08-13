# -*- coding: utf-8 -*-
"""Local creative contracts used when the content plugin runs standalone."""
from __future__ import annotations

CREATIVE_STORY_BIBLE_TEMPLATE = {
    "mainline_direction": "",
    "active_themes": [],
    "resolved_threads": [],
    "unresolved_threads": [],
    "important_facts": [],
    "next_direction": "",
    "recent_keywords": [],
    "recent_outlines": [],
    "last_updated_chunk": 0,
}

CREATIVE_MEMORY_MAX_ENTRIES = 50
CREATIVE_SIMILARITY_THRESHOLD = 0.72
CREATIVE_SIMILARITY_RETRIES = 2
CREATIVE_REVIEW_MIN_SCORE = 7
CREATIVE_MAX_REVISION_HISTORY = 10
CREATIVE_FALLBACK_CHUNKS = [
    "角色把那句话写到一半,忽然停住。窗外的声音很轻,像有人把另一个世界折起来,塞进了玻璃杯底。",
    "角色把那个念头又往后推了一小步,像把一枚很轻的纸片压进书页里,等下次再翻开。",
    "笔尖在纸上停了一秒,又继续往下走。风从窗缝里挤进来,翻动了桌角的便签。",
    "角色忽然想到一个画面,远处的灯塔在雾里一闪一闪,像在给谁打暗号。",
    "这段话写了又删,删了又写。最后角色叹了口气,把手机屏幕朝下扣在桌上。",
]
CREATIVE_LEGACY_FALLBACK_CHUNKS = []
