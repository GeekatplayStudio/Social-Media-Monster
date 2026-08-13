"""Article analysis: core-point extraction and article-grounded visual briefs."""
import pytest

from src.core.article_analysis import (
    analyze, build_visual_brief, clean_body, core_facts, core_summary,
    extract_entities, extract_concept, split_sentences,
)

WATERMARK_ARTICLE = """
In its announcement this week, Anthropic said Claude models launched on or after Aug. 2
would include watermarking. That includes content created by Claude through the API,
Claude Code, Claude Cowork and Claude Tag. Watermarking will apply to all Claude-generated
content wherever the AI system is offered, not just the EU. Anthropic said it would share
details on detecting the watermarks in the future. A representative for Anthropic didn't
immediately respond to a request for comment. 3 min read. Image of Claude logo.
James Martin/CNE. The move follows the EU AI Act, which requires providers to mark
synthetic content so it can be identified as machine generated.
"""
WATERMARK_TITLE = "Anthropic's Claude Will Add Watermarks to AI-Generated Text and Files"


# --------------------------------------------------------------- cleaning

def test_page_chrome_is_removed():
    cleaned = clean_body(WATERMARK_ARTICLE)
    assert "3 min read" not in cleaned
    assert "request for comment" not in cleaned
    assert "James Martin" not in cleaned or "Image of" not in cleaned
    assert "watermarking" in cleaned


def test_abbreviations_do_not_end_a_sentence():
    parts = split_sentences("Models launched after Aug. 2 include watermarking. That is new.")
    assert len(parts) == 2
    assert "Aug. 2 include" in parts[0]


# --------------------------------------------------------------- summarization

def test_core_facts_exclude_boilerplate():
    facts = core_facts(WATERMARK_TITLE, WATERMARK_ARTICLE, limit=4)
    joined = " ".join(facts).lower()
    assert facts
    assert "request for comment" not in joined
    assert "min read" not in joined


def test_core_summary_states_the_actual_news():
    summary = core_summary(WATERMARK_TITLE, WATERMARK_ARTICLE).lower()
    assert "watermark" in summary


def test_facts_are_not_near_duplicates():
    facts = core_facts(WATERMARK_TITLE, WATERMARK_ARTICLE, limit=4)
    for i, a in enumerate(facts):
        for b in facts[i + 1:]:
            wa, wb = set(a.lower().split()), set(b.lower().split())
            overlap = len(wa & wb) / max(len(wa | wb), 1)
            assert overlap <= 0.7, f"near-duplicate facts:\n{a}\n{b}"


def test_summarization_is_selective_not_just_the_first_sentences():
    """A low-value opening sentence must not automatically win a slot."""
    body = (
        "This is a short intro. "
        "The company reported that revenue grew 42 percent to 3.1 billion dollars in 2026, "
        "driven by enterprise adoption of its inference platform. "
        "Analysts had expected slower growth."
    )
    facts = core_facts("Company revenue grows 42 percent", body, limit=1)
    assert "42 percent" in facts[0], "the sentence carrying the numbers should rank first"


# --------------------------------------------------------------- entities

def test_entities_are_real_names_not_sentence_fragments():
    entities = extract_entities(f"{WATERMARK_TITLE} {WATERMARK_ARTICLE}")
    lowered = [e.lower() for e in entities]
    assert "anthropic" in lowered
    # "Claude Will Add" is a fragment, not an entity.
    assert not any("will" in e or " add" in e for e in lowered)
    assert not any("." in e and not e.endswith((".js", ".ai")) for e in entities)


def test_entities_do_not_span_sentence_boundaries():
    entities = extract_entities("We shipped Claude Tag. Watermarking is enabled.")
    assert not any("watermarking" in e.lower() and "tag" in e.lower() for e in entities)


# --------------------------------------------------------------- concepts

@pytest.mark.parametrize("title,expected", [
    ("Anthropic adds watermarks to AI-generated files", "provenance"),
    ("EU regulators open antitrust probe into cloud AI pricing", "regulation"),
    ("Startup raises $200 million at a $3 billion valuation", "funding"),
    ("Critical vulnerability lets attackers bypass authentication", "security"),
    ("Meta open sources its 400B parameter model weights", "open_source"),
    ("Cloud provider hit by six-hour outage across three regions", "outage"),
    ("New model tops SWE-bench leaderboard with 71 percent", "benchmark"),
])
def test_concept_detection_matches_the_story_action(title, expected):
    assert extract_concept(title, title)["name"] == expected


def test_unmatched_story_gets_a_neutral_scene():
    concept = extract_concept("A quiet day in the countryside", "Nothing much happened.")
    assert concept["name"] == "general"
    assert concept["scene"]


# --------------------------------------------------------------- visual briefs

def test_visual_brief_reflects_the_story_action_not_generic_ai_art():
    """
    A watermarking story used to be illustrated as a neural-network observatory purely
    because the word "model" appeared in the text.
    """
    brief = build_visual_brief(WATERMARK_TITLE, WATERMARK_ARTICLE)
    assert brief["concept"] == "provenance"
    assert "sigil" in brief["scene"] or "scroll" in brief["scene"]
    assert "neural lattice" not in brief["scene"]


def test_visual_brief_names_the_actual_subject():
    brief = build_visual_brief(WATERMARK_TITLE, WATERMARK_ARTICLE)
    assert brief["subject"].lower() in ("anthropic", "claude")


def test_concept_words_are_not_staged_as_actors():
    """"Watermarks" is what happens in the story, not a company in it."""
    brief = build_visual_brief(WATERMARK_TITLE, WATERMARK_ARTICLE)
    joined = f"{brief['subject']} {brief['supporting']}".lower()
    assert "watermark" not in joined


def test_two_different_stories_get_different_scenes():
    a = build_visual_brief("Regulators fine a cloud provider over data handling",
                           "The regulator issued a penalty under the new statute.")
    b = build_visual_brief("Startup raises $200 million to build inference chips",
                           "The round values the company at $3 billion.")
    assert a["scene"] != b["scene"]
    assert a["concept"] != b["concept"]


def test_analyze_returns_a_complete_structure():
    result = analyze(WATERMARK_TITLE, WATERMARK_ARTICLE)
    for key in ("title", "summary", "facts", "takeaway", "entities", "concept"):
        assert key in result, key
    assert result["facts"]
    assert result["concept"]["name"] == "provenance"


def test_takeaway_does_not_merely_repeat_the_lead():
    result = analyze(WATERMARK_TITLE, WATERMARK_ARTICLE)
    if result["takeaway"]:
        lead_words = set(result["summary"].lower().split())
        take_words = set(result["takeaway"].lower().split())
        overlap = len(lead_words & take_words) / max(len(take_words), 1)
        assert overlap < 0.85


def test_empty_input_does_not_crash():
    result = analyze("", "")
    assert result["facts"] == []
    assert build_visual_brief("", "")["scene"]
