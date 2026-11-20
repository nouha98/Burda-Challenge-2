"""das schmeckt! – editorial workflow app.

Run:  streamlit run app.py
"""
import json

import pandas as pd
import streamlit as st

from storage import runs

st.set_page_config(page_title="das schmeckt! – Trend-zu-Rezept", page_icon="🥘", layout="wide")
GREEN = "#006642"


def fmt_score(v):
    return "–" if v is None else f"{v:.0f}"


def load_proposals():
    return runs.read_json(runs.PROPOSALS)


# ---------- Sidebar: pipeline + run selection ----------
with st.sidebar:
    st.markdown(f"<h2 style='color:{GREEN};margin-bottom:0'>das schmeckt!</h2>"
                "<div style='color:#555'>Trend-zu-Rezept-Workflow</div>", unsafe_allow_html=True)
    st.divider()
    st.subheader("Daten")
    trends = runs.read_json(runs.TRENDS)
    proposals = load_proposals()
    st.caption(f"Trends: {trends['generated_at'] if trends else 'fehlt'}  \n"
               f"Vorschläge: {proposals['generated_at'] if proposals else 'fehlt'}")
    if st.button("1 · Trends neu recherchieren (~1,5 Min.)"):
        from agents import trend_agent
        with st.spinner("Trend-Agent: Google Trends + Wikimedia + Klassifikation …"):
            trend_agent.main()
        st.rerun()
    if st.button("2 · Fünf Vorschläge erstellen (~2,5 Min.)", disabled=trends is None):
        from agents import proposal_agent
        with st.spinner("Archiv-Check, Brand-Agent, Proposal-Agent …"):
            proposal_agent.main()
        st.rerun()
    st.divider()
    st.subheader("Redaktionslauf")
    all_runs = runs.list_runs()
    if "run_id" not in st.session_state:
        st.session_state.run_id = all_runs[0] if all_runs else None
    if all_runs:
        st.session_state.run_id = st.selectbox(
            "Lauf", all_runs, index=all_runs.index(st.session_state.run_id) if st.session_state.run_id in all_runs else 0)
        st.caption(f"Status: **{runs.state(st.session_state.run_id)['status']}**")
    else:
        st.caption("Noch keine Auswahl getroffen.")
    st.divider()
    with st.expander("Demo-Backup (Snapshot)"):
        from storage import snapshot
        snaps = snapshot.list_snapshots()
        if not snaps:
            st.caption("Kein Snapshot vorhanden.")
        else:
            snap = st.selectbox("Snapshot", snaps, format_func=lambda m: m["name"])
            st.caption(f"Trends {snap['trends_generated_at']} · Vorschläge {snap['proposals_generated_at']} · "
                       + ", ".join(r["proposal"].split(" ")[0] + " → " + r["status"] for r in snap["runs"]))
            if st.button("Snapshot laden", help="Lädt feste Demo-Daten. Aktuelle Dateien werden vorher gesichert."):
                res = snapshot.restore(snap["name"])
                if res["restored_runs"]:
                    st.session_state.run_id = res["restored_runs"][0]
                st.rerun()

run_id = st.session_state.run_id
tab_trends, tab_props, tab_recipes, tab_review, tab_nutri, tab_cards = st.tabs(
    ["Trends", "Vorschläge & Auswahl", "Rezepte", "Review", "Nährwerte", "Rezeptkarten"])

# ---------- Trends ----------
with tab_trends:
    if not trends:
        st.info("Noch keine Trenddaten – links „Trends neu recherchieren“ starten.")
    else:
        wm = trends["sources"]["wikimedia"]["live_window"]
        st.markdown(f"**Quellen:** Google Trends DE {trends['sources']['google_trends']['period']['start']} – "
                    f"{trends['sources']['google_trends']['period']['end']} · Wikipedia-Aufrufe (live) "
                    f"{wm['latest'][0]} – {wm['latest'][1]} vs. Vorwoche")
        rows = []
        for c in trends["candidates"]:
            s, w = c["scores"], c["wikimedia"] or {}
            rows.append({"Thema": c["classification"]["name_de"], "Art": c["classification"]["kind"],
                         "Trend-Score T": s["T"], "Google-Wachstum %": s["best_google_growth_percent"],
                         "Wikipedia 7 Tage": w.get("latest_7d_views"),
                         "Wikipedia Δ": f"{s['wikipedia_change']:+.0%}" if s["wikipedia_change"] is not None else "–",
                         "Hinweise": ", ".join(s["flags"]), "Relevanz": c["classification"]["relevance_de"]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=420)
        with st.expander(f"Ausgeschlossen ({len(trends['excluded'])})"):
            st.dataframe(pd.DataFrame([{"Thema": t["classification"].get("name_de"), "Grund": ", ".join(t["excluded_because"]),
                                        "Suchbegriffe": ", ".join(t["terms"])} for t in trends["excluded"]]),
                         width="stretch", hide_index=True)
        st.caption(trends["method"]["score"])
        for lim in trends["limitations"]:
            st.caption("⚠️ " + lim)

# ---------- Proposals + editorial selection ----------
with tab_props:
    if not proposals:
        st.info("Noch keine Vorschläge – links „Fünf Vorschläge erstellen“ starten.")
    else:
        st.markdown("Die Redaktion wählt **einen** Vorschlag. Daraus entstehen zwei unterschiedliche Rezepte.")
        for p in proposals["proposals"]:
            sc = p["scores"]
            comp = sc["components"]
            ev = p["evidence"]
            arch = ev["archive"]
            with st.container(border=True):
                head, score = st.columns([5, 2])
                head.markdown(f"#### {p['proposal_id']} · {p.get('title_de', p['topic'])}")
                head.caption(f"Thema: {p['topic']} ({p['kind']})")
                score.metric("Vorschlags-Score", f"{sc['P']:.1f} / {sc['available_maximum']:.0f}")
                st.markdown(p.get("teaser_de", ""))
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Trend (35 %)", fmt_score(comp["T"]))
                m2.metric("Marke (30 %)", fmt_score(comp["B"]))
                m3.metric("Archiv-Lücke (20 %)", fmt_score(comp["N"]))
                m4.metric("Machbarkeit (15 %)", fmt_score(comp["F"]))
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Trendsignal:** {p.get('trend_signal_de', '')}")
                    st.markdown(f"**Markenfit:** {p.get('brand_fit_de', '')}")
                    st.markdown(f"**Content-Lücke:** {p.get('content_gap_de', '')}")
                    st.markdown(f"**Wiederholungsrisiko:** {p.get('repetition_risk_de', '')}")
                with c2:
                    latest = arch.get("most_recent_comparable")
                    st.markdown(f"**Archiv (Stichprobe 5.000):** {arch['title_matches']} Rezepte im Titel, "
                                f"{arch['title_matches_recent']} in 24 Monaten")
                    if latest:
                        st.markdown(f"**Jüngstes vergleichbares Rezept:** „{latest['title']}“ ({latest['date_imported']})")
                    st.markdown("**Rezeptideen:**")
                    for d in p.get("recipe_directions", []):
                        st.markdown(f"- **{d.get('title_de')}** – {d.get('idea_de')} *({d.get('format')})*")
                with st.expander("Evidenz & offene Fragen"):
                    st.markdown("**Offene Fragen:** " + " · ".join(p.get("open_questions_de", [])))
                    st.markdown("**Google Trends**")
                    st.dataframe(pd.DataFrame([{k: r[k] for k in ("term", "signal_type", "source_kind", "search_interest",
                                                                  "increase_raw", "source_file")} for r in ev["google_records"]]),
                                 hide_index=True, width="stretch")
                    w = ev["wikimedia"] or {}
                    st.markdown(f"**Wikipedia** ({w.get('source')}, {w.get('traffic_filter')}): "
                                f"{w.get('previous_7d_views')} → {w.get('latest_7d_views')} Aufrufe "
                                f"({w.get('previous_period')} → {w.get('latest_period')})")
                    st.markdown("**Ähnliche Archivrezepte**")
                    for r in arch["closest_recipes"]:
                        st.markdown(f"- „{r['title']}“ – {r['date_imported']} – {r['category']} (`{r['id']}`)")
                    if ev["brave"].get("results"):
                        st.markdown("**Aktueller Web-Kontext (Brave, letzter Monat)**")
                        for b in ev["brave"]["results"][:5]:
                            st.markdown(f"- [{b['title']}]({b['url']})")
                    ba = ev["brand_assessment"]
                    if ba:
                        st.markdown("**Brand-Agent-Bewertung (0–5)**")
                        st.dataframe(pd.DataFrame(
                            [{"Bereich": grp, "Kriterium": k, "Wert": v.get("score"), "Begründung": v.get("reason")}
                             for grp in ("brand", "feasibility") for k, v in ba.get(grp, {}).items()]
                            + [{"Bereich": "archive", "Kriterium": "gap_fit", "Wert": ba.get("archive", {}).get("gap_fit", {}).get("score"),
                                "Begründung": ba.get("archive", {}).get("gap_fit", {}).get("reason")}]),
                            hide_index=True, width="stretch")

        st.divider()
        st.subheader("Redaktionelle Auswahl")
        with st.form("selection"):
            options = {f"{p['proposal_id']} · {p.get('title_de', p['topic'])}": p for p in proposals["proposals"]}
            choice = st.radio("Vorschlag", list(options), index=None)
            c1, c2, c3 = st.columns(3)
            servings = c1.number_input("Portionen", 1, 8, 2, help="Zielgruppe: häufig 2-Personen-Haushalte")
            max_minutes = c2.number_input("Max. Gesamtzeit (Min., 0 = egal)", 0, 240, 0, step=5)
            editor = c3.text_input("Redakteur*in", "")
            notes = st.text_area("Hinweise an den Rezept-Agenten (optional)", placeholder="z. B. eine Variante vegetarisch")
            if st.form_submit_button("Auswahl bestätigen", type="primary"):
                if not choice or not editor.strip():
                    st.error("Bitte einen Vorschlag wählen und den Namen eintragen.")
                else:
                    new_id = runs.create_run(options[choice], {"servings": int(servings),
                                                               "max_total_minutes": int(max_minutes) or None,
                                                               "notes": notes.strip()},
                                             editor.strip(), proposals["generated_at"])
                    st.session_state.run_id = new_id
                    st.success(f"Auswahl gespeichert ({new_id}). Weiter im Tab „Rezepte“.")
                    st.rerun()


# ---------- Recipes ----------
def render_recipe(r: dict):
    st.markdown(f"### {r.get('title')}")
    if r.get("subtitle"):
        st.caption(r["subtitle"])
    st.markdown(r.get("introduction", ""))
    t = r.get("times", {})
    st.markdown(f"**{r.get('servings')} {r.get('servings_unit', 'Portionen')}** · Zubereitung {t.get('prep_minutes')} Min. · "
                f"Garen {t.get('cook_minutes')} Min. · Gesamt {t.get('total_minutes')} Min.")
    st.markdown("**Zutaten**")
    group = object()
    for i in r.get("ingredients", []):
        if i.get("group") != group:
            group = i.get("group")
            if group:
                st.markdown(f"*{group}*")
        qty = f"{i['quantity']:g} " if isinstance(i.get("quantity"), (int, float)) else ""
        note = f", {i['note']}" if i.get("note") else ""
        opt = " (optional)" if i.get("optional") else ""
        st.markdown(f"- {qty}{i.get('unit') or ''} {i.get('name')}{note}{opt}")
    st.markdown("**Zubereitung**")
    group = object()
    for s in r.get("steps", []):
        if s.get("group") != group:
            group = s.get("group")
            if group:
                st.markdown(f"*{group}*")
        temp = f" *({s['temperature']})*" if s.get("temperature") else ""
        st.markdown(f"{s.get('number')}. {s.get('text')}{temp}")
    if r.get("serving_tip"):
        st.markdown(f"**Unser Tipp:** {r['serving_tip']}")
    st.caption(f"Version {r['version']} · {r.get('origin')} · {r.get('model', '').split('/')[-1]}")


with tab_recipes:
    if not run_id:
        st.info("Zuerst im Tab „Vorschläge & Auswahl“ einen Vorschlag auswählen.")
    else:
        sel = runs.selection(run_id)
        st.markdown(f"**Auswahl:** {sel['proposal_id']} · {sel['proposal'].get('title_de')} — von {sel['editor']} "
                    f"am {sel['selected_at'].replace('T', ' ')} · {sel['spec']['servings']} Portionen")
        recipes = runs.latest_recipes(run_id)
        if not recipes:
            if st.button("Zwei Rezepte entwickeln (Rezept-Agent, ~2 Min.)", type="primary"):
                from agents import recipe_agent
                with st.spinner("Rezept-Agent (Kimi-K3.1-Pro) schreibt Rezept A und B …"):
                    try:
                        recipe_agent.create_recipes(run_id)
                    except Exception as exc:
                        st.error(f"Rezept-Agent fehlgeschlagen: {exc}")
                st.rerun()
        else:
            cols = st.columns(2)
            for col, (slot, r) in zip(cols, recipes.items()):
                with col, st.container(border=True):
                    badge = {"approved": "✅ freigegeben (Review)", "needs_editor_review": "⚠️ Redaktion prüfen",
                             "draft": "📝 Entwurf"}.get(r.get("status"), r.get("status"))
                    st.markdown(f"<span style='color:{GREEN};font-weight:bold'>Rezept {slot}</span> · {badge}",
                                unsafe_allow_html=True)
                    render_recipe(r)
        with st.expander("Verlauf"):
            for e in runs.state(run_id)["events"]:
                st.markdown(f"- `{e['at']}` **{e['status']}** {e['detail']}")


# ---------- Review loop ----------
SEV_ICON = {"critical": "🛑", "major": "🔴", "minor": "🟡"}


def recipe_changes(old: dict, new: dict) -> list[str]:
    out = []
    for f in ("title", "introduction", "servings", "serving_tip"):
        if old.get(f) != new.get(f):
            out.append(f"**{f}:** {old.get(f)} → {new.get(f)}")
    if old.get("times") != new.get("times"):
        out.append(f"**Zeiten:** {old.get('times')} → {new.get('times')}")
    fmt = lambda i: f"{i.get('quantity') if i.get('quantity') is not None else ''} {i.get('unit') or ''} {i.get('name')}" \
                    + (f" ({i['note']})" if i.get("note") else "")
    oi = {i.get("id"): fmt(i) for i in old.get("ingredients", [])}
    ni = {i.get("id"): fmt(i) for i in new.get("ingredients", [])}
    for k in sorted(set(oi) | set(ni)):
        if oi.get(k) != ni.get(k):
            out.append(f"**Zutat:** {oi.get(k, '–')} → {ni.get(k, '–')}")
    os_ = {s.get("number"): s.get("text") for s in old.get("steps", [])}
    ns = {s.get("number"): s.get("text") for s in new.get("steps", [])}
    for k in sorted(set(os_) | set(ns), key=lambda x: (x is None, x)):
        if os_.get(k) != ns.get(k):
            out.append(f"**Schritt {k} neu:** {ns.get(k, '– entfernt –')}")
    return out


with tab_review:
    recipes = runs.latest_recipes(run_id) if run_id else {}
    if not recipes:
        st.info("Zuerst zwei Rezepte entwickeln (Tab „Rezepte“).")
    else:
        st.markdown("**Ablauf:** Code-Prüfung (Mengen, Verwendung aller Zutaten, Teilmengen, EL/TL, Zeiten, Portionen) → "
                    "Review-Agent (DeepSeek-V4.1-Flash) nach der 8-Punkte-Checkliste + kulinarische Plausibilität → "
                    "bei Befunden Korrektur durch den Rezept-Agenten → erneutes Review. **Maximal 2 Korrekturen.**")
        reviewed = any(runs.run_dir(run_id).glob("review_*.json"))
        if st.button("Review & Korrekturschleife starten (~1–3 Min.)" if not reviewed else "Review erneut ausführen",
                     type="primary" if not reviewed else "secondary"):
            from agents import review_agent
            box = st.empty()
            with st.spinner("Review läuft …"):
                try:
                    review_agent.review_loop(run_id, progress=lambda msg: box.info(msg))
                except Exception as exc:
                    st.error(f"Review fehlgeschlagen: {exc}")
            st.rerun()
        cols = st.columns(2)
        for col, slot in zip(cols, ["A", "B"]):
            with col:
                history = runs.recipe_history(run_id, slot)
                final = history[-1]
                st.markdown(f"### Rezept {slot}: {final.get('title')}")
                status = {"approved": "✅ Freigegeben nach Review", "needs_editor_review":
                          "⚠️ Nach 2 Korrekturen noch offene Punkte – Redaktion prüfen"}.get(final.get("status"), "📝 Noch nicht geprüft")
                st.markdown(f"**Status:** {status} · Version {final['version']}")
                for r in history:
                    rv = runs.read_json(runs.run_dir(run_id) / f"review_{slot}_v{r['version']}.json")
                    if not rv:
                        continue
                    with st.container(border=True):
                        verdict = "✅ bestanden" if rv["verdict"] == "pass" else "↩️ zur Korrektur"
                        st.markdown(f"**Version {r['version']} – {verdict} – {rv['score_total']:.0f}/100 Punkte**")
                        st.caption(rv.get("summary_de") or "")
                        sc = rv["scores"]
                        st.caption(f"Kulinarik {sc['culinary_plausibility']:.0f}/30 · Konsistenz {sc['consistency']:.0f}/25 · "
                                   f"Marke {sc['brand_fit']:.0f}/20 · Klarheit {sc['clarity']:.0f}/15 · "
                                   f"Abgrenzung {sc['differentiation']:.0f}/10")
                        issues = rv["code_findings"] + rv["llm_issues"]
                        if issues:
                            for i in issues:
                                src = "Code" if i["source"] == "code" else "Review"
                                text = i.get("message_de") or i.get("problem_de")
                                fix = f" → *{i['fix_de']}*" if i.get("fix_de") else ""
                                st.markdown(f"{SEV_ICON.get(i['severity'], '')} **{src}:** {text}{fix}")
                        else:
                            st.markdown("Keine Befunde.")
                        with st.expander("Checkliste (8 Kriterien)"):
                            names = {c[0]: c[1] for c in __import__("agents.review_agent", fromlist=["CRITERIA"]).CRITERIA}
                            st.dataframe(pd.DataFrame([{"Nr.": c.get("no"), "Kriterium": names.get(c.get("no"), ""),
                                                        "OK": "✅" if c.get("pass") else "❌", "Kommentar": c.get("comment_de")}
                                                       for c in rv["criteria"]]), hide_index=True, width="stretch")
                for old, new in zip(history, history[1:]):
                    with st.expander(f"Änderungen Version {old['version']} → {new['version']}", expanded=True):
                        for line in recipe_changes(old, new) or ["Keine inhaltlichen Änderungen."]:
                            st.markdown("- " + line)


# ---------- Nutrition ----------
MATCH_LABEL = {"exact": "exakt", "equivalent": "gleiches Lebensmittel", "closest": "nächster Ersatz", "unmatched": "nicht zugeordnet"}

with tab_nutri:
    recipes = runs.latest_recipes(run_id) if run_id else {}
    if not recipes:
        st.info("Zuerst zwei Rezepte entwickeln (Tab „Rezepte“).")
    else:
        from agents.nutrition_agent import latest_nutrition
        st.markdown("**Ablauf:** Zutat → Eintrag der *Schweizer Nährwertdatenbank V 7.1* (exakt → Schweizer Bezeichnung → "
                    "nächster Ersatz, Auswahl nur aus echten Datenbank-IDs durch den Nährwert-Agenten) → Menge in Gramm nach "
                    "dokumentierter Regel → Berechnung im Code: Σ (Gramm × Wert pro 100 g) ÷ Portionen.")
        current = {s: latest_nutrition(run_id, r) for s, r in recipes.items()}
        not_final = [s for s, r in recipes.items() if r.get("status") not in ("approved", "needs_editor_review")]
        if not_final:
            st.warning(f"Rezept {', '.join(not_final)} ist noch nicht durch das Review gelaufen.")
        stale = [s for s, n in current.items() if n is None]
        if st.button("Nährwerte berechnen (~20 Sek.)" if stale else "Nährwerte neu berechnen",
                     type="primary" if stale else "secondary"):
            from agents import nutrition_agent
            with st.spinner("Nährwert-Agent ordnet Zutaten zu …"):
                try:
                    nutrition_agent.run_nutrition(run_id)
                except Exception as exc:
                    st.error(f"Nährwertberechnung fehlgeschlagen: {exc}")
            st.rerun()
        cols = st.columns(2)
        for col, (slot, r) in zip(cols, recipes.items()):
            n = current[slot]
            with col:
                st.markdown(f"### Rezept {slot}: {r.get('title')}")
                if not n:
                    st.info(f"Für Version {r['version']} noch nicht berechnet.")
                    continue
                ps = n["per_serving"]
                st.markdown(f"**Pro Portion** ({n['servings']} Portionen, Version {n['recipe_version']})")
                m = st.columns(5)
                m[0].metric("Energie", f"{ps['kcal']} kcal")
                m[1].metric("Energie", f"{ps['kj']} kJ")
                m[2].metric("Fett", f"{ps['fat_g']:.0f} g")
                m[3].metric("Kohlenhydr.", f"{ps['carbs_g']:.0f} g")
                m[4].metric("Eiweiß", f"{ps['protein_g']:.0f} g")
                cov = n["weight_coverage"]
                st.markdown(("✅ Vollständig" if n["complete"] else "⚠️ Unvollständig – wesentliche Zutat ohne Zuordnung")
                            + (f" · Gewichtsabdeckung {cov:.0%}" if cov is not None else ""))
                st.dataframe(pd.DataFrame([{
                    "Zutat": l["display"], "Gramm": l["grams"], "Datenbankeintrag": l["db_name"] or "–",
                    "Zuordnung": MATCH_LABEL.get(l["match_type"], l["match_type"]), "Konfidenz": l["match_confidence"],
                    "Umrechnung": l["conversion_rule"], "kcal": (l.get("contribution") or {}).get("kcal"),
                    "Annahme / Begründung": l["assumption_de"]} for l in n["lines"]]),
                    hide_index=True, width="stretch")
                if n["unresolved"]:
                    st.markdown("**Nicht berechnet:**")
                    for u in n["unresolved"]:
                        st.markdown(f"- {'🔴' if u['major'] else '🟡'} {u['display']} ({u['weight_share']:.1%} des Gewichts): {u['reason']}")
                st.caption(f"{n['source']}, {n['basis']}. {n['note_de']}")


# ---------- Recipe cards ----------

with tab_cards:
    recipes = runs.latest_recipes(run_id) if run_id else {}
    if not recipes:
        st.info("Zuerst zwei Rezepte entwickeln (Tab „Rezepte“).")
    else:
        from rendering import export
        block = export.blockers(run_id)
        for slot, reasons in block.items():
            if reasons:
                st.warning(f"Rezept {slot}: " + "; ".join(reasons))
        ready = not any(block.values())
        existing = {s: export.card_path(run_id, r) for s, r in recipes.items()}
        have_all = all(p.exists() for p in existing.values())
        if st.button("Rezeptkarten erzeugen" if not have_all else "Rezeptkarten neu erzeugen",
                     type="primary" if not have_all else "secondary", disabled=not ready):
            export.export_cards(run_id)
            st.rerun()
        if not ready:
            st.caption("Karten werden erst erzeugt, wenn Review und Nährwerte für die aktuelle Version vorliegen.")
        for slot, path in existing.items():
            if not path.exists():
                continue
            html = path.read_text(encoding="utf-8")
            pages = html.count('class="page"')
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"### Rezept {slot}: {recipes[slot].get('title')}  \n"
                        f"<span style='color:#647169'>Version {recipes[slot]['version']} · {pages} Seite(n) A4 · `{path.name}`</span>",
                        unsafe_allow_html=True)
            c2.download_button("HTML herunterladen", html, file_name=f"das-schmeckt_{slot}_{path.stem}.html",
                               mime="text/html", key=f"dl_{slot}")
            st.iframe(html, height=pages * 1160 + 160)

    st.divider()
    with st.expander("Vorlage mit Archivrezepten testen (Wiederverwendbarkeit)"):
        st.caption("Die Vorlage muss auch Archivrezepte im XML-Format darstellen – Inhalte werden unverändert übernommen.")
        from ingest.archive import build_index
        from rendering.card import card_from_archive, render as render_card
        index = build_index()
        query = st.text_input("Archivrezept suchen (Titel)", "Rosenkohl")
        hits = [r for r in index if query and query.lower() in (r["title"] or "").lower()][:30]
        if hits:
            pick = st.selectbox("Rezept", hits, format_func=lambda r: f"{r['title']} ({r['date_imported']})")
            html = render_card(card_from_archive(pick))
            st.iframe(html, height=html.count('class="page"') * 1160 + 160)
        elif query:
            st.caption("Kein Treffer.")
