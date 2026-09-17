"""Viewport smoke for TrafficLab Control (mobile + desktop).

Drives a real Chromium via Playwright against a live BFF and asserts the panel
actually renders real data at both viewports — not that the HTML merely parsed.

Run:  python control/tests/smoke_viewports.py [base_url]
Exit: 0 = all assertions passed, 1 = at least one failed.

Artifacts (screenshots) land in control/tests/artifacts/ and are gitignored;
they are evidence for the WO comment, not repo content.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9128/"
OUT = Path(__file__).resolve().parent / "artifacts"
OUT.mkdir(exist_ok=True)

VIEWPORTS = [
    # (name, width, height, is_mobile) — iPhone 14 Pro logical size, and a
    # common laptop size. The 393px case is the one that matters: the WO is
    # explicit that this panel is mobile-first.
    ("mobile", 393, 852, True),
    ("desktop", 1440, 900, False),
]

PASS = 0
FAIL = 0
NOTES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}: {detail}")
        NOTES.append(f"{name}: {detail}")


def smoke(page, label: str, width: int) -> dict:
    console_errors: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)))

    # NOTE: `wait_until="networkidle"` is WRONG for this app and will always
    # time out — the panel holds an open SSE connection to /api/v1/events for
    # its whole lifetime, so the network is never idle by design. We wait for
    # DOM ready and then for the boot fetches to settle.
    page.goto(BASE, wait_until="domcontentloaded")
    # The panel fetches five endpoints on boot; give them room to land.
    page.wait_for_timeout(3500)

    # ---- Mission Control (default tab) ----
    goal_text = page.inner_text("#goal-card")
    check(f"[{label}] Mission goal card is populated",
          len(goal_text.strip()) > 40 and "Cargando" not in goal_text,
          goal_text[:120])
    check(f"[{label}] goal card shows the running task id",
          "t_" in goal_text, goal_text[:120])

    kpis = page.eval_on_selector_all(".kpi", "els => els.map(e => e.innerText)")
    check(f"[{label}] queue KPI strip rendered (5 tiles)", len(kpis) == 5, str(kpis))

    code_tiles = page.eval_on_selector_all("#code-grid .tile h3", "els => els.map(e => e.textContent)")
    check(f"[{label}] code/CI/tests tiles rendered", len(code_tiles) >= 3, str(code_tiles))

    tests_tile = page.inner_text("#code-grid")
    check(f"[{label}] test result surfaced from the real marker",
          "pass" in tests_tile.lower(), tests_tile[:160])

    prs = page.eval_on_selector_all("#pr-grid .tile", "els => els.length")
    check(f"[{label}] open PRs listed", prs >= 1, f"{prs} tiles")
    pr_text = page.inner_text("#pr-grid")
    check(f"[{label}] PR tiles carry the HUMAN_GO merge gate",
          "HUMAN_GO" in pr_text, pr_text[:160])

    # ---- product cards: honesty about what is live ----
    prod_text = page.inner_text("#product-grid")
    check(f"[{label}] IA-VISION card present", "IA-VISION" in prod_text)
    check(f"[{label}] SUINI card present", "SUINI" in prod_text)
    check(f"[{label}] unproven targets say NOT_AVAILABLE_YET",
          "NOT_AVAILABLE_YET" in prod_text, prod_text[:200])
    live_links = page.eval_on_selector_all(
        "#product-grid a", "els => els.map(e => e.getAttribute('href'))")
    check(f"[{label}] only probed-live targets expose a link",
          all(h and h.startswith("http") for h in live_links), str(live_links))

    page.screenshot(path=str(OUT / f"{label}-mission.png"), full_page=True)

    # ---- Human-Go Inbox ----
    page.click('.tab[data-tab="humango"]')
    page.wait_for_timeout(900)
    hg = page.inner_text("#panel-humango")
    check(f"[{label}] Human-Go panel rendered", len(hg.strip()) > 40, hg[:120])
    hg_tiles = page.eval_on_selector_all("#humango-grid .tile", "els => els.length")
    check(f"[{label}] Human-Go shows at least one decision tile", hg_tiles >= 1, f"{hg_tiles}")
    page.screenshot(path=str(OUT / f"{label}-humango.png"), full_page=True)

    # ---- Evidence Timeline ----
    page.click('.tab[data-tab="timeline"]')
    page.wait_for_timeout(1200)
    tl_items = page.eval_on_selector_all(".tl-item", "els => els.length")
    check(f"[{label}] timeline rendered events", tl_items >= 1, f"{tl_items} items")
    tl_text = page.inner_text("#timeline-list")
    check(f"[{label}] timeline rows carry a task id", "t_" in tl_text, tl_text[:160])
    check(f"[{label}] heartbeats hidden by default",
          "Latido del worker" not in tl_text, tl_text[:160])
    # toggle heartbeats back on and confirm the control actually works
    page.check("#tl-heartbeats")
    page.wait_for_timeout(1500)
    tl_text_hb = page.inner_text("#timeline-list")
    check(f"[{label}] heartbeat toggle changes the feed",
          tl_text_hb != tl_text, "feed identical after toggle")
    page.uncheck("#tl-heartbeats")
    page.wait_for_timeout(900)
    page.screenshot(path=str(OUT / f"{label}-timeline.png"), full_page=True)

    # ---- Health ----
    page.click('.tab[data-tab="health"]')
    page.wait_for_timeout(900)
    health = page.inner_text("#panel-health")
    check(f"[{label}] health panel shows Hermes version", "v0.20" in health, health[:160])
    page.screenshot(path=str(OUT / f"{label}-health.png"), full_page=True)

    # ---- layout sanity: no panel may overflow the viewport horizontally ----
    # Checked on EVERY tab, not just whichever one happens to be open at the
    # end. The first version of this smoke only measured the last panel and so
    # nearly missed a 107px overflow that lived exclusively on Health.
    for tab in ("mission", "humango", "timeline", "review", "health"):
        page.click(f'.tab[data-tab="{tab}"]')
        page.wait_for_timeout(700)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"[{label}] no horizontal overflow at {width}px on tab '{tab}'",
              overflow <= 1, f"overflow={overflow}px")

    # ---- no secrets ever reach the client bundle ----
    html = page.content()
    for needle in ("ghp_", "github_pat_", "sk-", "Bearer "):
        check(f"[{label}] rendered DOM free of '{needle}'", needle not in html)
    cookie_names = [c["name"] for c in page.context.cookies()]
    check(f"[{label}] session cookie present", "control_session" in cookie_names, str(cookie_names))
    js_cookie = page.evaluate("() => document.cookie")
    check(f"[{label}] session cookie is HttpOnly (invisible to JS)",
          "control_session" not in js_cookie, js_cookie)

    check(f"[{label}] no console errors", not console_errors, "; ".join(console_errors[:3]))
    return {"viewport": label, "width": width, "console_errors": console_errors}


results = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        for label, w, h, is_mobile in VIEWPORTS:
            print(f"--- {label} {w}x{h} ---")
            ctx = browser.new_context(
                viewport={"width": w, "height": h},
                device_scale_factor=3 if is_mobile else 1,
                is_mobile=is_mobile,
                has_touch=is_mobile,
            )
            page = ctx.new_page()
            try:
                results.append(smoke(page, label, w))
            finally:
                ctx.close()
    finally:
        browser.close()

summary = {
    "base_url": BASE,
    "ran_at": datetime.now(timezone.utc).isoformat(),
    "passed": PASS,
    "failed": FAIL,
    "ok": FAIL == 0,
    "viewports": results,
    "failures": NOTES,
    "artifacts": sorted(str(p.name) for p in OUT.glob("*.png")),
}
(OUT / "smoke_result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print()
print(f"=== VIEWPORT SMOKE: {PASS} pass, {FAIL} fail ===")
sys.exit(0 if FAIL == 0 else 1)
