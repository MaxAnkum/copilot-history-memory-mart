import csv, json, re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SRC = Path(r"a:\Padawan_Workspace\MP\copilot-activity-history.csv")
OUT_DIR = Path(r"a:\Padawan_Workspace\MP\memory_artifacts")

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
    (re.compile(r"privacy|dashboard|export|copilot|history", re.I), "Copilot history"),
    (re.compile(r"memory|remember|echo chamber", re.I), "Memory feature"),
    (re.compile(r"grand strategy|paradox|europa|cooperation|patience|zero-sum|openness|consistency", re.I), "AI strategy & games"),
    (re.compile(r"modern slavery|slavery act|debt bondage|domestic servitude", re.I), "Modern slavery Q&A"),
    (re.compile(r"napoleon|malta|french revolution|roma|sinti|apollo|challenger|roosevelt|thanksgiving", re.I), "History threads"),
    (re.compile(r"dishwasher|rinse aid|salt|siemens", re.I), "Dishwasher tips"),
    (re.compile(r"sisal|flax|vlas|manila|flask", re.I), "Materials & outdoor"),
    (re.compile(r"android|root|safetynet|play integrity|termux|docker|podman", re.I), "Android dev & security"),
    (re.compile(r"gpl|license|rijnsburg", re.I), "Licensing philosophy"),
    # New buckets to reduce Misc
    (re.compile(r"\bdbt\b|bytes?|gigabyte|log\(|logging|data (?:engineering|pipeline)", re.I), "Data engineering & logging"),
    (re.compile(r"Downton Abbey|Bob Marley|actor|series|show|movie", re.I), "Culture & media"),
    (re.compile(r"murder|ethics|morals?|allowed|not allowed", re.I), "Ethics & policy"),
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
URL_RX = re.compile(r"https?://([\w.-]+)(?:/[\S]*)?", re.I)
EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_SIMPLE_RX = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")


def redact_text(s: str) -> str:
    if not s:
        return s
    s = URL_RX.sub(lambda m: f"[URL:{m.group(1).lower()}]", s)
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
        "priority": 1
    })
    tiers[0].append({
        "primary_topic": "Memory feature",
        "core_belief": "Memory hygiene: intentional, auditable, counter-bias by design.",
        "excerpt": "Memory hygiene: intentional, auditable, counter-bias by design.",
        "provenance": "Synthesis",
        "priority": 1
    })

    # helper
    def add(tier, topic, belief, row):
        tiers[tier].append({
            "primary_topic": topic,
            "core_belief": belief,
            "excerpt": row['excerpt'],
            "provenance": row['provenance_id'],
            "priority": row['priority']
        })

    # heuristics: pick representative user lines per topic
    for topic, items in clusters.items():
        user_items = [r for r in items if r['role']=="user"]
        if not user_items:
            continue
        rep = user_items[0]
        if topic in ("AI strategy & games", "Memory feature", "Copilot history"):
            add(1, topic, "Openness+consistency enable long-term strategy; curate memory intentionally.", rep)
        elif topic in ("Android dev & security", "Licensing philosophy", "Data engineering & logging"):
            add(2, topic, "Operational constraints and practices to note.", rep)
        else:
            add(3, topic, "Reference interest/clarification in this topic.", rep)
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


def main():
    rows = parse_rows()
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

if __name__ == "__main__":
    main()
