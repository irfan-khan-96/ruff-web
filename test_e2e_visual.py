"""
Visual regression checks that axe-core can't do: text contrast on gradient
backgrounds (axe skips those), and the stash card layout.

Runs in Chromium in light and dark themes. Skipped when Playwright isn't
installed.
"""

import re

import pytest

from conftest import login

# Buttons, chips and action links: the elements most likely to sit on gradients
CONTROLS = "button, .btn, .action-button, input[type=submit], .tag-small, .tag-button, .filter-link, .hero-pill"

CONTRAST_JS = """selector => [...document.querySelectorAll(selector)]
  .map(el => [el, (el.tagName === 'INPUT' ? el.value : el.textContent).trim()])
  .filter(([el, text]) => el.offsetParent !== null && text)
  .map(([el, text]) => {
    const s = getComputedStyle(el);
    return {
      label: (el.id ? '#' + el.id : el.className || el.tagName) + ' "' + text.slice(0, 20) + '"',
      color: s.color, background: s.backgroundColor, image: s.backgroundImage,
      large: parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && parseInt(s.fontWeight) >= 700),
    };
  })"""


def _rgba(text):
    """All colours in a CSS value as (r, g, b, alpha) floats; alpha defaults to 1."""
    return [
        (float(r), float(g), float(b), float(a) if a else 1.0)
        for r, g, b, a in re.findall(r"rgba?\(([\d.]+), ([\d.]+), ([\d.]+)(?:, ([\d.]+))?", text)
    ]


def _luminance(rgb):
    channels = [v / 255 for v in rgb[:3]]
    channels = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(a, b):
    high, low = sorted([_luminance(a), _luminance(b)], reverse=True)
    return (high + 0.05) / (low + 0.05)


def _opaque(colour):
    return colour[3] >= 0.99


def _low_contrast(page, selector=CONTROLS):
    """Elements whose text fails WCAG AA against any opaque background colour they paint."""
    failures = []
    for el in page.evaluate(CONTRAST_JS, selector):
        foreground = _rgba(el["color"])[0]
        backgrounds = [c for c in _rgba(el["image"]) if _opaque(c)] if el["image"] != "none" else []
        if not backgrounds:
            backgrounds = [c for c in _rgba(el["background"]) if _opaque(c)]
        if not backgrounds:
            continue  # transparent: covered by the axe audit
        worst = min(_contrast(foreground, bg) for bg in backgrounds)
        if worst < (3.0 if el["large"] else 4.5):
            failures.append(f"{el['label']}: {worst:.2f}:1")
    return failures


@pytest.fixture(scope="module")
def seeded(live_server):
    from models import db, Collection, Stash, User

    username = live_server.create_user("visual")

    def seed():
        user = User.query.filter_by(username=username).first()
        collection = Collection(user_id=user.id, name="School")
        db.session.add(collection)
        db.session.flush()
        for n in range(3):
            stash = Stash(title=f"Stash {n}", body="Bring lunch and a jacket", user_id=user.id,
                          collection_id=collection.id, checklist=[{"text": "lunch", "done": n == 0}])
            db.session.add(stash)
            db.session.flush()
            stash.add_tag("trips")
            stash.add_tag(f"tag{n}")
        db.session.commit()

    live_server.query(seed)
    return username


def _themed_page(new_page, theme):
    page = new_page(color_scheme=theme)
    page.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}'); }} catch (e) {{}}")
    return page


def _settle(page):
    """Finish theme-switch colour transitions before measuring."""
    page.wait_for_load_state("networkidle")
    page.add_style_tag(content="*, *::before, *::after { transition: none !important; }")
    page.wait_for_timeout(50)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_controls_have_readable_text(live_server, new_page, seeded, theme):
    page = _themed_page(new_page, theme)
    failures = {}
    for path in ["/login", "/signup", "/password/forgot", "/verify/resend", "/relay"]:
        page.goto(live_server.url + path)
        _settle(page)
        failures[f"anon {path}"] = _low_contrast(page)
    login(page, live_server, seeded)
    for path in ["/", "/stashes", "/collections", "/tags", "/import", "/share"]:
        page.goto(live_server.url + path)
        _settle(page)
        failures[f"user {path}"] = _low_contrast(page)
    assert {where: issues for where, issues in failures.items() if issues} == {}


def test_stash_cards_layout(live_server, new_page, seeded):
    page = new_page(viewport={"width": 1280, "height": 900})
    login(page, live_server, seeded)
    page.goto(live_server.url + "/stashes")
    _settle(page)
    boxes = page.evaluate("""() => [...document.querySelectorAll('.stash-card')].map(card => {
        const box = el => el.getBoundingClientRect();
        return {
          card: {top: box(card).top, bottom: box(card).bottom},
          checkboxRight: box(card.querySelector('.stash-checkbox')).right,
          infoLeft: box(card.querySelector('.stash-info')).left,
        };
    })""")
    assert len(boxes) == 3
    for card in boxes:
        # Title/content starts right after the checkbox, not floating mid-card
        assert card["infoLeft"] - card["checkboxRight"] < 40, card
    for upper, lower in zip(boxes, boxes[1:]):
        # Tilted cards (and their tape) don't overlap the next one
        assert upper["card"]["bottom"] < lower["card"]["top"], (upper, lower)
