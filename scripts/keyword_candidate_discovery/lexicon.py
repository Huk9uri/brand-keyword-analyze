from __future__ import annotations

from .models import TermCategory


# Ordered for deterministic evidence and test output.
TERM_PATTERNS: tuple[tuple[tuple[str, ...], str, TermCategory], ...] = (
    (("설렁탕",), "설렁탕", TermCategory.MENU),
    (("순대국", "순댓국"), "순대국", TermCategory.MENU),
    (("국밥",), "국밥", TermCategory.MENU),
    (("수육",), "수육", TermCategory.MENU),
    (("도가니탕",), "도가니탕", TermCategory.MENU),
    (("혼밥", "혼자 먹", "혼자서 먹"), "혼밥", TermCategory.DINING_CONTEXT),
    (("직장인 점심",), "직장인 점심", TermCategory.DINING_CONTEXT),
    (("빠른 점심", "빨리 나", "금방 나"), "빠른 점심", TermCategory.DINING_CONTEXT),
    (("회식",), "회식", TermCategory.DINING_CONTEXT),
    (("해장",), "해장", TermCategory.VISIT_PURPOSE),
    (("보양식", "몸보신"), "보양식", TermCategory.VISIT_PURPOSE),
    (("든든한 한 끼", "든든한 한끼", "든든해"), "든든한 한 끼", TermCategory.VISIT_PURPOSE),
    (("24시간", "24 시간"), "24시간", TermCategory.SERVICE_ATTRIBUTE),
    (("단체식사", "단체 식사"), "단체식사", TermCategory.SERVICE_ATTRIBUTE),
    (("포장",), "포장", TermCategory.SERVICE_ATTRIBUTE),
    (("진한 국물", "국물이 진"), "진한 국물", TermCategory.FOOD_ATTRIBUTE),
    (("맑은 국물", "국물이 맑"), "맑은 국물", TermCategory.FOOD_ATTRIBUTE),
    (("푸짐한 고기", "고기가 많"), "푸짐한 고기", TermCategory.FOOD_ATTRIBUTE),
    (("밀키트",), "밀키트", TermCategory.NON_VISIT_INTENT),
    (("택배",), "택배", TermCategory.NON_VISIT_INTENT),
    (("조리법", "레시피"), "레시피", TermCategory.NON_VISIT_INTENT),
)

