# #119 CI acceptance and evidence

CI and ChatGPT own 29 of 38 checklist items. The baseline is 4/29.

Implemented: versioned candidate projector, JSON schema v1, CLI list/filter/history/export/status, idempotent SQLite materialization, additional Real-A typed parser cases, regression and snapshot UAT runner.

Evidence: tests/test_issue119_owned_items.py, tests/test_issue119_projection_migration.py, tests/test_issue119_real_a_regression.py, GitHub Actions Windows and portability jobs.

Known limits: non-equipped speech observations are NOT_CONFIRMED; tab/slot never inferred solely from CHEST labels. Partial scan does not imply complete inventory. Move/removal audit requires trusted transition evidence. The 29 acceptance checks must remain pending until individually verified.

Dev F owns real Windows A only; Owner handles manual visual verification and merge decisions. Never merge or deploy solely on CI success.
