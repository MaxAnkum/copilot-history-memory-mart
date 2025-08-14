import csv, json, re
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SRC = Path(os.environ.get('HISTORY_CSV', r"a:\Padawan_Workspace\MP\copilot-activity-history.csv"))
OUT_DIR = Path(r"a:\Padawan_Workspace\MP\memory_artifacts")

# Ontology & approvals files (human-in-the-loop)
ONTOLOGY_FILE = OUT_DIR / "ontology.json"
APPROVALS_FILE = OUT_DIR / "approvals.json"
# Optional file with manual carves: lines like `carve: <name> ~ <regex>`
CARVE_FILE = OUT_DIR / "carves.txt"
# Optional date filter (inclusive). Leave as None to include all.
START_DATE = None  # e.g., datetime(2024, 1, 1)
END_DATE = None    # e.g., datetime(2025, 12, 31)

SCHEMA_FIELDS = [
    "timestamp","thread_id","role","prompt_intent","primary_topic","subtopic_tags",
    "entities","stance_claim","rationale_evidence","outcome_decision","action_items",
    "memory_candidate","priority","excerpt","evolution_link","provenance_id"
]

# Heuristics
INTENT_PATTERNS = [
    (re.compile(r"\?\s*$"), "question"),
    (re.compile(r"^can you|^could you|^please|^help\b", re.I), "request"),
    (re.compile(r"remember|memory|store|synthesi|tier|schema", re.I), "meta"),
    (re.compile(r"design|architect|schema|build|implement|ETL|pipeline", re.I), "design"),
    (re.compile(r"decide|decision|choose|pick|approve|consent", re.I), "decision"),
]

TOPIC_SEEDS = [
    # Specific carves before generic
    (re.compile(r"apollo|space shuttle|\bSTS-?\d+\b|challenger|columbia|astronaut|\bNASA\b", re.I), "Space history"),
    (re.compile(r"washing machine|washer|dryer|fridge|refrigerator|oven|microwave|vacuum|maintenance", re.I), "Household Q&A"),
    (re.compile(r"privacy|dashboard|export|copilot|history", re.I), "Copilot history"),
    (re.compile(r"memory|remember|echo chamber", re.I), "Memory feature"),
    (re.compile(r"grand strategy|paradox|europa|cooperation|patience|zero-sum|openness|consistency", re.I), "AI strategy & games"),
    (re.compile(r"modern slavery|slavery act|debt bondage|domestic servitude", re.I), "Modern slavery Q&A"),
    (re.compile(r"napoleon|malta|french revolution|roma|sinti|roosevelt|thanksgiving", re.I), "History threads"),
    (re.compile(r"dishwasher|rinse aid|salt|siemens", re.I), "Dishwasher tips"),
    (re.compile(r"sisal|flax|vlas|manila|flask", re.I), "Materials & outdoor"),
    (re.compile(r"android|root|safetynet|play integrity|termux|docker|podman", re.I), "Android dev & security"),
    (re.compile(r"gpl|license|rijnsburg", re.I), "Licensing philosophy"),
    (re.compile(r"\bdbt\b|bytes?|gigabyte|log\(|logging|data (?:engineering|pipeline)", re.I), "Data engineering & logging"),
    (re.compile(r"Downton Abbey|Bob Marley|actor|series|show|movie", re.I), "Culture & media"),
    (re.compile(r"murder|ethics|morals?|allowed|not allowed", re.I), "Ethics & policy"),
    (re.compile(r"inflation|credit|interest|pound|quid|prices?|economics|finance|zero[-\s]?sum", re.I), "Economics & finance"),
]

SUBTAG_EXTRACT = [
    (re.compile(r"privacy dashboard|apps and services activity", re.I), ["privacy-dashboard"]),
    (re.compile(r"excel|csv|export", re.I), ["export","csv"]),
    (re.compile(r"patience|cooperation|openness|consistency", re.I), ["patience","cooperation","openness","consistency"]),
    (re.compile(r"modern slavery act|document retention", re.I), ["msa2015","doc-retention"]),
    (re.compile(r"malta|napoleon|duchy of warsaw|tsar paul", re.I), ["malta","napoleon","poland"]),
    (re.compile(r"root|safetynet|play integrity|termux|docker|podman", re.I), ["root","integrity","termux","containers"]),
]

ENTITY_PATTERNS = [
    (re.compile(r"Microsoft Privacy Dashboard|Privacy Dashboard", re.I), "Microsoft Privacy Dashboard"),
    (re.compile(r"Modern Slavery Act 2015", re.I), "Modern Slavery Act 2015"),
    (re.compile(r"Play Integrity API|SafetyNet", re.I), "Play Integrity API"),
    (re.compile(r"Termux", re.I), "Termux"),
    (re.compile(r"VOC|Dutch East India Company", re.I), "VOC"),
]

ROLE_MAP = {"AI":"assistant","Human":"user"}

# --- Redaction helpers ---
URL_RX = re.compile(r"https?://([\w.-]+)(?:/([\S]*))?", re.I)
EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_SIMPLE_RX = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Domains to keep full URLs (no redaction of path)
ALLOW_FULL_URL_DOMAINS = [
    'microsoft.com','account.microsoft.com','learn.microsoft.com',
    'gov.uk','legislation.gov.uk','wikipedia.org','github.com'
]


def _domain_allowed(domain: str) -> bool:
    d = domain.lower()
    return any(d==a or d.endswith('.'+a) for a in ALLOW_FULL_URL_DOMAINS)


def redact_text(s: str) -> str:
    if not s:
        return s
    def _url_sub(m):
        full = m.group(0)
        dom = m.group(1).lower()
        if _domain_allowed(dom):
            return full
        return f"[URL:{dom}]"
    s = URL_RX.sub(_url_sub, s)
    s = EMAIL_RX.sub("[EMAIL]", s)
    s = PHONE_SIMPLE_RX.sub("[PHONE]", s)
    return s


def classify_intent(text:str)->str:
    for rx, lab in INTENT_PATTERNS:
        if rx.search(text):
            return lab
    return "brainstorm"


def guess_topic(text:str)->str:
    for rx, lab in TOPIC_SEEDS:
        if rx.search(text):
            return lab
    return "Misc"


def subtags(text:str):
    tags = set()
    for rx, arr in SUBTAG_EXTRACT:
        if rx.search(text):
            tags.update(arr)
    return list(tags)[:7]


def entities(text:str):
    found = set()
    for rx, name in ENTITY_PATTERNS:
        if rx.search(text):
            found.add(name)
    return list(found)


def build_excerpt(msg:str)->str:
    s = re.sub(r"\s+", " ", msg).strip()
    s = redact_text(s)
    return s[:400]


def memory_flag_and_priority(topic:str, role:str, text:str):
    t = topic.lower()
    if role=="user" and any(k in t for k in ["copilot history","memory feature","ai strategy"]):
        return "yes", 1
    if "android dev" in t or "licensing" in t:
        return "yes", 2
    return "no", 3


def _in_date_range(ts: str) -> bool:
    if not ts:
        return True
    try:
        dt = datetime.fromisoformat(ts.replace('Z',''))
    except Exception:
        return True
    if START_DATE and dt < START_DATE:
        return False
    if END_DATE and dt > END_DATE:
        return False
    return True


def parse_rows():
    rows = []
    with open(SRC, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            convo = r.get('Conversation','').strip()
            t = r.get('Time','').strip()
            if not _in_date_range(t):
                continue
            author = r.get('Author','').strip()
            msg = r.get('Message','')
            role = ROLE_MAP.get(author, 'user')
            text = msg
            intent = classify_intent(text)
            topic = guess_topic(convo + "\n" + text)
            tags = subtags(convo + "\n" + text)
            ents = entities(text)
            stance = ""
            rationale = ""
            outcome = ""
            actions = ""
            excerpt = build_excerpt(text)
            provenance_id = f"{convo} | {t}"
            mem, prio = memory_flag_and_priority(topic, role, text)
            rows.append({
                "timestamp": t,
                "thread_id": convo or 'Untitled',
                "role": role,
                "prompt_intent": intent,
                "primary_topic": topic,
                "subtopic_tags": ";".join(tags),
                "entities": ";".join(ents),
                "stance_claim": stance,
                "rationale_evidence": rationale,
                "outcome_decision": outcome,
                "action_items": actions,
                "memory_candidate": mem,
                "priority": prio,
                "excerpt": excerpt,
                "evolution_link": "",
                "provenance_id": provenance_id
            })
    return rows


def dedupe_merge(rows):
    by_excerpt = {}
    for r in rows:
        key = (r['excerpt'], r['role'])
        if key not in by_excerpt:
            by_excerpt[key] = r
        else:
            # merge provenance, tags, entities
            prev = by_excerpt[key]
            prev['provenance_id'] += f" || {r['provenance_id']}"
            if r['subtopic_tags']:
                prev['subtopic_tags'] = ";".join(sorted(set(filter(None, prev['subtopic_tags'].split(';')+r['subtopic_tags'].split(';')))))
            if r['entities']:
                prev['entities'] = ";".join(sorted(set(filter(None, prev['entities'].split(';')+r['entities'].split(';')))))
            # highest priority number is lower importance; keep min
            prev['priority'] = min(int(prev['priority']), int(r['priority']))
            # memory flag: yes dominates
            if r['memory_candidate']=="yes":
                prev['memory_candidate'] = "yes"
    return list(by_excerpt.values())


def write_csv(path, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def cluster(rows):
    clusters = defaultdict(list)
    for r in rows:
        clusters[r['primary_topic']].append(r)
    return clusters


def synthesize_cluster(topic, items):
    text_concat = " \n ".join(i['excerpt'] for i in items)
    # concise synthesis
    core_belief = ""
    if topic == "Copilot history":
        core_belief = "Users should access/export their Copilot history; current UX needs work."
    elif topic == "Memory feature":
        core_belief = "Memory must be intentional, auditable, and explainable; avoid echo chambers."
    elif topic == "AI strategy & games":
        core_belief = "Cooperation, openness, and principled consistency enable long-term strategy; encode patience."
    elif topic == "Modern slavery Q&A":
        core_belief = "Affirm Modern Slavery Act principles; recognize indicators like document retention."
    elif topic == "History threads":
        core_belief = "Clarify timelines/causality; institutions often outperform individuals."
    elif topic == "Dishwasher tips":
        core_belief = "Rinse aid depletes per cycle; salt less often; map symbols correctly."
    elif topic == "Materials & outdoor":
        core_belief = "Sisal tolerates UV; flax rots faster; pick materials per moisture exposure."
    elif topic == "Android dev & security":
        core_belief = "Android root is disabled by default; bank apps detect via integrity checks; Docker is limited."
    elif topic == "Licensing philosophy":
        core_belief = "Question global license enforceability; prefer public-domain-first ideals."
    elif topic == "Data engineering & logging":
        core_belief = "Log succinctly; avoid duplicated noise; measure bytes; prefer structured logging."
    elif topic == "Culture & media":
        core_belief = "Clarify cultural references and media history; separate fact from myth."
    elif topic == "Ethics & policy":
        core_belief = "Maintain moral clarity on harms; nuance where appropriate, clarity where required."
    elif topic == "Economics & finance":
        core_belief = "Prefer positive-sum framing; understand inflation, prices, and incentives."
    elif topic == "Space history":
        core_belief = "Differentiate mission incidents; learn from aerospace failures and timelines."
    elif topic == "Household Q&A":
        core_belief = "Practical home maintenance tips; map symbols/alerts; schedule refills and care cycles."
    else:
        core_belief = "Mixed factual clarifications across topics."

    rules = []
    if topic == "Copilot history":
        rules = [
            "If using Microsoft 365 Copilot, then use in-app Conversations; else use Privacy Dashboard.",
            "If processing share URLs, then scrape HTML/JSON; do not treat as chat logs.",
        ]
    if topic == "Memory feature":
        rules = [
            "If revisiting a topic, then it influences but is not remembered unless asked.",
            "If maintaining memory hygiene, then review/refresh memory; delete narrow prefs; seek counterarguments.",
        ]
    if topic == "AI strategy & games":
        rules = [
            "If designing systems, then reward long horizons and reputation; penalize betrayal long-term.",
            "If possible, then prefer positive-sum framing and declare consistent principles.",
        ]

    open_q = []
    if topic in ("Copilot history","Memory feature","AI strategy & games"):
        open_q = [
            "Exact dashboard paths or APIs for Copilot items.",
            "Scope of bulk memory ingestion vs curated summaries.",
            "Metrics for engineered patience and principled consistency.",
        ][:3]

    evolution = "See provenance chain inside topic for stance and tooling refinements over time."

    return {
        "topic": topic,
        "count": len(items),
        "core_belief": core_belief,
        "decision_rules": rules,
        "open_questions": open_q,
        "stance_evolution": evolution,
    }


def write_report(clusters, synths):
    idx_lines = ["# Cluster Index", "", "| Topic | Items |", "|---|---:|"]
    for s in sorted(synths, key=lambda x: x['topic']):
        idx_lines.append(f"| {s['topic']} | {s['count']} |")

    sections = []
    for s in synths:
        sections.append(f"\n## {s['topic']} ({s['count']})\n\n" \
                        f"- Core Belief: {s['core_belief']}\n" \
                        f"- Decision Rules:\n" + ''.join(f"  - {r}\n" for r in s['decision_rules']) + \
                        f"- Open Questions:\n" + ''.join(f"  - {q}\n" for q in s['open_questions']) + \
                        f"- Stance Evolution: {s['stance_evolution']}\n")

    content = "\n".join(idx_lines) + "\n" + "\n".join(sections)
    (OUT_DIR/"report.md").write_text(content, encoding='utf-8')


def _safe_dt(s: str):
    try:
        return datetime.fromisoformat(s.replace('Z',''))
    except Exception:
        return None


def refine_rows(rows, tiers=None):
    # Fill missing thread_id, enforce memory flags for Tier 0/1, and build evolution chains per topic
    tier01_excerpts = set()
    if tiers:
        for tier, arr in tiers.items():
            if tier in (0,1):
                for e in arr:
                    tier01_excerpts.add(e['excerpt'])

    # normalize fields
    for r in rows:
        if not r.get('thread_id'):
            r['thread_id'] = 'Untitled'
        if not r.get('prompt_intent'):
            r['prompt_intent'] = classify_intent(r.get('excerpt',''))
        # Enforce Tier 0/1 candidates
        if r['excerpt'] in tier01_excerpts:
            r['memory_candidate'] = 'yes'
            try:
                r['priority'] = min(int(r.get('priority', 3)), 1)
            except Exception:
                r['priority'] = 1

    # Evolution links: previous item within same topic (by timestamp) for the same role
    by_topic_role = defaultdict(list)
    for r in rows:
        by_topic_role[(r['primary_topic'], r['role'])].append(r)
    for key, arr in by_topic_role.items():
        arr.sort(key=lambda x: (_safe_dt(x['timestamp']) or datetime.min, x['excerpt']))
        prev = None
        for r in arr:
            r['evolution_link'] = prev['provenance_id'] if prev else ''
            prev = r
    return rows


def write_refined_report(clusters, synths):
    # Same structure, but output to refined_report.md
    idx_lines = ["# Cluster Index (Refined)", "", "| Topic | Items |", "|---|---:|"]
    for s in sorted(synths, key=lambda x: x['topic']):
        idx_lines.append(f"| {s['topic']} | {s['count']} |")

    sections = []
    for s in synths:
        rules = s['decision_rules'] or []
        open_q = s['open_questions'] or []
        sections.append(f"\n## {s['topic']} ({s['count']})\n\n" \
                        f"- Core Belief: {s['core_belief']}\n" \
                        f"- If/Then Decision Rules:\n" + ''.join(f"  - {r}\n" for r in rules) + \
                        f"- Open Questions (<=3):\n" + ''.join(f"  - {q}\n" for q in open_q[:3]) + \
                        f"- Stance Evolution (<=50 words): {s['stance_evolution']}\n")

    content = "\n".join(idx_lines) + "\n" + "\n".join(sections)
    (OUT_DIR/"refined_report.md").write_text(content, encoding='utf-8')


def propose_memory(clusters):
    tiers = {0:[],1:[],2:[],3:[]}

    # Tier 0 synthesized beliefs (no direct user excerpt)
    tiers[0].append({
        "primary_topic": "AI strategy & games",
        "core_belief": "Strategic triad: openness+consistency+cooperation underpin long-term trust.",
        "excerpt": "Strategic triad: openness+consistency+cooperation underpin long-term trust.",
        "provenance": "Synthesis",
        "priority": 1,
        "role": "assistant"
    })
    tiers[0].append({
        "primary_topic": "Memory feature",
        "core_belief": "Memory hygiene: intentional, auditable, counter-bias by design.",
        "excerpt": "Memory hygiene: intentional, auditable, counter-bias by design.",
        "provenance": "Synthesis",
        "priority": 1,
        "role": "assistant"
    })

    # helper
    def add(tier, topic, belief, row):
        tiers[tier].append({
            "primary_topic": topic,
            "core_belief": belief,
            "excerpt": row['excerpt'],
            "provenance": row['provenance_id'],
            "priority": row['priority'],
            "role": row.get('role','user')
        })

    # heuristics: pick representative user lines per topic
    for topic, items in clusters.items():
        user_items = [r for r in items if r['role']=="user"]
        asst_items = [r for r in items if r['role']=="assistant"]
        if topic in ("AI strategy & games", "Memory feature", "Copilot history"):
            if user_items:
                add(1, topic, "Openness+consistency enable long-term strategy; curate memory intentionally.", user_items[0])
            # keep Tier 1 focused; no assistant addition here
            continue
        if topic in ("Android dev & security", "Licensing philosophy", "Data engineering & logging"):
            if user_items:
                add(2, topic, "Operational constraints and practices to note.", user_items[0])
            if asst_items:
                add(2, topic, "Operational constraints and practices to note.", asst_items[0])
        else:
            if user_items:
                add(3, topic, "Reference interest/clarification in this topic.", user_items[0])
            if asst_items:
                add(3, topic, "Reference interest/clarification in this topic.", asst_items[0])
    return tiers


def write_memory_files(tiers):
    mem = []
    for tier, arr in tiers.items():
        for e in arr:
            mem.append({"tier": tier, **e})
    (OUT_DIR/"memory_tiers.json").write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding='utf-8')


def write_memory_mart(tiers):
    # Compact bullet list for Tier 0/1
    lines = ["# Memory Mart (Tier 0/1)", ""]
    for tier in (0,1):
        lines.append(f"## Tier {tier}")
        for e in tiers.get(tier, []):
            topic = e.get('primary_topic','')
            belief = e.get('core_belief','')
            excerpt = e.get('excerpt','')
            prov = e.get('provenance','')
            if tier == 0:
                lines.append(f"- [{topic}] {belief}")
            else:
                lines.append(f"- [{topic}] {belief} — \"{excerpt}\" (from {prov})")
        lines.append("")
    (OUT_DIR/"memory_mart_tier01.md").write_text("\n".join(lines), encoding='utf-8')


def write_memory_mart_tier23(tiers, max_per_topic: int = 50):
    # Tier 2 and Tier 3 mart; Tier 3 grouped by topic with cap
    lines = ["# Memory Mart (Tier 2/3)", ""]
    # Tier 2 flat list
    lines.append("## Tier 2")
    for e in tiers.get(2, []):
        topic = e.get('primary_topic','')
        belief = e.get('core_belief','')
        excerpt = e.get('excerpt','')
        prov = e.get('provenance','')
        role = e.get('role','')
        role_tag = f" [{role}]" if role else ""
        lines.append(f"- [{topic}] {belief}{role_tag} — \"{excerpt}\" (from {prov})")
    lines.append("")
    # Tier 3 grouped by topic
    lines.append("## Tier 3 (grouped, capped per topic)")
    by_topic = defaultdict(list)
    for e in tiers.get(3, []):
        by_topic[e.get('primary_topic','Misc')].append(e)
    for topic in sorted(by_topic.keys()):
        arr = by_topic[topic]
        lines.append(f"### {topic} ({len(arr)})")
        for e in arr[:max_per_topic]:
            belief = e.get('core_belief','')
            excerpt = e.get('excerpt','')
            prov = e.get('provenance','')
            role = e.get('role','')
            role_tag = f" [{role}]" if role else ""
            lines.append(f"- {belief}{role_tag} — \"{excerpt}\" (from {prov})")
        if len(arr) > max_per_topic:
            lines.append(f"- ...and {len(arr) - max_per_topic} more")
        lines.append("")
    (OUT_DIR/"memory_mart_tier23.md").write_text("\n".join(lines), encoding='utf-8')


def write_memory_mart_all(tiers):
    # Combined all tiers (Tier 3 grouped & capped like above)
    lines = ["# Memory Mart (All Tiers)", ""]
    lines.append("## Tier 0")
    for e in tiers.get(0, []):
        lines.append(f"- [{e.get('primary_topic','')}] {e.get('core_belief','')}")
    lines.append("")
    lines.append("## Tier 1")
    for e in tiers.get(1, []):
        lines.append(f"- [{e.get('primary_topic','')}] {e.get('core_belief','')} — \"{e.get('excerpt','')}\" (from {e.get('provenance','')})")
    lines.append("")
    by_topic2 = defaultdict(list)
    for e in tiers.get(2, []):
        by_topic2[e.get('primary_topic','Misc')].append(e)
    lines.append("## Tier 2")
    for topic in sorted(by_topic2.keys()):
        arr = by_topic2[topic]
        lines.append(f"### {topic} ({len(arr)})")
        for e in arr:
            role = e.get('role','')
            role_tag = f" [{role}]" if role else ""
            lines.append(f"- {e.get('core_belief','')}{role_tag} — \"{e.get('excerpt','')}\" (from {e.get('provenance','')})")
        lines.append("")
    by_topic3 = defaultdict(list)
    for e in tiers.get(3, []):
        by_topic3[e.get('primary_topic','Misc')].append(e)
    lines.append("## Tier 3 (grouped, capped per topic)")
    for topic in sorted(by_topic3.keys()):
        arr = by_topic3[topic]
        lines.append(f"### {topic} ({len(arr)})")
        for e in arr[:50]:
            role = e.get('role','')
            role_tag = f" [{role}]" if role else ""
            lines.append(f"- {e.get('core_belief','')}{role_tag} — \"{e.get('excerpt','')}\" (from {e.get('provenance','')})")
        if len(arr) > 50:
            lines.append(f"- ...and {len(arr) - 50} more")
        lines.append("")
    (OUT_DIR/"memory_mart_all.md").write_text("\n".join(lines), encoding='utf-8')


# ==================== Ontology-driven regrouping & cross-references ====================

def _slugify(s: str) -> str:
    s = (s or '').strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip('-') or 'misc'


def _short_words(s: str, max_words=15) -> str:
    words = re.findall(r"\w+|[^\w\s]", s or '')
    out, cnt = [], 0
    for w in words:
        if re.match(r"\w+", w):
            cnt += 1
        out.append(w)
        if cnt >= max_words:
            break
    return (" ".join(out)).strip()


def load_ontology(tiers):
    # Load or bootstrap an ontology that defines values and category mapping
    if ONTOLOGY_FILE.exists():
        try:
            return json.loads(ONTOLOGY_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    # Bootstrap default from existing Tier 0/1 entries
    values = []
    seen = set()
    for tier in (0,1):
        for e in tiers.get(tier, []):
            label = e.get('core_belief') or e.get('primary_topic')
            if not label or label in seen:
                continue
            seen.add(label)
            values.append({
                "id": f"T{tier}:{_slugify(label)[:40]}",
                "label": label,
                "tier": tier
            })
    # Default topic->category map using current topics as categories
    topic_map = {}
    for tier_list in tiers.values():
        for e in tier_list:
            topic_map[e.get('primary_topic','Misc')] = _slugify(e.get('primary_topic','Misc'))
    ont = {
        "values": values,
        "categories": {},
        "map": topic_map,
        # optional manual hints: "value_map": { "data-engineering": ["T0:memory-hygiene-..." ] }
    }
    ONTOLOGY_FILE.write_text(json.dumps(ont, ensure_ascii=False, indent=2), encoding='utf-8')
    return ont


def reindex_with_ontology(rows, ontology):
    m = ontology.get('map', {})
    for r in rows:
        cat = m.get(r['primary_topic'])
        if not cat and r['primary_topic'].lower().startswith('auto:'):
            cat = _slugify(r['primary_topic'][5:])
        r['ont_category'] = cat or _slugify(r['primary_topic'])
    return rows


def _value_candidates(ontology):
    # returns list of (id, label, token-set)
    vals = []
    for v in ontology.get('values', []):
        toks = set(tokenize(v.get('label','')))
        vals.append((v.get('id'), v.get('label'), toks))
    return vals


def link_values_for_entry(entry, ontology):
    # Heuristic: link by token overlap, plus optional value_map by category
    vals = _value_candidates(ontology)
    cat = entry.get('ont_category') or _slugify(entry.get('primary_topic',''))
    text = f"{entry.get('primary_topic','')} {entry.get('excerpt','')}"
    toks = set(tokenize(text))
    linked = []
    for vid, vlabel, vtoks in vals:
        if not vtoks:
            continue
        overlap = len(vtoks & toks)
        if overlap >= 2:
            linked.append((vid, vlabel, overlap))
    # add manual hints
    for vid in (ontology.get('value_map', {}) or {}).get(cat, []):
        v = next((x for x in ontology.get('values',[]) if x.get('id')==vid), None)
        if v:
            linked.append((vid, v.get('label'), 99))
    # unique by id, sort by score desc
    uniq = {}
    for vid, vlabel, score in linked:
        uniq[vid] = max(score, uniq.get(vid, 0))
    # return top 2 labels with tier annotation if known
    annotated = []
    for vid, score in sorted(uniq.items(), key=lambda x: -x[1])[:2]:
        v = next((x for x in ontology.get('values',[]) if x.get('id')==vid), None)
        if v is None:
            annotated.append((vid, score, ""))
        else:
            annotated.append((v.get('label'), score, v.get('tier', '')))
    return [f"Tier {t}: {lab}" if t in (0,1) else lab for lab, _, t in annotated] or []


def extract_influences(text: str):
    # Simple proper-noun detector; prefer two-word names
    if not text:
        return []
    cands = re.findall(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){0,2})\b", text)
    # filter common sentence starts and months/days
    stop = {"I","The","In","On","At","And","But","So","If","For","A","An","Of","To","We","You","He","She","They","It","May","June","July","August","September","October","November","December"}
    out = []
    for c in cands:
        parts = c.split()
        if any(p in stop for p in parts[:1]):
            continue
        if len(parts)==1 and len(c) < 4:
            continue
        out.append(c)
    # dedupe, cap
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return seen[:3]


def write_cross_reference_table(tiers, rows, ontology):
    # Build index from rows for provenance lookup
    idx = {}
    for r in rows:
        idx[(r['excerpt'], r['provenance_id'])] = r
    lines = [
        "| Tier | Entry (≤15\u202Fwords)                        | Primary Topic      | Linked Tier\u202F0/1 Value(s)     | Influence(s)              | Notes / Provenance                   |",
        "|------|----------------------------------------------|--------------------|------------------------------|---------------------------|---------------------------------------|",
    ]
    def add_row(tier, e):
        key = (e.get('excerpt',''), e.get('provenance',''))
        r = idx.get(key, {})
        topic = r.get('ont_category') or _slugify(e.get('primary_topic','Misc'))
        entry = _short_words(e.get('excerpt',''), 15)
        linked = link_values_for_entry({**r, **e}, ontology)
        link_str = "; ".join(linked) if linked else "—"
        infl = extract_influences(e.get('excerpt',''))
        infl_str = ", ".join(infl) if infl else "—"
        notes = e.get('provenance','') or r.get('provenance_id','')
        lines.append(f"| {tier}    | {entry:<42} | {topic:<18} | {link_str:<28} | {infl_str:<25} | {notes:<37} |")
    for tier in (2,3):
        for e in tiers.get(tier, []):
            add_row(tier, e)
    (OUT_DIR/"cross_reference.md").write_text("\n".join(lines), encoding='utf-8')


def propose_promotions(tiers, rows, ontology):
    # Heuristics: strong language + linked to Tier 0/1 + recurring topic
    topic_counts_user = defaultdict(int)
    for r in rows:
        if r['role'] == 'user':
            topic_counts_user[r['primary_topic']] += 1
    proposals = []
    for tier in (3,):
        for e in tiers.get(tier, []):
            text = e.get('excerpt','')
            userish = e.get('role','') == 'user'
            strong = bool(re.search(r"\b(should|must|prefer|i believe|i think|i want|i will)\b", text, re.I))
            # link to values
            linked = link_values_for_entry({"primary_topic": e.get('primary_topic',''), "excerpt": text}, ontology)
            recurring = topic_counts_user.get(e.get('primary_topic',''), 0) >= 5
            if userish and (strong or linked or recurring):
                new_tier = 2 if linked or recurring else 2
                reason = []
                if strong: reason.append("strong-statement")
                if linked: reason.append("reinforces-values")
                if recurring: reason.append("recurring-topic")
                proposals.append({
                    "provenance": e.get('provenance',''),
                    "excerpt": text,
                    "from_tier": tier,
                    "to_tier": new_tier,
                    "primary_topic": e.get('primary_topic',''),
                    "reasons": reason,
                })
    (OUT_DIR/"proposals.json").write_text(json.dumps({"promotions": proposals}, ensure_ascii=False, indent=2), encoding='utf-8')
    # Human-readable summary
    md = ["# Proposed Promotions (Human-in-the-loop)",""]
    for p in proposals[:200]:
        md.append(f"- Promote to Tier {p['to_tier']} ({', '.join(p['reasons'])}): \"{_short_words(p['excerpt'], 20)}\" — {p['provenance']}")
    (OUT_DIR/"proposals.md").write_text("\n".join(md), encoding='utf-8')


def write_master_mart_proposed(tiers, ontology):
    # Group Tier 2/3 by ontology category, do not apply promotions yet
    lines = ["# Memory Mart (All Tiers — Proposed Regrouping)",""]
    lines.append("## Tier 0")
    for e in tiers.get(0, []):
        lines.append(f"- [{e.get('primary_topic','')}] {e.get('core_belief','')}")
    lines.append("")
    lines.append("## Tier 1")
    for e in tiers.get(1, []):
        lines.append(f"- [{e.get('primary_topic','')}] {e.get('core_belief','')} — \"{e.get('excerpt','')}\" (from {e.get('provenance','')})")
    lines.append("")
    # Tier 2 by category
    lines.append("## Tier 2 (by ontology category)")
    by_cat2 = defaultdict(list)
    for e in tiers.get(2, []):
        cat = ontology.get('map', {}).get(e.get('primary_topic','')) or _slugify(e.get('primary_topic',''))
        by_cat2[cat].append(e)
    for cat in sorted(by_cat2.keys()):
        arr = by_cat2[cat]
        lines.append(f"### {cat} ({len(arr)})")
        for e in arr:
            role = e.get('role','')
            role_tag = f" [{role}]" if role else ""
            lines.append(f"- {e.get('core_belief','')}{role_tag} — \"{e.get('excerpt','')}\" (from {e.get('provenance','')})")
        lines.append("")
    # Tier 3 by category (capped)
    lines.append("## Tier 3 (by ontology category, capped)")
    by_cat3 = defaultdict(list)
    for e in tiers.get(3, []):
        cat = ontology.get('map', {}).get(e.get('primary_topic','')) or _slugify(e.get('primary_topic',''))
        by_cat3[cat].append(e)
    for cat in sorted(by_cat3.keys()):
        arr = by_cat3[cat]
        lines.append(f"### {cat} ({len(arr)})")
        for e in arr[:50]:
            role = e.get('role','')
            role_tag = f" [{role}]" if role else ""
            lines.append(f"- {e.get('core_belief','')}{role_tag} — \"{e.get('excerpt','')}\" (from {e.get('provenance','')})")
        if len(arr) > 50:
            lines.append(f"- ...and {len(arr) - 50} more")
        lines.append("")
    (OUT_DIR/"memory_mart_all_proposed.md").write_text("\n".join(lines), encoding='utf-8')


def write_memory_mart_onedoc(tiers, rows, ontology, filename="Memory_Mart_OneDoc.md"):
    # Single-file deliverable optimized for tools that accept one document
    lines = ["# Memory Mart — OneDoc", ""]
    # Tier 0/1 concise
    lines.append("## Tier 0")
    for e in tiers.get(0, []):
        lines.append(f"- [{e.get('primary_topic','')}] {e.get('core_belief','')}")
    lines.append("")
    lines.append("## Tier 1")
    for e in tiers.get(1, []):
        lines.append(f"- [{e.get('primary_topic','')}] {e.get('core_belief','')} — \"{e.get('excerpt','')}\" (from {e.get('provenance','')})")
    lines.append("")
    # Tier 2 by ontology category (post-promotion)
    lines.append("## Tier 2 (by ontology category)")
    by_cat2 = defaultdict(list)
    for e in tiers.get(2, []):
        cat = ontology.get('map', {}).get(e.get('primary_topic','')) or _slugify(e.get('primary_topic',''))
        by_cat2[cat].append(e)
    for cat in sorted(by_cat2.keys()):
        arr = by_cat2[cat]
        lines.append(f"### {cat} ({len(arr)})")
        for e in arr:
            role = e.get('role','')
            role_tag = f" [{role}]" if role else ""
            lines.append(f"- {e.get('core_belief','')}{role_tag} — \"{e.get('excerpt','')}\" (from {e.get('provenance','')})")
        lines.append("")
    # Cross-reference table (Tier 2 only) for traceability
    lines.append("## Cross-reference (Tier 2 only)")
    idx = {}
    for r in rows:
        idx[(r['excerpt'], r['provenance_id'])] = r
    lines.append("| Tier | Entry (≤15 words) | Category | Linked Tier 0/1 Value(s) | Influences | Provenance |")
    lines.append("|---|---|---|---|---|---|")
    for e in tiers.get(2, []):
        key = (e.get('excerpt',''), e.get('provenance',''))
        r = idx.get(key, {})
        cat = r.get('ont_category') or _slugify(e.get('primary_topic','Misc'))
        entry = _short_words(e.get('excerpt',''), 15)
        linked = link_values_for_entry({**r, **e}, ontology)
        link_str = "; ".join(linked) if linked else "—"
        infl = extract_influences(e.get('excerpt',''))
        infl_str = ", ".join(infl) if infl else "—"
        notes = e.get('provenance','') or r.get('provenance_id','')
        lines.append(f"| 2 | {entry} | {cat} | {link_str} | {infl_str} | {notes} |")
    target = OUT_DIR / "final" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding='utf-8')


# --- Auto-carve Misc into dynamic topics ---
STOPWORDS = set('''a an the and or but if then else for to of in on at by with without from this that these those is are was were be been being do does did not no yes it its itself you your i me my mine we our they them their as into about over under within across up down out more most less least many much few lot lots very just here there now new old other another same different also than while when where why how which who whom whose because so such can could should would will shall may might must own per vs via etc'''.split())


def tokenize(text: str):
    text = text.lower()
    toks = re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text)
    return [t for t in toks if t not in STOPWORDS]


def load_carve_directives():
    directives = []  # list of (name, compiled_regex)
    try:
        if CARVE_FILE.exists():
            for raw in CARVE_FILE.read_text(encoding='utf-8').splitlines():
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                if line.lower().startswith('carve:') and '~' in line:
                    # format: carve: <name> ~ <regex>
                    try:
                        _, rest = line.split(':', 1)
                        name_part, rx_part = rest.split('~', 1)
                        name = name_part.strip()
                        rx = rx_part.strip()
                        directives.append((name, re.compile(rx, re.I)))
                    except Exception:
                        continue
    except Exception:
        pass
    return directives


def auto_carve(rows, top_n=8, min_count=5):
    # Apply manual carves first if provided
    manual = load_carve_directives()
    if manual:
        for r in rows:
            if r['primary_topic'] == 'Misc':
                hay = f"{r.get('thread_id','')}\n{r.get('excerpt','')}"
                for name, rx in manual:
                    if rx.search(hay):
                        r['primary_topic'] = name
                        break
    # Collect terms from remaining Misc excerpts
    term_count = defaultdict(int)
    examples = defaultdict(list)
    for r in rows:
        if r['primary_topic'] == 'Misc':
            terms = tokenize(r['excerpt'])
            uniq = set(terms)
            for t in uniq:
                term_count[t] += 1
                if len(examples[t]) < 3:
                    examples[t].append(r['excerpt'])
    # pick top terms
    top_terms = [t for t,_ in sorted(term_count.items(), key=lambda x: (-x[1], x[0])) if term_count[t] >= min_count][:top_n]
    dynamic_map = {t: f"Auto: {t}" for t in top_terms}
    # Reassign topics for Misc rows when containing top term
    for r in rows:
        if r['primary_topic'] == 'Misc':
            terms = set(tokenize(r['excerpt']))
            hits = [t for t in top_terms if t in terms]
            if hits:
                r['primary_topic'] = dynamic_map[hits[0]]
    # Write suggestions file
    lines = ["# Auto Carves", "", "Top terms carved from Misc:"]
    for t in top_terms:
        lines.append(f"- carve: Auto: {t} ~ \\b{re.escape(t)}\\b (count={term_count[t]})")
        for ex in examples[t]:
            lines.append(f"  - e.g., \"{ex}\"")
    if manual:
        lines.append("\nManual carves applied:")
        for name, rx in manual:
            lines.append(f"- carve: {name} ~ {rx.pattern}")
    (OUT_DIR/"auto_carves.md").write_text("\n".join(lines), encoding='utf-8')
    return rows


# --- Semantic opinion deltas ---

def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def write_opinion_deltas_semantic(rows, sim_threshold=0.55):
    by_topic_user = defaultdict(list)
    for r in rows:
        if r['role'] == 'user':
            by_topic_user[r['primary_topic']].append(r)
    lines = ["# Opinion Deltas (Semantic)", ""]
    for topic, arr in sorted(by_topic_user.items()):
        if len(arr) < 2:
            continue
        arr.sort(key=lambda x: (_safe_dt(x['timestamp']) or datetime.min, x['excerpt']))
        first, last = arr[0], arr[-1]
        w1 = set(tokenize(first['excerpt']))
        w2 = set(tokenize(last['excerpt']))
        sim = jaccard(w1, w2)
        if sim < sim_threshold:
            added = sorted(list(w2 - w1))[:10]
            removed = sorted(list(w1 - w2))[:10]
            lines.append(f"## {topic} (similarity={sim:.2f})")
            lines.append(f"- Earliest ({first['timestamp']}): \"{first['excerpt']}\"")
            lines.append(f"- Latest   ({last['timestamp']}): \"{last['excerpt']}\"")
            if added:
                lines.append(f"- New terms: {', '.join(added)}")
            if removed:
                lines.append(f"- Dropped terms: {', '.join(removed)}")
            lines.append("")
    (OUT_DIR/"opinion_deltas_semantic.md").write_text("\n".join(lines), encoding='utf-8')


# Legacy wrapper to keep compatibility; we now prefer semantic deltas

def write_opinion_deltas(rows):
    # Generate semantic deltas, and write a short pointer in the legacy file
    write_opinion_deltas_semantic(rows)
    (OUT_DIR/"opinion_deltas.md").write_text(
        "This report moved to opinion_deltas_semantic.md (semantic similarity-based).",
        encoding='utf-8'
    )


def apply_promotions(tiers, rows):
    """Apply accepted promotions from proposals.json, validating against current rows.
    Alignment check: only promote entries whose (excerpt, provenance) exist in rows index.
    """
    path = OUT_DIR / "proposals.json"
    if not path.exists():
        return tiers
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return tiers
    promos = data.get("promotions", []) or []
    # Build row index to ensure alignment with cross_reference source rows
    row_keys = set((r.get('excerpt',''), r.get('provenance_id','')) for r in rows)
    # Helper to find item index in a tier by (excerpt, provenance)
    def _find_idx(arr, key):
        for i, e in enumerate(arr):
            if (e.get('excerpt',''), e.get('provenance','')) == key:
                return i
        return -1
    # Apply moves
    for p in promos:
        frm = int(p.get('from_tier', 3))
        to = int(p.get('to_tier', 2))
        if frm not in tiers or to not in tiers:
            continue
        key = (p.get('excerpt',''), p.get('provenance',''))
        # alignment with rows (and thus cross_reference source)
        if key not in row_keys:
            continue
        i = _find_idx(tiers[frm], key)
        if i < 0:
            continue
        item = tiers[frm].pop(i)
        # avoid duplicate in target
        if _find_idx(tiers[to], key) < 0:
            tiers[to].append(item)
    return tiers


def main():
    rows = parse_rows()
    # auto-carve after initial parse, before dedupe
    rows = auto_carve(rows)
    rows = dedupe_merge(rows)
    write_csv(OUT_DIR/"normalized.csv", rows)
    clusters = cluster(rows)
    synths = [synthesize_cluster(t, items) for t, items in clusters.items()]
    write_report(clusters, synths)
    tiers = propose_memory(clusters)
    # Refinement pass
    refined_rows = refine_rows([dict(r) for r in rows], tiers)
    write_csv(OUT_DIR/"refined_normalized.csv", refined_rows)
    refined_clusters = cluster(refined_rows)
    refined_synths = [synthesize_cluster(t, items) for t, items in refined_clusters.items()]
    write_refined_report(refined_clusters, refined_synths)
    write_memory_files(tiers)
    write_memory_mart(tiers)
    write_memory_mart_tier23(tiers)
    write_memory_mart_all(tiers)
    write_opinion_deltas(refined_rows)
    write_opinion_deltas_semantic(refined_rows)
    # Ontology + proposals + cross-reference
    ontology = load_ontology(tiers)
    refined_rows = reindex_with_ontology(refined_rows, ontology)
    write_cross_reference_table(tiers, refined_rows, ontology)
    propose_promotions(tiers, refined_rows, ontology)
    write_master_mart_proposed(tiers, ontology)
    # Apply accepted promotions and rebuild final master mart
    tiers = apply_promotions(tiers, refined_rows)
    write_memory_mart_all(tiers)
    # Regenerate cross-reference after promotions to reflect final tiers
    write_cross_reference_table(tiers, refined_rows, ontology)
    # OneDoc consolidated file for single-doc tools
    write_memory_mart_onedoc(tiers, refined_rows, ontology)

if __name__ == "__main__":
    main()
