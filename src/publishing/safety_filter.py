"""Sensitive content safety filter protecting personal brand reputation."""

import re
from typing import Dict, List, Optional
from src.contracts.enums import PostStatus
from src.contracts.schemas import GeneratedContent


class SafetyEvaluation:
    """Result of sensitive content risk evaluation."""

    def __init__(
        self,
        is_sensitive: bool,
        category: str,
        matched_keywords: Optional[List[str]] = None,
        severity: str = "CLEAN",
        reason: Optional[str] = None,
    ):
        self.is_sensitive = is_sensitive
        self.category = category
        self.matched_keywords = matched_keywords or []
        self.severity = severity
        self.reason = reason

    def __repr__(self) -> str:
        return f"<SafetyEvaluation is_sensitive={self.is_sensitive} category='{self.category}' severity='{self.severity}'>"


class SafetyFilter:
    """Heuristic classifier detecting controversial, political, military, malware, and legal risks."""

    # Categorized sensitive patterns
    CATEGORIES: Dict[str, List[str]] = {
        "military": [
            r"\bweapon(?:s|ized)?\b",
            r"\bautonomous weapons?\b",
            r"\bmilitary\b",
            r"\btactical strikes?\b",
            r"\bwarfare\b",
            r"\bdrones?\b",
            r"\bdefense ministry\b",
            r"\bdepartment of defense\b",
            r"\bair defense\b",
            r"\bmissile defense\b",
            r"\bcombat(?:\s+operations)?\b",
            r"\bmissiles?\b",
            r"\bwarheads?\b",
            r"\blethal autonomous\b",
            r"\bbattlefield\b",
            r"\barmed conflict\b",
        ],
        "politics": [
            r"\b(?:presidential|general|federal|parliamentary|midterm|state)\s+elections?\b",
            r"\belection\s+(?:day|fraud|interference|rigging|results?|turnout|campaign)\b",
            r"(?<!leader\s)(?<!raft\s)(?<!paxos\s)(?<!bully\s)\belections?\b",
            r"\bpresidential(?:\s+race)?\b",
            r"\bswing voters?\b",
            r"\bvoting machines?\b",
            r"\bballot fraud\b",
            r"\bpolitical campaign\b",
            r"\bgenerative ads\b",
            r"\bdeepfake candidate\b",
            r"\bdemocrats?\b",
            r"\brepublicans?\b",
            r"\bpartisan\b",
            r"\blending political\b",
        ],
        "malware": [
            r"\bzero[\s-]day\b",
            r"\bexploits?(?:\s+framework)?\b",
            r"\bweaponized payload\b",
            r"\bremote code execution\b",
            r"\bmalware\b",
            r"\bransom[\s-]?ware\b",
            r"\bcyber[\s-]?attacks?\b",
            r"\bbot[\s-]?nets?\b",
            r"\bc2 servers?\b",
        ],
        "defamation/legal": [
            r"\blawsuits?\b",
            r"\b(?:sues|suing)\b",
            r"\bcopyright piracy\b",
            r"\bcopyright infringement\b",
            r"\bclass action\b",
            r"\bsubpoenas?\b",
            r"\binfringement claims?\b",
            r"\billegal(?:ly)?\s+scrap(?:ing|ed)\b",
            r"\bdefamation\b",
            r"\bintellectual property theft\b",
            r"\bantitrust probe\b",
            r"\bsecurities fraud\b",
        ],
        "financial": [
            r"\bcrypto pump\b",
            r"\bprice predictions?\b",
            r"\btoken launch\b",
            r"\bfinancial advice\b",
            r"\bguaranteed returns?\b",
            r"\binsider trading\b",
            r"\bairdrop claim\b",
        ],
        "hate_speech": [
            r"\bhate speech\b",
            r"\bracial slurs?\b",
            r"\bdiscriminatory attacks?\b",
        ],
    }

    def __init__(self):
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {
            cat: [re.compile(p, re.IGNORECASE) for p in patterns]
            for cat, patterns in self.CATEGORIES.items()
        }

    def evaluate_text(self, text: str) -> SafetyEvaluation:
        """Scan input text against sensitive categories and return safety evaluation."""
        if not text:
            return SafetyEvaluation(is_sensitive=False, category="clean", severity="CLEAN")

        clean_text = text.strip()
        matched_cats: List[str] = []
        matched_words: List[str] = []

        for cat, patterns in self._compiled_patterns.items():
            for pat in patterns:
                match = pat.search(clean_text)
                if match:
                    if cat not in matched_cats:
                        matched_cats.append(cat)
                    matched_words.append(match.group(0))

        if matched_cats:
            primary_cat = matched_cats[0]
            severity = "HIGH" if primary_cat in ("malware", "defamation/legal", "hate_speech") else "MEDIUM"
            return SafetyEvaluation(
                is_sensitive=True,
                category=primary_cat,
                matched_keywords=matched_words,
                severity=severity,
                reason=f"Matched sensitive category '{primary_cat}': {', '.join(matched_words[:3])}",
            )

        return SafetyEvaluation(is_sensitive=False, category="clean", severity="CLEAN")

    def evaluate(self, content: GeneratedContent) -> SafetyEvaluation:
        """Evaluate a GeneratedContent contract object and set is_sensitive."""
        eval_res = self.evaluate_text(content.text)
        content.is_sensitive = eval_res.is_sensitive
        return eval_res

    def route_post_status(self, is_sensitive: bool) -> PostStatus:
        """Route job to AWAITING_APPROVAL if sensitive, else QUEUED."""
        return PostStatus.AWAITING_APPROVAL if is_sensitive else PostStatus.QUEUED
