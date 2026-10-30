"""
Visual regression checks that axe-core can't do: text contrast on gradient
backgrounds (axe skips those), and layout on phones, tablets and desktops.

Runs in Chromium in light and dark themes. Skipped when Playwright isn't
installed.
"""

import re

import pytest

from conftest import login

# Buttons, chips and action links: the elements most likely to sit on gradients
CONTROLS = "button, .btn, .chip, .nav-link, .option, input[type=submit], .toast, .roster"

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
    from models import db, Stash, User

    username = live_server.create_user("visual")

    def seed():
        user = User.query.filter_by(username=username).first()
        for n in range(3):
            stash = Stash(body=f"Stash {n} with a fairly long title that has to fit on a phone\n"
                               f"Bring lunch and a jacket\n[{'x' if n == 0 else ' '}] lunch",
                          user_id=user.id)
            db.session.add(stash)
            db.session.flush()
            stash.add_tag("trips")
            stash.add_tag(f"tag{n}")
        db.session.commit()
        return Stash.query.filter_by(user_id=user.id).first().id

    return {"username": username, "stash_id": live_server.query(seed)}


def _themed_page(new_page, theme, **options):
    page = new_page(color_scheme=theme, **options)
    page.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}'); }} catch (e) {{}}")
    return page


def _settle(page):
    """Finish theme-switch colour transitions before measuring."""
    page.wait_for_load_state("networkidle")
    page.add_style_tag(content="*, *::before, *::after { transition: none !important; }")
    page.wait_for_timeout(50)


def _private_pages(seeded):
    return ["/", f"/stashes/{seeded['stash_id']}", "/stashes", "/pass", "/lounge"]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_controls_have_readable_text(live_server, new_page, seeded, theme):
    page = _themed_page(new_page, theme)
    failures = {}
    for path in ["/", "/stashes", "/login", "/login/sent", "/lounge", "/pass"]:
        page.goto(live_server.url + path)
        _settle(page)
        failures[f"anon {path}"] = _low_contrast(page)
    login(page, live_server, seeded["username"])
    for path in _private_pages(seeded):
        page.goto(live_server.url + path)
        _settle(page)
        failures[f"user {path}"] = _low_contrast(page)
    assert {where: issues for where, issues in failures.items() if issues} == {}


LAYOUT_JS = """() => {
    const visible = el => el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden';
    const tabbar = document.querySelector('.tabbar');
    return {
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        tabbar: tabbar && getComputedStyle(tabbar).display !== 'none',
        small: [...document.querySelectorAll('main button, main .btn, main input:not([type=hidden]):not([type=checkbox]):not([type=radio]), main select, main textarea, .tabbar .nav-link')]
            .filter(visible)
            .filter(el => el.getBoundingClientRect().height < 44)
            .map(el => (el.id || el.className || el.tagName) + ' ' + Math.round(el.getBoundingClientRect().height) + 'px'),
        cards: [...document.querySelectorAll('.stash-card')].map(c => [c.getBoundingClientRect().top, c.getBoundingClientRect().bottom]),
    };
}"""


@pytest.mark.parametrize("width, height, is_phone", [
    (360, 740, True),     # small phone
    (390, 844, True),     # phone
    (768, 1024, False),   # tablet, portrait
    (1024, 768, False),   # tablet, landscape
    (1280, 800, False),   # desktop
])
def test_layout_fits_every_screen(live_server, new_page, seeded, width, height, is_phone):
    page = new_page(viewport={"width": width, "height": height}, is_mobile=is_phone, has_touch=is_phone)
    login(page, live_server, seeded["username"])
    problems = {}
    for path in _private_pages(seeded):
        page.goto(live_server.url + path)
        _settle(page)
        found = page.evaluate(LAYOUT_JS)
        issues = []
        if found["overflow"] > 0:
            issues.append(f"scrolls sideways by {found['overflow']}px")
        if found["tabbar"] != is_phone:
            issues.append("tab bar " + ("missing on a phone" if is_phone else "showing on a big screen"))
        if is_phone and found["small"]:
            issues.append(f"tap targets under 44px: {found['small']}")
        for (_, bottom), (top, _) in zip(found["cards"], found["cards"][1:]):
            if bottom > top:
                issues.append("stash cards overlap")
        if issues:
            problems[path] = issues
    assert problems == {}
