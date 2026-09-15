from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEWPORT_FIX = ROOT / "resources" / "views" / "components" / "sidebar_viewport_fix.html"


def _source() -> str:
    return VIEWPORT_FIX.read_text(encoding="utf-8")


def test_mobile_portal_uses_full_width_off_canvas_navigation():
    source = _source()
    mobile = source.split("@media (max-width: 760px)", 1)[1]

    assert "--nexora-sidebar-width: 0px !important" in mobile
    assert "width: min(86vw, 320px) !important" in mobile
    assert "transform: translateX(calc(-100% - 18px)) !important" in mobile
    assert ".nx-role-sidebar-shell.is-mobile-open .nx-role-sidebar" in mobile
    assert "margin-left: 0 !important" in mobile
    assert "width: 100% !important" in mobile
    assert "nx-mobile-menu-button" in source
    assert "data-nx-mobile-menu" in source
    assert "shell.classList.toggle('is-mobile-open', open)" in source
    assert "backdrop.addEventListener('click'" in source
    assert "event.key === 'Escape'" in source
    assert "--nexora-sidebar-width: 76px !important" not in mobile


def test_mobile_portal_keeps_confirmed_phone_safety_guards():
    source = _source()

    assert ".student-logbook-table-wrap" in source
    assert ".student-gradebook-table-wrap" in source
    assert "overflow-x: auto !important" in source
    assert ".student-logbook-icon-button" in source
    assert ".admin-students-page .btn-more" in source
    assert "min-width: 44px !important" in source
    assert ".crop-area" in source
    assert "max-height: 60dvh !important" in source
    assert ".flash-popup" in source
    assert "min-width: 0 !important" in source
    assert ".student-main-content .edit-row" in source
    assert "flex-direction: column !important" in source
