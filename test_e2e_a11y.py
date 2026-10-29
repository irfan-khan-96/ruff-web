"""
Accessibility audit: run axe-core on every page, logged out and logged in, in
light and dark themes, and fail on any WCAG violation it reports.

Needs Playwright with Chromium and network access (axe-core loads from
jsDelivr). Skipped when Playwright is not installed.
"""

import pytest

from conftest import login

AXE_URL = "https://cdn.jsdelivr.net/npm/axe-core@4.14.0/axe.min.js"


@pytest.fixture(scope="module")
def seeded(live_server):
    """A user with one of everything, so every page has real content."""
    from models import db, User, Stash, RelaySession, RelayEntry

    username = live_server.create_user("a11y")

    def seed():
        user = User.query.filter_by(username=username).first()
        stash = Stash(body="Groceries\nMilk and eggs\n[ ] milk\n[x] eggs", user_id=user.id)
        db.session.add(stash)
        db.session.flush()
        stash.add_tag("home")
        relay = RelaySession(code="A11Y01", owner_id=user.id, title="Story", prompt="Once upon a time")
        db.session.add(relay)
        db.session.flush()
        db.session.add(RelayEntry(session_id=relay.id, author_name=username, body="there was a cat", position=1))
        db.session.commit()
        return stash.id

    return {"username": username, "stash_id": live_server.query(seed)}


def _violations(page, url):
    page.goto(url)
    page.wait_for_load_state("networkidle")
    page.add_script_tag(url=AXE_URL)
    return page.evaluate("""
        axe.run(document, {resultTypes: ['violations']}).then(result =>
            result.violations.map(v =>
                `${v.id} [${v.impact}]: ${v.nodes.map(n => n.target.join(' ')).slice(0, 3).join(', ')}`))
    """)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_pages_have_no_accessibility_violations(live_server, new_page, seeded, theme):
    stash_id = seeded["stash_id"]
    public = ["/", "/login", "/signup", "/password/forgot", "/verify/resend", "/pass", "/relay/A11Y01",
              "/no-such-page"]
    private = ["/", "/stashes", "/stashes?q=nothing-matches", f"/stashes/{stash_id}", "/pass",
               f"/share/{stash_id}", "/lounge", "/relay/A11Y01"]

    # bypass_csp lets the audit inject axe; the app's own CSP is tested elsewhere
    page = new_page(bypass_csp=True, color_scheme=theme)
    page.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}'); }} catch (e) {{}}")

    found = {}
    for path in public:
        found[f"anon {path}"] = _violations(page, live_server.url + path)
    login(page, live_server, seeded["username"])
    for path in private:
        found[f"user {path}"] = _violations(page, live_server.url + path)

    assert {page_: issues for page_, issues in found.items() if issues} == {}
