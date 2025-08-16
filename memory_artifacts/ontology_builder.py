import json, re, os
from datetime import datetime
from pathlib import Path


STOPWORDS = set('a an the and or but if then else for to of in on at by with without from this that these those is are was were be been being do does did not no yes it its itself you your i me my mine we our they them their as into about over under within across up down out more most less least many much few lot lots very just here there now new old other another same different also than while when where why how which who whom whose because so such can could should would will shall may might must own per vs via etc'.split())

def _slugify(s: str) -> str:
    s = (s or '').strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip('-') or 'misc'


def tokenize(text: str):
    text = (text or '').lower()
    return [t for t in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text) if t not in STOPWORDS]


def load_seeds(seeds_path: Path):
    if not seeds_path.exists():
        # Minimal default: start empty; builder will add auto categories per topic
        seeds = {
            "categories": {},
            "aliases": {},
            "patterns": {},
            "sources": [],
            "authors": []
        }
        seeds_path.write_text(json.dumps(seeds, ensure_ascii=False, indent=2), encoding='utf-8')
        return seeds
    try:
        data = json.loads(seeds_path.read_text(encoding='utf-8'))
        # normalize structure
        data.setdefault('categories', {})
        data.setdefault('aliases', {})
        data.setdefault('patterns', {})
        data.setdefault('sources', [])
        data.setdefault('authors', [])
        return data
    except Exception:
        return {
            "categories": {},
            "aliases": {},
            "patterns": {},
            "sources": [],
            "authors": []
        }


# --- Source discovery ---
URL_RX = re.compile(r"https?://([\w.-]+)(?:/([^\s#?]*))?", re.I)
WIKI_CAT_RX = re.compile(r"^wiki/Category:(.+)$", re.I)
WIKI_PAGE_RX = re.compile(r"^wiki/([^/]+)$", re.I)
ISBN_RX = re.compile(r"\bISBN(?:-1[03])?:?\s*([0-9Xx\-]{10,17})\b")


def _merge_sources(existing: list, found: list) -> list:
    idx = {(s.get('type'), s.get('id')): dict(s) for s in (existing or [])}
    for s in found:
        key = (s.get('type'), s.get('id'))
        cur = idx.get(key)
        if cur:
            cur['count'] = int(cur.get('count', 0)) + int(s.get('count', 0) or 1)
            # update last_seen if newer
            try:
                if s.get('last_seen') and (not cur.get('last_seen') or s['last_seen'] > cur['last_seen']):
                    cur['last_seen'] = s['last_seen']
            except Exception:
                cur['last_seen'] = s.get('last_seen') or cur.get('last_seen')
            # keep url/label if missing
            if not cur.get('url') and s.get('url'):
                cur['url'] = s['url']
            if not cur.get('label') and s.get('label'):
                cur['label'] = s['label']
        else:
            idx[key] = s
    return list(idx.values())


def _author_slug(name: str) -> str:
    return _slugify(name)


def discover_sources(rows, seeds) -> list:
    found = []
    authors = seeds.get('authors', []) or []
    for r in rows:
        ts = r.get('timestamp') or ''
        text = (r.get('excerpt') or '')
        # URLs
        for m in URL_RX.finditer(text):
            dom = (m.group(1) or '').lower()
            path = m.group(2) or ''
            if dom.endswith('wikipedia.org'):
                # Category
                cm = WIKI_CAT_RX.match(path)
                if cm:
                    cat = cm.group(1)
                    found.append({"type": "wikipedia_category", "id": cat, "url": f"https://{dom}/wiki/Category:{cat}", "label": cat.replace('_',' '), "count": 1, "last_seen": ts})
                    continue
                # Page
                pm = WIKI_PAGE_RX.match(path)
                if pm:
                    page = pm.group(1)
                    found.append({"type": "wikipedia_page", "id": page, "url": f"https://{dom}/wiki/{page}", "label": page.replace('_',' '), "count": 1, "last_seen": ts})
                    continue
            # General domain as a source
            found.append({"type": "url_domain", "id": dom, "label": dom, "count": 1, "last_seen": ts})
        # ISBNs
        row_isbns = []
        for im in ISBN_RX.finditer(text):
            isbn = im.group(1).replace('-', '').upper()
            row_isbns.append(isbn)
            found.append({"type": "isbn", "id": isbn, "label": f"ISBN {isbn}", "count": 1, "last_seen": ts})
        # Authors (from seeds) — match via listed ISBNs or book title patterns
        if authors:
            for a in authors:
                aname = a.get('name')
                if not aname:
                    continue
                matched = False
                # by ISBN list
                for ai in (a.get('isbns') or []):
                    if ai.replace('-', '').upper() in row_isbns:
                        matched = True; break
                # by title patterns
                if not matched:
                    for rx in (a.get('book_patterns') or []):
                        try:
                            if re.search(rx, text, re.I):
                                matched = True; break
                        except re.error:
                            continue
                if matched:
                    found.append({
                        "type": "author",
                        "id": _author_slug(aname),
                        "label": aname,
                        "subjects": a.get('subjects') or [],
                        "count": 1,
                        "last_seen": ts
                    })
    # aggregate
    agg = _merge_sources([], found)
    return agg


def build_ontology(rows, tiers, out_dir: Path, seeds: dict | None = None, existing_values=None, preserve_tier0_only: bool = True,
                   wiki_category_threshold: int = 3):
    """Build ontology.json from seeds + dataset topics (Tier 2/3) in an auditable way.
    - Does not create/modify Tier 0/1 values content beyond copying from tiers.
    - Creates/updates categories, map, and value_map deterministically.
    - Writes ontology.json and a build log (final/ontology_build_log.md).
    Returns the ontology dict.
    """
    out_dir = Path(out_dir)
    seeds_path = out_dir / 'ontology_sources.json'
    if seeds is None:
        seeds = load_seeds(seeds_path)

    seed_cats: dict = dict(seeds.get('categories', {}))  # slug -> {label, description, aliases[], wiki_refs[]}
    seed_aliases: dict = dict(seeds.get('aliases', {}))   # alias(lower) -> slug
    seed_patterns: dict = dict(seeds.get('patterns', {})) # regex -> slug
    seed_sources: list = list(seeds.get('sources', []))   # list of discovered sources
    seed_authors: list = list(seeds.get('authors', []))   # author registry

    # 1) Values
    # - Preserve Tier 0 from existing_values when provided (stable, human-curated)
    # - Rebuild Tier 1 dynamically from tiers (unless no tiers provided)
    values = []
    seen_vals = set()
    if existing_values:
        try:
            for v in existing_values:
                if 'id' in v and 'label' in v and 'tier' in v:
                    if preserve_tier0_only and int(v['tier']) != 0:
                        continue
                    values.append({"id": v['id'], "label": v['label'], "tier": int(v['tier'])})
                    if int(v['tier']) == 0:
                        seen_vals.add(v['label'])
        except Exception:
            pass
    # If no Tier 0 provided, seed from tiers Tier 0
    if not any(v.get('tier') == 0 for v in values):
        for e in (tiers.get(0, []) or []):
            lab = e.get('core_belief') or e.get('primary_topic') or ''
            if not lab or lab in seen_vals:
                continue
            seen_vals.add(lab)
            values.append({
                "id": f"T0:{_slugify(lab)[:40]}",
                "label": lab,
                "tier": 0
            })
    # Always rebuild Tier 1 from tiers (dedup by label)
    t1_seen = set(v['label'] for v in values if v.get('tier') == 1)
    for e in (tiers.get(1, []) or []):
        lab = e.get('core_belief') or e.get('primary_topic') or ''
        if not lab or lab in t1_seen or lab in seen_vals:
            continue
        t1_seen.add(lab)
        values.append({
            "id": f"T1:{_slugify(lab)[:40]}",
            "label": lab,
            "tier": 1
        })

    # 2) Topics observed in dataset for Tier 2/3
    topics = []
    for tier in (2, 3):
        for e in (tiers.get(tier, []) or []):
            t = e.get('primary_topic') or 'Misc'
            topics.append(t)
    topics = sorted({t for t in topics})

    # 3) Map topics -> category slugs using seeds (label/aliases/patterns); else create auto-<slug>
    cmap = {}
    cats = dict(seed_cats)
    applied = []
    for topic in topics:
        t_slug = _slugify(topic)
        chosen = None
        # exact label match
        for slug, meta in seed_cats.items():
            if topic.lower() == (meta.get('label','').lower()):
                chosen = slug; rule = 'label-match'; break
        # alias match
        if not chosen:
            alias_slug = seed_aliases.get(topic.lower())
            if alias_slug:
                chosen = alias_slug; rule = 'alias-match'
        # pattern match
        if not chosen and seed_patterns:
            for rx, slug in seed_patterns.items():
                try:
                    if re.search(rx, topic, re.I):
                        chosen = slug; rule = f'regex:{rx}'; break
                except re.error:
                    continue
        # fallback auto
        if not chosen:
            chosen = 'auto-' + t_slug
            if chosen not in cats:
                cats[chosen] = {
                    "label": topic if not topic.lower().startswith('auto') else topic.title(),
                    "description": "Auto-added from observed dataset topic (pending curation).",
                    "aliases": [],
                    "wiki_refs": []
                }
            rule = 'auto'
        cmap[topic] = chosen
        applied.append((topic, chosen, rule))

    # 4) value_map suggestions: use token overlap between category label+sample excerpts and Tier 0/1 value labels
    def _value_candidates():
        vals = []
        for v in values:
            toks = set(tokenize(v.get('label','')))
            vals.append((v.get('id'), v.get('label'), toks, v.get('tier')))
        return vals

    val_cands = _value_candidates()
    samples_by_topic = {}
    for r in rows:
        pt = r.get('primary_topic')
        if pt in topics:
            samples_by_topic.setdefault(pt, [])
            if len(samples_by_topic[pt]) < 5:
                samples_by_topic[pt].append(r.get('excerpt') or '')

    vmap = {}
    for topic, slug in cmap.items():
        meta = cats.get(slug, {})
        sample_text = " ".join(samples_by_topic.get(topic, [])[:5])
        toks = set(tokenize(f"{meta.get('label', topic)} {sample_text}"))
        scored = []
        for vid, vlabel, vtoks, t in val_cands:
            if not vtoks:
                continue
            score = len(vtoks & toks)
            if score >= 2:
                scored.append((score, vid))
        scored.sort(reverse=True)
        if scored:
            vmap[slug] = [vid for _, vid in scored[:2]]

    # 5) Compose ontology
    ontology = {
        "values": values,
        "categories": cats,
        "map": cmap,
        "value_map": vmap
    }

    # 6) Discover and persist sources into seeds (accumulate over time)
    discovered = discover_sources(rows, seeds)
    seed_sources = _merge_sources(seed_sources, discovered)

    # 6b) Promote frequent Wikipedia categories into categories, seed value_map from them
    # Build frequency map
    wiki_cats = [s for s in seed_sources if s.get('type') == 'wikipedia_category']
    for s in wiki_cats:
        try:
            cnt = int(s.get('count', 0))
        except Exception:
            cnt = 0
        if cnt >= wiki_category_threshold:
            title = (s.get('label') or s.get('id') or '').strip()
            if not title:
                continue
            slug = _slugify(title)
            if slug not in cats:
                cats[slug] = {
                    "label": title.replace('_', ' '),
                    "description": "Promoted from frequent Wikipedia category source (auto).",
                    "aliases": [],
                    "wiki_refs": [s.get('url')] if s.get('url') else []
                }
            # seed value_map via token overlap
            toks = set(tokenize(title))
            scored = []
            for vid, vlabel, vtoks, t in val_cands:
                if not vtoks:
                    continue
                score = len(vtoks & toks)
                if score >= 2:
                    scored.append((score, vid))
            scored.sort(reverse=True)
            if scored:
                vmap[slug] = [vid for _, vid in scored[:2]]

    # 7) Write outputs
    ont_path = out_dir / 'ontology.json'
    ont_path.write_text(json.dumps(ontology, ensure_ascii=False, indent=2), encoding='utf-8')

    # Build log for auditability
    final_dir = out_dir / 'final'
    final_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Ontology build log", "", f"Built: {datetime.utcnow().isoformat()}Z", ""]
    lines.append("## Topic → category mapping decisions")
    for topic, slug, rule in applied:
        lines.append(f"- '{topic}' → `{slug}` ({rule})")
    lines.append("")
    lines.append("## value_map (category → Tier 0/1 value IDs)")
    if vmap:
        for k, arr in sorted(vmap.items()):
            lines.append(f"- `{k}` → {', '.join(arr)}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Discovered sources (top 15)")
    if seed_sources:
        top = sorted(seed_sources, key=lambda s: (-int(s.get('count',0)), s.get('type',''), s.get('id','')))[:15]
        for s in top:
            url = s.get('url')
            label = s.get('label') or s.get('id')
            lines.append(f"- [{s.get('type')}] {label} — count: {s.get('count',0)} last_seen: {s.get('last_seen','')}{(' url: '+url) if url else ''}")
    else:
        lines.append("- (none)")
    (final_dir / 'ontology_build_log.md').write_text("\n".join(lines), encoding='utf-8')

    # 8) Optional suggestions report for sources-derived ontology improvements
    if os.environ.get('ONTOLOGY_SOURCES_SUGGEST', '0') == '1':
        sugg = ["# Sources suggestions", "", f"Built: {datetime.utcnow().isoformat()}Z", ""]
        # Propose category promotions again (explicit list)
        promo = [(s.get('label') or s.get('id'), s) for s in wiki_cats if int(s.get('count',0)) >= wiki_category_threshold]
        if promo:
            sugg.append("## Proposed new categories from frequent Wikipedia categories")
            for title, s in sorted(promo):
                slug = _slugify(title)
                sugg.append(f"- `{slug}`: {title.replace('_',' ')} — mentions: {s.get('count',0)} wiki: {s.get('url','')}")
            sugg.append("")
        # Unmapped ISBNs to seed authors
        isbns = [s for s in seed_sources if s.get('type') == 'isbn']
        # Gather those not matched to any author
        known_isbns = set()
        for a in seed_authors:
            for ai in (a.get('isbns') or []):
                known_isbns.add(ai.replace('-', '').upper())
        unknown_isbns = [s for s in isbns if (s.get('id') or '').upper() not in known_isbns]
        if unknown_isbns:
            sugg.append("## ISBNs without author mapping (consider adding to seeds.authors)")
            for s in sorted(unknown_isbns, key=lambda x: -int(x.get('count',0)))[:20]:
                sugg.append(f"- {s.get('id')} — last_seen: {s.get('last_seen','')}")
            sugg.append("")
        (final_dir / 'sources_suggestions.md').write_text("\n".join(sugg), encoding='utf-8')

    # Also persist seeds for future curation/auditing (scaffold file editable by humans)
    seeds_path.write_text(json.dumps({
        "categories": seed_cats,
        "aliases": seed_aliases,
        "patterns": seed_patterns,
        "sources": seed_sources,
        "authors": seed_authors
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    return ontology
