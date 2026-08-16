"""Deterministic rule-based query classifier.

Assigns one of thirteen QueryClass values by matching compiled regex patterns
in priority order. The first match wins; DIRECT is the fallback. Classification
is synchronous and stateless — no model calls, no database access.
"""

from __future__ import annotations

import re

from app.domain.enums import QueryClass

# Evaluated in order; the first matching pattern determines the class.
# Place more specific signals before broader ones to avoid false matches.
_RULES: list[tuple[re.Pattern[str], QueryClass]] = [
    (
        # Quoted strings, definition requests, and labelled items are exact-term
        # signals: the student knows the precise phrase and wants it located or
        # defined verbatim rather than paraphrased.
        re.compile(
            r"""(?xi)
            (?:
                [\"'].+?[\"']
              | \bdefin(?:e|ition\s+of)\b
              | \bwhat\s+does\s+.+?\s+mean\b
              | \bexact\s+(?:quote|wording|text|phrase)\b
              | \bverbatim\b
              | \b(?:equation|theorem|lemma|corollary|definition|formula|proposition)
                \s+\d[\w.]*\b
            )
            """,
        ),
        QueryClass.EXACT_TERM,
    ),
    (
        re.compile(
            r"\b(?:table\s+\d[\w.]*"
            r"|in\s+the\s+table|from\s+the\s+table"
            r"|the\s+table\s+(?:on|above|below|shows?)"
            r"|rows?\s+(?:in|of|from)\s+the\s+table"
            r"|columns?\s+(?:in|of|from)\s+the\s+table"
            r"|tabular\s+(?:data|format))\b",
            re.IGNORECASE,
        ),
        QueryClass.TABLE,
    ),
    (
        re.compile(
            r"\b(?:fig(?:ure)?\s*\d[\w.]*"
            r"|diagram|flowchart"
            r"|chart\b|plot\b"
            r"|the\s+(?:figure|image|graph)\s+(?:on|above|below|shows?)"
            r"|visuali[sz]ation\b)\b",
            re.IGNORECASE,
        ),
        QueryClass.VISUAL,
    ),
    (
        re.compile(
            r"\b(?:quiz(?:\s+me)?"
            r"|test\s+me\b"
            r"|practice\s+(?:problems?|questions?)"
            r"|generate\s+(?:\w+\s+)?questions?"
            r"|create\s+(?:a\s+)?(?:quiz|test)"
            r"|sample\s+questions?"
            r"|make\s+(?:a\s+)?quiz"
            r"|give\s+me\s+(?:some\s+)?questions?\s+(?:on|about))\b",
            re.IGNORECASE,
        ),
        QueryClass.QUIZ_GENERATION,
    ),
    (
        re.compile(
            r"\b(?:summarize|summarise"
            r"|give\s+(?:me\s+)?(?:a\s+)?(?:summary|overview)\s+of"
            r"|key\s+(?:points?|takeaways?|ideas?)"
            r"|main\s+(?:points?|ideas?|themes?|topics?)"
            r"|what\s+(?:is|are)\s+the\s+main"
            r"|outline\s+(?:of|the)"
            r"|recap\s+of|overview\s+of)\b",
            re.IGNORECASE,
        ),
        QueryClass.SUMMARY,
    ),
    (
        re.compile(
            r"\b(?:concept\s+map|mind\s+map"
            r"|map\s+out\s+(?:all\s+)?(?:the\s+)?concepts?"
            r"|how\s+(?:\w+\s+){0,2}(?:everything|it\s+all)\s+fits?\s+together"
            r"|big[\s-]picture\s+overview"
            r"|comprehensive\s+overview\s+of\s+all"
            r"|all\s+the\s+concepts?\s+in)\b",
            re.IGNORECASE,
        ),
        QueryClass.CONCEPT_MAP,
    ),
    (
        re.compile(
            r"\b(?:compar(?:e|ing|ison)"
            r"|versus\b|vs\.?\s"
            r"|differences?\s+between"
            r"|how\s+(?:do(?:es)?|is|are)\s+\w+(?:\s+\w+){0,4}\s+differ\b"
            r"|contrast\s+\w+(?:\s+\w+){0,4}\s+(?:and|with|versus)\b"
            r"|similarities?\s+(?:and\s+differences?\s+)?between"
            r"|distinguish\s+between)\b",
            re.IGNORECASE,
        ),
        QueryClass.COMPARISON,
    ),
    (
        re.compile(
            r"\b(?:how\s+many\b|how\s+much\b"
            r"|total\s+(?:number\s+)?of\b"
            r"|list\s+all\s+(?:the\s+)?"
            r"|all\s+(?:the\s+)?(?:types?|kinds?|categories|methods?|approaches?|examples?|cases?)\s+of\b"
            r"|count\s+(?:the\s+|of\s+)?"
            r"|sum\s+of\b)\b",
            re.IGNORECASE,
        ),
        QueryClass.AGGREGATION,
    ),
    (
        re.compile(
            r"\b(?:across\s+(?:all\s+)?(?:the\s+)?(?:documents?|papers?|chapters?|files?|sources?)"
            r"|in\s+(?:all|multiple|several)\s+(?:documents?|papers?|sources?)"
            r"|multiple\s+(?:documents?|papers?|sources?))\b",
            re.IGNORECASE,
        ),
        QueryClass.MULTI_DOCUMENT,
    ),
    (
        re.compile(
            r"\b(?:if\s+.{3,}?\bthen\b"
            r"|given\s+that\s+.{3,}?,\s*(?:what|how|why)"
            r"|trace\s+(?:through|the\s+steps?)"
            r"|chain\s+of\s+(?:reasoning|events?|steps?|consequences?)"
            r"|how\s+would\s+\w+(?:\s+\w+){0,6}\s+lead\s+to"
            r"|derive\s+(?:the|an?)\s+\w+\s+(?:from|using|for))\b",
            re.IGNORECASE,
        ),
        QueryClass.MULTI_HOP,
    ),
    (
        re.compile(
            r"\b(?:(?:what|describe)\s+(?:is|are)\s+the\s+relationship\s+between"
            r"|how\s+(?:is|are|does|do)\s+\w+(?:\s+\w+){0,4}\s+"
            r"(?:relate(?:d)?\s+to|affect\b|influence\b|impact\b|connect(?:ed)?\s+to|depend(?:s)?\s+on)"
            r"|connection\s+between"
            r"|what\s+links\b"
            r"|role\s+of\s+\w+(?:\s+\w+){0,4}\s+in)\b",
            re.IGNORECASE,
        ),
        QueryClass.RELATIONSHIP,
    ),
    (
        re.compile(
            r"\b(?:prerequisites?\b"
            r"|before\s+(?:I\s+can|learning|studying|understanding)\s+\w"
            r"|what\s+(?:do\s+I|should\s+I)\s+(?:need\s+to\s+know|understand)\s+(?:first|before)"
            r"|background\s+knowledge\b"
            r"|background\s+(?:needed|required)\s+(?:for|to)"
            r"|foundational\s+(?:knowledge|concepts?))\b",
            re.IGNORECASE,
        ),
        QueryClass.PREREQUISITE,
    ),
]


class QueryClassifier:
    """Classify a natural-language query into one of thirteen QueryClass values.

    Rules run in priority order; the first matching rule determines the class.
    Queries that match no rule are classified as DIRECT.
    """

    def classify(self, query: str) -> QueryClass:
        for pattern, query_class in _RULES:
            if pattern.search(query):
                return query_class
        return QueryClass.DIRECT
