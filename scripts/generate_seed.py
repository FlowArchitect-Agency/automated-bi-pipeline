"""Generate realistic demo seed data for the BI pipeline's 5 sources.

This is SAMPLE DATA, clearly demo-labeled. It is generated deterministically
(seed fixed) so tests are reproducible. Deliberate anomalies are injected so
the anomaly-detection enricher has something to find.

Run:  python scripts/generate_seed.py
Writes to: data/seed/*.csv
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

# Report window: last 60 days ending 2026-08-02 (the "today" in the demo)
END = datetime(2026, 8, 2)
START = END - timedelta(days=60)
DAYS = (END - START).days

OUT = Path(__file__).resolve().parent.parent / "data" / "seed"
OUT.mkdir(parents=True, exist_ok=True)

DEMO_NOTE = "SAMPLE/DEMO DATA — synthetically generated, not real customers."

# ── Shared vocab ───────────────────────────────────────────────
REGIONS = ["FR", "EU", "UK", "US"]
CHANNELS = ["web", "mobile", "marketplace"]
TICKET_LANGS = ["en", "fr"]
TICKET_CHANNELS = ["email", "chat", "in_app", "phone"]

SUBJECTS = {
    "billing": {
        "en": ["Wrong amount charged", "Invoice not received", "Refund request", "Subscription renewal issue"],
        "fr": ["Facturation erronée", "Facture non reçue", "Demande de remboursement", "Problème d'abonnement"],
    },
    "shipping": {
        "en": ["Package delayed", "Wrong item delivered", "Tracking not updating", "Damaged on arrival"],
        "fr": ["Colis en retard", "Mauvais article livré", "Suivi bloqué", "Colis endommagé"],
    },
    "bug": {
        "en": ["Checkout button broken", "App crashes on login", "Payment fails on mobile", "Search returns error"],
        "fr": ["Bouton de paiement cassé", "L'application plante", "Paiement échoue sur mobile", "Erreur de recherche"],
    },
    "feature_request": {
        "en": ["Add CSV export", "Dark mode please", "Bulk edit for inventory", "SSO integration request"],
        "fr": ["Ajouter l'export CSV", "Mode sombre svp", "Édition en masse du stock", "Demande SSO"],
    },
    "account": {
        "en": ["Cannot reset password", "Two-factor auth problem", "Merge two accounts", "Delete my account"],
        "fr": ["Réinitialisation mot de passe", "Problème 2FA", "Fusionner des comptes", "Supprimer mon compte"],
    },
    "other": {
        "en": ["General question", "Partnership inquiry", "Press contact", "Feedback"],
        "fr": ["Question générale", "Demande de partenariat", "Contact presse", "Retour"],
    },
}
DESCS = {
    "billing": {
        "en": "I was charged {amt} but my order total was {exp}. Please investigate and refund the difference.",
        "fr": "J'ai été facturé {amt}€ alors que le total était de {exp}€. Merci d'examiner et de rembourser.",
    },
    "shipping": {
        "en": "My order #{oid} was supposed to arrive on {dt} but it's now {delay} days late. Status still says 'in transit'.",
        "fr": "Ma commande #{oid} devait arriver le {dt} mais a maintenant {delay} jours de retard. Toujours 'en transit'.",
    },
    "bug": {
        "en": "When I click checkout the spinner spins forever and nothing happens on Chrome/Safari. Console shows a 500 error.",
        "fr": "Quand je clique sur payer le loader tourne indéfiniment sur Chrome/Safari. Erreur 500 dans la console.",
    },
    "feature_request": {
        "en": "Would love to see this added — it would save our team several hours per week. Happy to beta test.",
        "fr": "Ce serait super d'ajouter ça — ça nous ferait gagner plusieurs heures par semaine. Prêt pour la bêta.",
    },
    "account": {
        "en": "I'm locked out and the password reset email never arrives. Tried multiple times. Very frustrated.",
        "fr": "Je suis bloqué et l'email de réinitialisation n'arrive jamais. J'ai essayé plusieurs fois. Très frustré.",
    },
    "other": {
        "en": "Just reaching out — not urgent. Wanted to share some feedback on the recent update.",
        "fr": "Je vous contacte — pas urgent. Je voulais partager un retour sur la dernière mise à jour.",
    },
}

PRODUCTS = [
    ("P-1001", "AcmeFlow Project Manager"),
    ("P-1002", "AcmeFlow CRM Add-on"),
    ("P-1003", "DataPipe Connector Pack"),
    ("P-1004", "InsightDeck Dashboard"),
    ("P-1005", "FormBuilder Pro"),
    ("P-1006", "InboxZero Assistant"),
]
# Titles/bodies bucketed by sentiment so rating and text are coherent
# (critical for believable demo data and meaningful summarization).
REVIEW = {
    "positive": {
        "titles": {
            "en": ["Great product", "Love it", "Best purchase this year", "Works as expected"],
            "fr": ["Super produit", "J'adore", "Meilleur achat", "Conforme"],
        },
        "bodies": {
            "en": [
                "The onboarding was smooth and the UI is intuitive. Support helped us migrate from our old tool.",
                "Solid and reliable. Integrations with our stack just worked. Would recommend for small teams.",
                "I absolutely love it. Saved me hours every week. The automation rules are a game changer.",
                "Best purchase this year. ROI was visible within a month. The team adopted it immediately.",
            ],
            "fr": [
                "L'intégration était fluide et l'interface intuitive. Le support nous a aidés à migrer.",
                "Solide et fiable. Les intégrations ont fonctionné immédiatement. Je recommande pour petites équipes.",
                "J'adore. Ça m'a fait gagner des heures chaque semaine. Les règles d'automatisation sont géniales.",
                "Meilleur achat de l'année. ROI visible en un mois. Toute l'équipe a adopté l'outil.",
            ],
        },
    },
    "neutral": {
        "titles": {
            "en": ["Mostly good", "Just okay"],
            "fr": ["Plutôt bien", "Mitigé"],
        },
        "bodies": {
            "en": [
                "Works well 80% of the time but we hit occasional slowdowns during peak hours. Reporting could be richer.",
                "It's just okay. Does the job but nothing stands out. Considering alternatives for the price.",
            ],
            "fr": [
                "Fonctionne bien 80% du temps mais ralentissements aux heures de pointe. Reporting à enrichir.",
                "Mitigé. Ça fait le job mais rien ne se démarque. Je regarde les alternatives vu le prix.",
            ],
        },
    },
    "negative": {
        "titles": {
            "en": ["Disappointing", "Bugs everywhere"],
            "fr": ["Décevant", "Plein de bugs"],
        },
        "bodies": {
            "en": [
                "Disappointed — key features promised on the roadmap are missing. Pricing feels high for what's included.",
                "So many bugs after the last update. The dashboard doesn't load and support is slow to respond. Frustrating.",
            ],
            "fr": [
                "Décevant — des fonctionnalités clés promises sont absentes. Prix élevé pour l'offre.",
                "Énormément de bugs après la dernière mise à jour. Le tableau de bord ne charge plus. Frustrant.",
            ],
        },
    },
}
RATING_FOR_SENTIMENT = {"positive": (4, 5), "neutral": (3,), "negative": (1, 2)}


def _pick_sentiment_for_rating(rating: int) -> str:
    for sent, ratings in RATING_FOR_SENTIMENT.items():
        if rating in ratings:
            return sent
    return "neutral"

INDUSTRIES = ["SaaS", "E-commerce", "Fintech", "Healthcare", "Manufacturing", "Education", "Retail", "Media"]
SOURCES = ["organic", "referral", "ads", "event"]
STATUSES = ["new", "contacted", "qualified", "won", "lost"]

PAGES = ["/", "/pricing", "/product", "/docs", "/blog/launch", "/contact", "/signup"]


def daterange(start: datetime, end: datetime):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def fmt_money(v: float) -> str:
    return f"{v:.2f}"


# ───────────────────────────────────────────────────────────────
# 1. ORDERS  (with deliberate anomalies on specific days)
# ───────────────────────────────────────────────────────────────
def gen_orders() -> int:
    rows = []
    oid = 50000
    # baseline revenue per channel/day
    base = {"web": 4200, "mobile": 2600, "marketplace": 1800}
    for d in daterange(START, END):
        # weekday seasonality: weekends lighter
        dow_mult = 0.65 if d.weekday() >= 5 else 1.0
        for ch in CHANNELS:
            for region in REGIONS:
                region_mult = {"FR": 1.0, "EU": 1.1, "UK": 0.9, "US": 1.2}[region]
                mean = base[ch] * region_mult * dow_mult
                orders_n = max(1, int(mean / random.uniform(70, 130)))
                for _ in range(orders_n):
                    oid += 1
                    gross = round(random.uniform(40, 480), 2)
                    discount = round(gross * random.choice([0, 0, 0, 0.1, 0.2]), 2)
                    net = round(gross - discount, 2)
                    rows.append({
                        "order_id": f"ORD-{oid}",
                        "customer_id": f"C-{random.randint(10000, 49999)}",
                        "order_date": d.date().isoformat(),
                        "channel": ch,
                        "region": region,
                        "currency": "EUR",
                        "gross_revenue_eur": fmt_money(gross),
                        "discount_eur": fmt_money(discount),
                        "net_revenue_eur": fmt_money(net),
                        "units": random.randint(1, 4),
                    })

    # ── Injected ANOMALIES (so detection has real targets) ─────
    # 1) US marketplace spike on 2026-07-18 (a flash sale)
    spike_date = datetime(2026, 7, 18).date().isoformat()
    for _ in range(240):
        oid += 1
        gross = round(random.uniform(60, 500), 2)
        rows.append({
            "order_id": f"ORD-{oid}", "customer_id": f"C-{random.randint(10000, 49999)}",
            "order_date": spike_date, "channel": "marketplace", "region": "US", "currency": "EUR",
            "gross_revenue_eur": fmt_money(gross), "discount_eur": "0.00",
            "net_revenue_eur": fmt_money(gross), "units": random.randint(1, 5),
        })
    # 2) FR web drop on 2026-07-25 (outage day)
    drop_date = datetime(2026, 7, 25).date().isoformat()
    rows = [r for r in rows if not (r["order_date"] == drop_date and r["channel"] == "web" and r["region"] == "FR")]
    # add a tiny trickle to represent the outage
    for _ in range(4):
        oid += 1
        rows.append({
            "order_id": f"ORD-{oid}", "customer_id": f"C-{random.randint(10000, 49999)}",
            "order_date": drop_date, "channel": "web", "region": "FR", "currency": "EUR",
            "gross_revenue_eur": "55.00", "discount_eur": "0.00", "net_revenue_eur": "55.00", "units": 1,
        })

    _write("orders.csv", rows, list(rows[0].keys()))
    return len(rows)


# ───────────────────────────────────────────────────────────────
# 2. SUPPORT TICKETS  (bilingual)
# ───────────────────────────────────────────────────────────────
def gen_tickets() -> int:
    rows = []
    tid = 20000
    cats = list(SUBJECTS.keys())
    weights = [0.20, 0.22, 0.15, 0.12, 0.18, 0.13]
    n = 520
    for _ in range(n):
        tid += 1
        cat = random.choices(cats, weights=weights, k=1)[0]
        lang = random.choices(TICKET_LANGS, weights=[0.55, 0.45], k=1)[0]
        subj = random.choice(SUBJECTS[cat][lang])
        desc = DESCS[cat][lang].format(
            amt=random.randint(20, 400), exp=random.randint(10, 300),
            oid=random.randint(50000, 99999), dt="2026-07-20", delay=random.randint(2, 9),
        )
        created = START + timedelta(
            days=random.randint(0, DAYS - 1),
            hours=random.randint(8, 20),
            minutes=random.randint(0, 59),
        )
        # urgent bugs & billing more likely to breach SLA
        sla = (cat == "bug" and random.random() < 0.35) or (cat == "billing" and random.random() < 0.25)
        rows.append({
            "ticket_id": f"TKT-{tid}",
            "customer_id": f"C-{random.randint(10000, 49999)}",
            "created_at": created.isoformat(timespec="seconds"),
            "channel": random.choice(TICKET_CHANNELS),
            "language": lang,
            "subject": subj,
            "description": desc,
            "status": random.choices(["open", "pending", "solved"], weights=[0.35, 0.25, 0.40])[0],
            "sla_breached": str(sla).lower(),
        })
    _write("support_tickets.csv", rows, list(rows[0].keys()))
    return len(rows)


# ───────────────────────────────────────────────────────────────
# 3. PRODUCT REVIEWS  (bilingual)
# ───────────────────────────────────────────────────────────────
def gen_reviews() -> int:
    rows = []
    rid = 30000
    n = 340
    for _ in range(n):
        rid += 1
        pid, pname = random.choice(PRODUCTS)
        lang = random.choice(TICKET_LANGS)
        # pick a sentiment first (so text & rating stay coherent),
        # then a rating from that sentiment bucket.
        if pid == "P-1006":  # buggy product → mostly negative
            sent = random.choices(["negative", "neutral", "positive"], weights=[0.7, 0.2, 0.1])[0]
        else:
            sent = random.choices(["positive", "neutral", "negative"], weights=[0.6, 0.25, 0.15])[0]
        rating = random.choice(RATING_FOR_SENTIMENT[sent])
        created = START + timedelta(days=random.randint(0, DAYS - 1))
        rows.append({
            "review_id": f"REV-{rid}",
            "product_id": pid,
            "product_name": pname,
            "created_at": created.isoformat(timespec="hours"),
            "rating": rating,
            "language": lang,
            "title": random.choice(REVIEW[sent]["titles"][lang]),
            "body": random.choice(REVIEW[sent]["bodies"][lang]),
            "verified": str(random.random() < 0.6).lower(),
        })
    _write("product_reviews.csv", rows, list(rows[0].keys()))
    return len(rows)


# ───────────────────────────────────────────────────────────────
# 4. WEB ANALYTICS  (daily aggregates; shares the spike/drop)
# ───────────────────────────────────────────────────────────────
def gen_web() -> int:
    rows = []
    for d in daterange(START, END):
        dow_mult = 0.7 if d.weekday() >= 5 else 1.0
        for page in PAGES:
            for country in REGIONS:
                for device in ["desktop", "mobile", "tablet"]:
                    base_sessions = {"desktop": 320, "mobile": 280, "tablet": 60}[device]
                    page_mult = {"/": 1.6, "/pricing": 1.0, "/product": 1.1, "/docs": 0.7,
                                 "/blog/launch": 0.5, "/contact": 0.4, "/signup": 0.6}[page]
                    s = int(base_sessions * page_mult * dow_mult * random.uniform(0.85, 1.15))
                    pv = int(s * random.uniform(1.2, 2.1))
                    # surge on the launch blog on/after July 18 (aligns with flash sale)
                    if page == "/blog/launch" and d.date().isoformat() == "2026-07-18":
                        s = int(s * 3.5)
                        pv = int(pv * 3.2)
                    rows.append({
                        "event_date": d.date().isoformat(),
                        "page_path": page,
                        "country": country,
                        "device": device,
                        "sessions": s,
                        "pageviews": pv,
                        "bounce_rate": f"{random.uniform(28, 62):.2f}",
                        "avg_session_sec": f"{random.uniform(60, 320):.2f}",
                    })
    _write("web_analytics.csv", rows, list(rows[0].keys()))
    return len(rows)


# ───────────────────────────────────────────────────────────────
# 5. CRM LEADS  (bilingual notes)
# ───────────────────────────────────────────────────────────────
def gen_leads() -> int:
    rows = []
    lid = 70000
    n = 180
    lead_notes_en = [
        "Spoke with {role}. Budget confirmed for Q3. Currently using {comp}.",
        "Inbound from {src}. Evaluating alternatives to {comp}. Wants demo next week.",
        "Met at {src}. Large team, ~{sz} people. Interested in annual plan.",
        "Referred by existing customer. Needs SSO and the API. Decision by end of quarter.",
        "Pricing objection. Smaller team than expected. Nurture for next cycle.",
    ]
    lead_notes_fr = [
        "Échangé avec le/la {role}. Budget confirmé pour T3. Utilise actuellement {comp}.",
        "Entrant via {src}. Évalue des alternatives à {comp}. Démo la semaine prochaine.",
        "Rencontré via {src}. Grande équipe, ~{sz} personnes. Intéressé par plan annuel.",
        "Recommandé par un client. Besoin de SSO et de l'API. Décision fin de trimestre.",
        "Objection sur le prix. Équipe plus petite que prévu. À cultiver pour le prochain cycle.",
    ]
    roles = ["CTO", "Head of Ops", "VP Engineering", "Ops Manager", "COO"]
    comps = ["Salesforce", "HubSpot", "Notion", "Monday", "Zapier", "Asana"]
    sizes = ["8", "45", "120", "350", "1200", "60", "15", "500"]
    for _ in range(n):
        lid += 1
        lang = random.choice(["en", "fr"])
        created = START + timedelta(days=random.randint(0, DAYS - 1))
        if lang == "en":
            notes = random.choice(lead_notes_en).format(
                role=random.choice(roles), src=random.choice(SOURCES),
                comp=random.choice(comps), sz=random.choice(sizes))
        else:
            notes = random.choice(lead_notes_fr).format(
                role=random.choice(roles), src=random.choice(SOURCES),
                comp=random.choice(comps), sz=random.choice(sizes))
        rows.append({
            "lead_id": f"LD-{lid}",
            "company_name": f"{random.choice(['Northwind','Acme','Lumen','Vortex','Bright','Cobalt','Helix','Vertex'])} {random.choice(['Inc','GmbH','SAS','Ltd','BV'])}",
            "industry": random.choice(INDUSTRIES),
            "region": random.choice(REGIONS),
            "created_at": created.isoformat(timespec="hours"),
            "source": random.choice(SOURCES),
            "status": random.choices(STATUSES, weights=[0.30, 0.25, 0.20, 0.12, 0.13])[0],
            "est_value_eur": str(round(random.uniform(2000, 75000), 2)),
            "notes": notes,
        })
    _write("crm_leads.csv", rows, list(rows[0].keys()))
    return len(rows)


# ── helper ─────────────────────────────────────────────────────
def _write(name: str, rows: list[dict], fieldnames: list[str]) -> None:
    path = OUT / name
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path.name}: {len(rows):>6} rows")


def write_readme(counts: dict[str, int]) -> None:
    total = sum(counts.values())
    note = (
        "# Seed data — SAMPLE / DEMO ONLY\n\n"
        f"{DEMO_NOTE}\n\n"
        "Synthetically generated by `scripts/generate_seed.py` (seed=42) so the\n"
        "pipeline and its tests are fully reproducible. No real persons, companies,\n"
        "orders, or metrics are represented.\n\n"
        "Deliberate anomalies are embedded for the anomaly-detection enricher:\n"
        "  - US marketplace revenue SPIKE on 2026-07-18 (flash sale)\n"
        "  - FR web revenue DROP on 2026-07-25 (outage)\n"
        "  - Product P-1006 has artificially poor ratings (buggy release)\n\n"
        "## Row counts\n"
    )
    for k, v in counts.items():
        note += f"- {k}: {v:,}\n"
    note += f"- **total**: {total:,}\n"
    (OUT / "README.md").write_text(note, encoding="utf-8")
    print(f"  wrote README.md (total {total:,} rows)")


if __name__ == "__main__":
    print(f"Generating demo seed data in {OUT} ...")
    counts = {
        "orders.csv": gen_orders(),
        "support_tickets.csv": gen_tickets(),
        "product_reviews.csv": gen_reviews(),
        "web_analytics.csv": gen_web(),
        "crm_leads.csv": gen_leads(),
    }
    write_readme(counts)
    print("Done.")
