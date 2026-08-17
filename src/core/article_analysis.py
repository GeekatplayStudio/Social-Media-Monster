"""
Article analysis: find what a story is actually about.

Two consumers depend on this:
  * the writer, which needs the CORE of a story rather than its first four sentences
  * the visual agent, which needs the story's subject and action to build a scene that
    depicts THIS article instead of generic "AI" artwork

Everything here is deterministic extraction - no model required - so quality does not
collapse when no LLM is reachable. When a model IS available it is given this analysis
as structure to write against.
"""
import re
from collections import Counter

# ---------------------------------------------------------------- noise

# Page chrome and newsroom filler that carries no information about the story.
CHROME_PATTERNS = [
    r'\b\d+\s*min(?:ute)?s?\s+read\b\.?',
    r'\bImage of [^.]*\.',
    r'^\s*(?:Photo|Image|Illustration|Credit|Getty|Reuters)[:/].*$',
    r'\b(?:didn\'?t|did not)\s+(?:immediately\s+)?respond(?:ed)?\s+to\s+(?:a\s+)?request(?:s)?\s+for\s+comment[^.]*\.',
    r'\bA\s+(?:representative|spokesperson)\s+for\s+[^.]*?\s+(?:didn\'?t|did not)[^.]*\.',
    r'\b(?:Sign up|Subscribe|Newsletter|Advertisement|Related coverage|Read more|Continue reading)\b[^.]*\.?',
    r'\bFollow us on\b[^.]*\.?',
    r'\bAll rights reserved\b[^.]*\.?',
    # Only a standalone share bar, never the verb: "would share details" must survive a
    # line break falling right after "share".
    r'^[ \t]*(?:Share|Tweet|Copy link)[ \t]*$',
    r'^\s*#{1,6}\s*',                       # markdown headings -> keep the text
    r'\[[^\]]*\]\([^)]*\)',                 # leftover markdown links
    r'https?://\S+',
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "from", "into", "that", "this",
    "these", "those", "of", "to", "in", "on", "at", "by", "as", "is", "are", "was", "were",
    "be", "been", "being", "it", "its", "has", "have", "had", "will", "would", "can",
    "could", "should", "may", "might", "must", "new", "now", "how", "why", "what", "when",
    "after", "over", "more", "than", "you", "your", "our", "their", "they", "we", "he",
    "she", "his", "her", "them", "there", "here", "also", "just", "very", "much", "many",
    "some", "all", "not", "no", "if", "then", "so", "up", "out", "about", "said", "says",
    "including", "include", "includes", "according", "week", "year", "day", "time", "make",
    "made", "get", "got", "use", "used", "using", "add", "adds", "added", "adding",
}

# Words that look like entities but are generic. Kept out of hashtags and image subjects.
WEAK_ENTITY_WORDS = {
    "the", "this", "that", "it", "in", "its", "add", "adds", "added", "will", "would",
    "new", "how", "why", "what", "when", "and", "but", "for", "with", "from", "ai",
    "ai-generated", "text", "files", "data", "tech", "news", "report", "update", "here",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

# Well-known organisations and products, so they are recognised even mid-sentence.
KNOWN_ENTITIES = {
    "openai", "anthropic", "google", "deepmind", "meta", "microsoft", "nvidia", "apple",
    "amazon", "aws", "azure", "tesla", "spacex", "netflix", "ibm", "intel", "amd", "arm",
    "qualcomm", "samsung", "tiktok", "bytedance", "alibaba", "baidu", "tencent",
    "mistral", "cohere", "hugging face", "huggingface", "stability", "midjourney",
    "perplexity", "databricks", "snowflake", "salesforce", "oracle", "adobe", "figma",
    "github", "gitlab", "docker", "kubernetes", "redis", "postgres", "postgresql",
    "sqlite", "mongodb", "linux", "windows", "android", "ios", "chrome", "firefox",
    "claude", "gpt", "gemini", "llama", "mistral", "qwen", "grok", "copilot", "sora",
    "dall-e", "stable diffusion", "comfyui", "pytorch", "tensorflow", "cuda",
}

# ---------------------------------------------------------------- visual concepts
#
# Each concept maps a story's ACTION to a concrete scene. This is what stops a
# watermarking story from being illustrated as a generic neural-network observatory.
CONCEPTS = [
    {
        "name": "provenance",
        "triggers": ["watermark", "watermarking", "provenance", "authenticity", "attribution",
                     "detect ai", "ai detection", "c2pa", "content credentials", "fingerprint",
                     "invisible mark", "signed content", "label ai"],
        "scene": "a scriptorium where a glowing sigil is being pressed invisibly into a scroll, "
                 "its hidden mark flaring into view only under a raised lantern",
        "props": "seal press, watermark glyph, lantern beam revealing hidden runes",
    },
    {
        "name": "release",
        "triggers": ["launch", "launches", "released", "release", "ships", "shipping", "unveil",
                     "announces", "introducing", "rolls out", "rollout", "general availability",
                     "now available", "debut"],
        "scene": "an unveiling hall where a covered artifact on a raised dais is revealed to a "
                 "waiting crowd of operator sprites",
        "props": "draped pedestal, ceremonial banners, spotlight shafts",
    },
    {
        "name": "regulation",
        "triggers": ["regulation", "regulator", "policy", "law", "lawsuit", "sued", "court",
                     "antitrust", "ban", "banned", "fine", "fined", "compliance", "eu ai act",
                     "legislation", "subpoena", "ruling", "settlement", "copyright"],
        "scene": "a marble senate chamber where holographic statutes hover above robed envoys "
                 "arguing across a divided floor",
        "props": "stone tablets of law, scales, seal of judgement",
    },
    {
        "name": "security",
        "triggers": ["breach", "hacked", "hack", "exploit", "vulnerability", "cve", "malware",
                     "ransomware", "leak", "leaked", "compromised", "zero-day", "phishing",
                     "backdoor", "attack"],
        "scene": "a fractured vault door in a fortress wall, alarm sigils burning red while "
                 "shadow figures slip through the breach",
        "props": "shattered lock rune, warning beacons, spilled data crystals",
    },
    {
        "name": "funding",
        "triggers": ["funding", "raised", "raises", "valuation", "investment", "acquisition",
                     "acquires", "acquired", "merger", "ipo", "billion", "million", "revenue",
                     "profit", "buyout", "stake"],
        "scene": "a treasury hall where towering stacks of glowing ingots are weighed on a "
                 "great brass balance before assembled merchants",
        "props": "coin towers, ledger scrolls, rising value spires",
    },
    {
        "name": "benchmark",
        "triggers": ["benchmark", "outperform", "beats", "state of the art", "sota", "accuracy",
                     "score", "leaderboard", "evaluation", "eval", "wins", "record", "faster than"],
        "scene": "a tournament arena with a great illuminated scoreboard, rival champions' "
                 "banners ranked in ascending tiers",
        "props": "scoreboard runes, laurel wreath, ranked pennants",
    },
    {
        "name": "open_source",
        "triggers": ["open source", "open-source", "open sources", "weights released", "apache",
                     "mit license", "public repository", "free to use", "community edition"],
        "scene": "a fortress gate thrown wide, blueprints unrolled on a communal table as "
                 "travellers copy them by torchlight",
        "props": "open gates, shared blueprints, copied scrolls",
    },
    {
        "name": "outage",
        "triggers": ["outage", "downtime", "went down", "disruption", "degraded", "incident",
                     "restored", "postmortem", "post-mortem", "failure", "crashed"],
        "scene": "a darkened server hall where cooling towers stand silent and a lone engineer "
                 "sprite works beneath emergency lamps",
        "props": "dead status runes, emergency lighting, tangled cables",
    },
    {
        "name": "hardware",
        "triggers": ["chip", "gpu", "silicon", "datacenter", "data center", "cluster", "wafer",
                     "fab", "foundry", "tpu", "accelerator", "supercomputer", "hbm"],
        "scene": "a cavernous foundry where molten silicon is poured into rune-etched wafer "
                 "moulds beneath humming compute pylons",
        "props": "wafer moulds, cooling pylons, forge glow",
    },
    {
        "name": "agents",
        "triggers": ["agent", "agents", "autonomous", "orchestration", "workflow", "multi-agent",
                     "tool use", "automation", "assistant"],
        "scene": "a command hall where a robed operator directs a constellation of small task "
                 "drones across a glowing floor map",
        "props": "task constellation, command dais, routing threads",
    },
    {
        "name": "media_gen",
        "triggers": ["image generation", "video generation", "diffusion", "text-to-image",
                     "text-to-video", "render", "generative art", "voice clone", "deepfake"],
        "scene": "an artisan's atelier where a pixel-forge loom weaves beams of light into "
                 "moving picture frames",
        "props": "light loom, frame reels, prism array",
    },
    {
        "name": "model_training",
        "triggers": ["training", "trained", "fine-tune", "fine-tuning", "pretraining", "dataset",
                     "parameters", "context window", "tokens", "inference", "model card"],
        "scene": "an observatory where a vast lattice of constellation nodes is tuned by "
                 "astronomers adjusting brass dials",
        "props": "node lattice, tuning dials, star charts",
    },
    {
        "name": "data_storage",
        "triggers": ["database", "sqlite", "postgres", "storage", "corruption", "index",
                     "query", "replication", "backup", "wal"],
        "scene": "a subterranean archive of glowing crystal storage cores linked by branching "
                 "index conduits",
        "props": "crystal cores, conduit branches, archive ledgers",
    },
    {
        "name": "developer",
        "triggers": ["developer", "api", "sdk", "framework", "library", "release notes",
                     "python", "javascript", "rust", "compiler", "ide", "code"],
        "scene": "a developer's sanctum of stacked terminal monoliths streaming live source "
                 "glyphs around a central workbench",
        "props": "terminal monoliths, glyph streams, tool rack",
    },
    {
        "name": "partnership",
        "triggers": ["partnership", "partners", "collaboration", "teams up", "joint", "alliance",
                     "integration", "deal with"],
        "scene": "two great banners being joined at a stone bridge as delegations meet at the "
                 "midpoint",
        "props": "joined banners, bridge span, clasped seals",
    },
    {
        "name": "shutdown",
        "triggers": ["deprecate", "deprecated", "sunset", "shutting down", "shut down",
                     "discontinued", "end of life", "retire", "layoffs", "cuts"],
        "scene": "a great machine being dismantled plate by plate, its power runes dimming as "
                 "crates are carried out",
        "props": "dismantled plating, dimming runes, packing crates",
    },
]

DEFAULT_SCENE = ("a retro-futurist newsroom hall lined with glowing broadcast monitors "
                 "relaying an unfolding story")
DEFAULT_PROPS = "broadcast monitors, ticker banners, dispatch desk"

# Two stories on the same subject share a concept, which alone produced the identical
# scene description and near-identical artwork. These axes vary the staging per story so
# related articles stay on-concept without repeating each other.
NARRATIVE_MOMENTS = [
    "at the tense moment the process begins",
    "mid-action, with figures reacting to what is unfolding",
    "in the quiet aftermath, the space emptied and cooling",
    "at peak activity, crowded and urgent",
    "just before dawn, with a single figure preparing the work",
    "during a sudden interruption, alarms and attention converging",
]

CAMERA_VANTAGES = [
    "viewed from a low heroic angle",
    "seen from a high gantry looking down",
    "framed through a doorway in the foreground",
    "a close three-quarter view of the central subject",
    "a wide symmetrical head-on composition",
    "an off-centre view with deep receding perspective",
]

PALETTE_KEYS = [
    "deep indigo shadows with cyan rim light and warm amber highlights",
    "cold teal shadows against molten orange key light",
    "violet and magenta dusk tones with pale gold accents",
    "slate blue midtones with emerald signal glow",
    "warm sepia base with icy blue practical lights",
]


def _stable_index(text: str, modulus: int) -> int:
    """Deterministic per-story selection: same story always renders the same way."""
    digest = 0
    for ch in (text or "untitled"):
        digest = (digest * 131 + ord(ch)) & 0xFFFFFFFF
    return digest % max(modulus, 1)


# ---------------------------------------------------------------- cleaning
def clean_body(text: str) -> str:
    """Strips page chrome so scoring is not polluted by nav and photo credits."""
    cleaned = text or ""
    for pattern in CHROME_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


ABBREVIATIONS = {
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "inc", "ltd", "co", "corp", "dr", "mr", "mrs", "ms", "prof", "st", "vs", "etc",
    "no", "fig", "approx", "al", "u.s", "e.g", "i.e", "est", "min", "max", "ver", "rev",
}


def split_sentences(text: str) -> list:
    """Abbreviation-aware sentence split ("Aug. 2" stays one sentence)."""
    # Unwrap hard-wrapped prose first. Splitting on every newline chopped wrapped
    # paragraphs mid-sentence, producing fragments like "Claude Code, Claude Cowork and".
    unwrapped = re.sub(r'(?<![.!?:])\n(?!\s*\n)(?!\s*[-*•▪]|\s*\d+[.)])', ' ', text or "")

    out = []
    for chunk in re.split(r'(?<=[.!?])\s+|\n+', unwrapped):
        frag = re.sub(r'^\s*(?:[-*•▪]|\d+[.)])\s*', '', chunk).strip()
        if not frag:
            continue
        if out:
            prev = out[-1]
            tail = prev.split()[-1].rstrip('.').lower() if prev.split() else ""
            if tail in ABBREVIATIONS or frag[0].isdigit() or frag[0].islower():
                out[-1] = f"{prev} {frag}"
                continue
        out.append(frag)
    return out


# ---------------------------------------------------------------- entities
def extract_entities(text: str, limit: int = 6) -> list:
    """Organisations, products and proper nouns - the things a story is *about*."""
    counts = Counter()

    # Segment first: a capitalised run must not span a sentence boundary, otherwise
    # "...Claude Tag. Watermarking will..." is read as one entity.
    for segment in re.split(r'(?<=[.!?;:])\s+|\n+|,\s*', text or ""):
        # No '.' in the token class for the same reason; "Node.js" is handled below.
        for match in re.findall(r'\b(?:[A-Z][a-zA-Z0-9+-]*(?:\.[a-z]{2,3})?(?:\s+[A-Z][a-zA-Z0-9+-]*){0,2})\b', segment):
            words = match.split()
            # Trim leading/trailing filler: "Claude Will Add" -> "Claude".
            while words and words[0].lower() in WEAK_ENTITY_WORDS:
                words.pop(0)
            while words and words[-1].lower() in WEAK_ENTITY_WORDS:
                words.pop()
            if not words:
                continue
            # A verb or filler word inside the run means it is a sentence fragment.
            if any(w.lower() in WEAK_ENTITY_WORDS for w in words):
                continue
            token = " ".join(words)
            if len(token) < 3:
                continue
            low = token.lower()
            weight = 3 if low in KNOWN_ENTITIES else 1
            if len(words) > 1:
                weight += 1
            counts[token] += weight

    # Known names appear in lowercase prose too.
    lowered = (text or "").lower()
    for known in KNOWN_ENTITIES:
        if known in lowered:
            counts[known.title()] += 2

    ranked, seen = [], set()
    for name, _ in counts.most_common(limit * 4):
        key = name.lower()
        # Skip a term already covered by a longer phrase, e.g. "Claude" under "Claude Code".
        if any(key != s and key in s for s in seen):
            continue
        seen.add(key)
        ranked.append(name)
        if len(ranked) >= limit:
            break
    return ranked


def extract_concept(title: str, body: str) -> dict:
    """
    What HAPPENS in the story. Title matches count double because a headline states the
    action; body matches alone often reflect background context.
    """
    title_l = (title or "").lower()
    body_l = (body or "")[:4000].lower()

    def occurs(trigger: str, text: str) -> bool:
        """
        Anchored at the start of a word, tolerant of ordinary inflection at the end.

        A bare substring test let "ide" fire inside "countryside" and "api" inside
        "rapidly". A strict word boundary at both ends went too far the other way and
        stopped "watermark" from matching "watermarking", so only regular suffixes are
        allowed to follow.
        """
        pattern = rf'(?<![a-z0-9]){re.escape(trigger)}(?:s|es|ed|d|ing|er|ers)?(?![a-z0-9])'
        return re.search(pattern, text) is not None

    best, best_score = None, 0
    for concept in CONCEPTS:
        score = 0
        for trigger in concept["triggers"]:
            if occurs(trigger, title_l):
                score += 3
            if occurs(trigger, body_l):
                score += 1
        if score > best_score:
            best, best_score = concept, score

    if not best:
        return {"name": "general", "scene": DEFAULT_SCENE, "props": DEFAULT_PROPS, "score": 0}
    return {**best, "score": best_score}


# ---------------------------------------------------------------- summarization
def _sentence_score(sentence: str, index: int, total: int, title_terms: set, body_terms: Counter) -> float:
    words = [w.lower().strip(".,;:()\"'") for w in sentence.split()]
    content = [w for w in words if w and w not in STOPWORDS]
    if not content:
        return -1.0

    score = 0.0

    # Coverage of the headline's distinct terms. Counting every occurrence rewarded
    # repetition instead of relevance: a list naming "Claude" four times outscored the
    # sentence that actually stated the news.
    distinct = set(content)
    score += len(distinct & title_terms) * 2.5

    # Terms that recur through the article are its themes.
    score += sum(body_terms.get(w, 0) for w in distinct) / max(len(distinct), 1)

    # Concrete, checkable detail earns its place.
    if re.search(r'\b\d', sentence):
        score += 2.0
    if re.search(r'\b(?:percent|%|million|billion|version|v\d|\d{4})\b', sentence, re.I):
        score += 1.5
    if re.search(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b', sentence):
        score += 0.8

    # Lead bias: news puts the core up front, but not exclusively.
    score += max(0.0, 3.0 - (index / max(total, 1)) * 4.0)

    # Length sanity - fragments and run-ons both read badly.
    n = len(words)
    if n < 6:
        score -= 3.0
    elif n > 45:
        score -= 2.0
    elif 10 <= n <= 32:
        score += 1.0

    # Filler that adds nothing.
    low = sentence.lower()
    if any(p in low for p in ("request for comment", "declined to comment", "read more",
                             "click here", "subscribe", "all rights reserved")):
        score -= 6.0
    if low.startswith(("but ", "and ", "however", "that said", "meanwhile")):
        score -= 1.0

    # A sentence opening with a back-reference cannot stand alone as a summary line:
    # "That includes content created by..." is meaningless without its predecessor.
    if re.match(r'^(?:that|this|these|those|it|they|he|she|there|such|both|either)\b', low):
        score -= 4.0

    return score


def rank_sentences(title: str, body: str) -> list:
    """Sentences ordered by how central they are to the story."""
    cleaned = clean_body(body)
    sentences = [s for s in split_sentences(cleaned) if len(s) > 30]
    if not sentences:
        return []

    title_terms = {w.lower().strip(".,;:()") for w in (title or "").split()
                   if w.lower() not in STOPWORDS and len(w) > 2}

    body_terms = Counter()
    for w in re.findall(r'\b[a-zA-Z][a-zA-Z0-9-]{2,}\b', cleaned.lower()):
        if w not in STOPWORDS:
            body_terms[w] += 1
    # Normalise so a long article does not simply outscore a short one.
    if body_terms:
        top = body_terms.most_common(1)[0][1]
        body_terms = Counter({k: v / top for k, v in body_terms.items()})

    scored = [
        (_sentence_score(s, i, len(sentences), title_terms, body_terms), i, s)
        for i, s in enumerate(sentences)
    ]
    scored.sort(key=lambda t: -t[0])
    return [{"text": s, "score": round(sc, 2), "position": i} for sc, i, s in scored]


def core_facts(title: str, body: str, limit: int = 4) -> list:
    """The most central sentences, returned in reading order."""
    ranked = rank_sentences(title, body)
    if not ranked:
        return []
    chosen = _dedupe(ranked, limit)
    chosen.sort(key=lambda r: r["position"])
    return [r["text"] for r in chosen]


def _dedupe(ranked: list, limit: int) -> list:
    """Drops near-duplicate sentences so the summary is not the same point three ways."""
    picked = []
    for cand in ranked:
        cand_words = {w for w in cand["text"].lower().split() if w not in STOPWORDS}
        if not cand_words:
            continue
        duplicate = False
        for chosen in picked:
            chosen_words = {w for w in chosen["text"].lower().split() if w not in STOPWORDS}
            overlap = len(cand_words & chosen_words) / max(len(cand_words | chosen_words), 1)
            if overlap > 0.55:
                duplicate = True
                break
        if not duplicate:
            picked.append(cand)
        if len(picked) >= limit:
            break
    return picked


def core_summary(title: str, body: str) -> str:
    """One sentence stating what the story is. The nut graf."""
    facts = core_facts(title, body, limit=1)
    return facts[0] if facts else (title or "").strip()


def takeaway(title: str, body: str, exclude: str = "") -> str:
    """
    A 'so what' line that does not simply restate the facts already shown.
    Prefers forward-looking or consequence sentences.
    """
    ranked = rank_sentences(title, body)
    exclude_words = {w for w in (exclude or "").lower().split() if w not in STOPWORDS}

    forward = re.compile(
        r'\b(?:will|would|expects?|plans?|means?|could|impact|affects?|requires?|'
        r'plan to|going to|plans to|in the future|next|by \d{4})\b', re.I)

    best = None
    for r in ranked:
        words = {w for w in r["text"].lower().split() if w not in STOPWORDS}
        if exclude_words and len(words & exclude_words) / max(len(words), 1) > 0.6:
            continue
        if forward.search(r["text"]):
            best = r["text"]
            break
        if best is None:
            best = r["text"]
    return best or ""


def analyze(title: str, body: str) -> dict:
    """Full analysis used by the writer, the verifier and the visual agent."""
    cleaned = clean_body(body)
    facts = core_facts(title, cleaned, limit=4)
    summary = facts[0] if facts else (title or "").strip()
    return {
        "title": (title or "").strip(),
        "summary": summary,
        "facts": facts,
        "takeaway": takeaway(title, cleaned, exclude=" ".join(facts[:2])),
        "entities": extract_entities(f"{title} {cleaned}"),
        "concept": extract_concept(title, cleaned),
        "numbers": re.findall(r'\b\d[\d,.]*\s*(?:%|percent|million|billion|x|GB|TB|ms|B)?\b',
                              " ".join(facts))[:6],
    }


# ---------------------------------------------------------------- visual composition
def build_visual_brief(title: str, body: str) -> dict:
    """
    Turns the article into a concrete scene description. The concept supplies the action,
    the entities supply the subject, so two different stories never share a prompt.
    """
    analysis = analyze(title, body)
    concept = analysis["concept"]

    # A concept word that happens to be capitalised in a headline ("Watermarks") is the
    # story's action, not one of its actors, so it must not be staged as a banner.
    def stem(word: str) -> str:
        w = word.lower().rstrip(".,")
        for suffix in ("ing", "ers", "ed", "es", "s"):
            if len(w) > 4 and w.endswith(suffix):
                return w[: -len(suffix)]
        return w

    # Stemmed comparison so "Watermarks" is recognised as the concept "watermarking".
    concept_stems = {stem(w) for trigger in concept.get("triggers", []) for w in trigger.split()}

    entities = [
        e for e in analysis["entities"]
        if e.lower() not in WEAK_ENTITY_WORDS
        and not all(stem(w) in concept_stems for w in e.split())
    ]

    subject = entities[0] if entities else ""
    supporting = ", ".join(entities[1:3])

    # Vary staging by story, not by concept, so two articles on the same subject do not
    # render the same picture. Seeded from the headline, so a given story is stable.
    key = f"{title}|{subject}"
    moment = NARRATIVE_MOMENTS[_stable_index(key, len(NARRATIVE_MOMENTS))]
    vantage = CAMERA_VANTAGES[_stable_index(key + "v", len(CAMERA_VANTAGES))]
    palette = PALETTE_KEYS[_stable_index(key + "p", len(PALETTE_KEYS))]

    return {
        "concept": concept["name"],
        "scene": concept["scene"],
        "props": concept["props"],
        "subject": subject,
        "supporting": supporting,
        "summary": analysis["summary"],
        "entities": entities,
        "moment": moment,
        "vantage": vantage,
        "palette": palette,
        # Distinct focus term keeps the prompt anchored to THIS article's specifics.
        "focus": ", ".join(entities[:3]) or (analysis["summary"][:60] if analysis["summary"] else ""),
    }
