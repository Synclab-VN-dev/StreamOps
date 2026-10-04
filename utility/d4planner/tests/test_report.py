from d4planner.report.poc_report import render_report


def test_report_does_not_infer_gameplay_semantics():
    events = [
        {
            "sessionId": "poc",
            "sequence": 1,
            "timestamp": "2026-10-04T19:30:21.123+07:00",
            "process": "diablo iv",
            "windowTitle": "Diablo IV",
            "text": "EQUIPPED",
            "rawSpeech": ["EQUIPPED"],
        }
    ]
    report = render_report(events)
    assert "Diablo-context events: **1**" in report
    assert "Event ordering: **PASS**" in report
    assert "| Equipped marker | NOT_EVALUATED | |" in report
    assert "**Status: NOT_EVALUATED**" in report
