# Stream Manager UI — Issue #50

Tài liệu handoff cho thiết kế Stream Manager Multistream đã được duyệt trong issue #50.

## Nguồn UI chính

MagicPath là **visual source of truth** cho layout, hierarchy, spacing và interaction:
https://www.magicpath.ai/files/456063904129388544

Component cần refer: **Stream Manager V2 — Multi Stream + Preflight + Stream Activity**.

Dev không tự thay đổi UX chỉ vì tài liệu Markdown không mô tả chi tiết pixel/layout. Khi có khác biệt giữa mockup và text:
- MagicPath quyết định phần visual/interaction;
- tài liệu này quyết định behavior/state/contract;
- backend contract #48 quyết định dữ liệu/runtime semantics.

## Phạm vi V2

Page gồm:
1. OBS Session summary.
2. Shared Preflight / Stream readiness.
3. Danh sách destination độc lập.
4. Per-destination Start/Stop và runtime status.
5. Add/Edit/Delete destination.
6. Stream Activity.
7. Service/backend unavailable, loading/reconcile và error states.

Xem `ui-spec.md` và `states.md` trước khi implement.

Related: #48 backend contract, #50 design ticket.
