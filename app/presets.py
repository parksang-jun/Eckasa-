"""장면 광고용 배경/모델 프리셋.

각 프리셋은 대시보드에서 고르는 한국어 라벨과, nano-banana(이미지 편집)에 넣을
영어 프롬프트 조각을 가진다. 가방 형태는 항상 '그대로 유지'하도록 scene.py 에서
공통 지시문을 덧붙인다.
"""
from __future__ import annotations

from typing import Dict, List

# ---------------------------- 배경 ----------------------------
BACKGROUNDS: Dict[str, Dict[str, str]] = {
    "europe_street": {
        "label": "유럽 거리 (파리/토스카나)",
        "prompt": (
            "on a charming European old-town street with a Paris and Tuscany vibe, "
            "cobblestone road, elegant cafe storefronts and warm stone buildings, "
            "soft golden-hour sunlight, cinematic editorial fashion atmosphere"
        ),
    },
    "santorini": {
        "label": "산토리니/그리스",
        "prompt": (
            "in Santorini Greece, whitewashed buildings with blue domes, bright "
            "Mediterranean sunlight, deep blue sea in the background, airy vacation vibe"
        ),
    },
    "bali_beach": {
        "label": "발리/열대 해변",
        "prompt": (
            "on a tropical Bali beach with palm trees, turquoise water and soft sunset "
            "light, relaxed summer holiday mood"
        ),
    },
    "morocco": {
        "label": "모로코/마라케시 마켓",
        "prompt": (
            "in a Moroccan Marrakech market, terracotta walls, colorful textiles and "
            "lanterns, warm exotic light, artistic travel-editorial mood"
        ),
    },
}

# ---------------------------- 모델 ----------------------------
MODELS: Dict[str, Dict[str, str]] = {
    "western_female": {
        "label": "서양 여성",
        "prompt": "a stylish Western European female fashion model in a chic daily outfit",
    },
    "asian_female": {
        "label": "한국/아시아 여성",
        "prompt": "a stylish Korean/Asian female fashion model in a chic daily outfit",
    },
    "male_unisex": {
        "label": "남성/유니섹스",
        "prompt": "a stylish model with a casual unisex daily outfit",
    },
    "no_model": {
        "label": "모델 없이 배경만",
        "prompt": "",  # 사람 없이 가방만 연출
    },
}

# 장면 다양성: 같은 가방을 여러 컷으로 (앞에서부터 scene_count 개 사용)
SCENE_VARIATIONS: List[str] = [
    "full-body shot, the model is walking and carrying the bag on the shoulder",
    "medium shot, close attention on the bag held in the hand",
    "the model is sitting at an outdoor cafe with the bag placed beside",
    "over-the-shoulder editorial shot featuring the bag",
]

# 모델 없이 배경만일 때의 컷 변형
SCENE_VARIATIONS_NO_MODEL: List[str] = [
    "the bag placed elegantly as the hero product in the scene, eye-level",
    "the bag on a surface with the scenery softly blurred behind",
    "a low-angle premium product shot of the bag in the scene",
    "the bag with natural props around it in the scene",
]


def background_choices() -> List[Dict[str, str]]:
    return [{"key": k, "label": v["label"]} for k, v in BACKGROUNDS.items()]


def model_choices() -> List[Dict[str, str]]:
    return [{"key": k, "label": v["label"]} for k, v in MODELS.items()]


def get_background(key: str) -> Dict[str, str]:
    return BACKGROUNDS.get(key, BACKGROUNDS["europe_street"])


def get_model(key: str) -> Dict[str, str]:
    return MODELS.get(key, MODELS["western_female"])
