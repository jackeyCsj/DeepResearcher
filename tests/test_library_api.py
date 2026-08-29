from types import SimpleNamespace

from client.api.app import app, list_docs


def test_library_list_hides_legacy_reports_and_internal_fields():
    manager = SimpleNamespace(
        list_docs=lambda: [
            {
                "title": "Legacy report",
                "source_type": "report",
                "added_at": "2026-01-01T00:00:00",
                "converted_path": "converted/legacy.md",
                "content_hash": "hidden",
            },
            {
                "title": "Imported paper",
                "source_type": "pdf",
                "added_at": "2026-01-02T00:00:00",
                "original_path": "originals/paper.pdf",
                "converted_path": "converted/paper.md",
                "content_hash": "also-hidden",
            },
        ]
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(library_manager=manager)))

    assert list_docs(request, current_user=object()) == [
        {
            "title": "Imported paper",
            "source_type": "pdf",
            "added_at": "2026-01-02T00:00:00",
        }
    ]


def test_save_report_route_is_not_registered():
    routes = {
        (method, route.path)
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }
    assert ("POST", "/api/library/save-report") not in routes
