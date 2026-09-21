from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEWPORT_FIX = ROOT / "resources" / "views" / "components" / "sidebar_viewport_fix.html"
VIEWPORT_CSS = ROOT / "resources" / "assets" / "css" / "sidebars.css"


def _source() -> str:
    return VIEWPORT_FIX.read_text(encoding="utf-8")


def _css_source() -> str:
    return VIEWPORT_CSS.read_text(encoding="utf-8")


def test_mobile_portal_uses_full_width_off_canvas_navigation():
    source = _source()
    css = _css_source()

    assert "@media (max-width: 760px)" in css
    assert "--nexora-sidebar-width: 0px !important" in css
    assert "width: min(86vw, 320px) !important" in css
    assert "transform: translateX(calc(-100% - 18px)) !important" in css
    assert ".nx-role-sidebar-shell.is-mobile-open .nx-role-sidebar" in css
    assert "margin-left: 0 !important" in css
    assert "width: 100% !important" in css
    assert "<style" not in source.lower()
    assert "nx-mobile-menu-button" in source
    assert "data-nx-mobile-menu" in source
    assert "shell.classList.toggle('is-mobile-open', open)" in source
    assert "backdrop.addEventListener('click'" in source
    assert "event.key === 'Escape'" in source


def test_mobile_portal_keeps_confirmed_phone_safety_guards():
    source = _source()
    css = _css_source()

    assert "<style" not in source.lower()
    assert ".student-logbook-table-wrap" in css
    assert ".student-gradebook-table-wrap" in css
    assert "overflow-x: auto !important" in css
    assert ".student-logbook-icon-button" in css
    assert ".admin-students-page .btn-more" in css
    assert "min-width: 44px !important" in css
    assert ".crop-area" in css
    assert "max-height: 60dvh !important" in css
    assert ".flash-popup" in css
    assert "min-width: 0 !important" in css
    assert ".student-main-content .edit-row" in css
    assert "flex-direction: column !important" in css
