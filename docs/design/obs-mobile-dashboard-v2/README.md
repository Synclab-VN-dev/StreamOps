# OBS Mobile Dashboard v2 — Design Handoff

Tài liệu trong thư mục này là **nguồn tham chiếu thiết kế** cho OBS Management và Streaming Management của StreamOps theo hướng mobile-first.

Kiến trúc UI được chốt thành hai page riêng:

- `/obs` — OBS Management Dashboard, chứa các card vận hành OBS và một card `Streaming` dạng summary/navigation.
- `/obs/stream` — Streaming Management, chỉ chứa các card thuộc domain streaming.

## Mục tiêu

Giữ nguyên đầy đủ capability hiện tại của OBS Management nhưng tổ chức lại information architecture để dễ dùng trên điện thoại:

- tất cả card mặc định **collapsed**;
- mỗi card collapsed phải hiển thị 3–4 thông tin summary quan trọng và **khác nhau theo ngữ cảnh của card**;
- expand card phải giữ đầy đủ thông tin và action tương ứng của UI hiện tại;
- không hard-code dữ liệu demo từ prototype vào production;
- backend/API hiện có là source of truth;
- ưu tiên tái sử dụng kiến trúc Web UI hiện tại (`obs.html`, `obs.js`, `obs-process.js`, `app.css`) thay vì đưa thêm framework chỉ để copy prototype.

## Tài liệu

- [DESIGN_SPEC.md](./DESIGN_SPEC.md): cấu trúc UX/UI, card, summary, expand behavior.
- [IMPLEMENTATION_MAPPING.md](./IMPLEMENTATION_MAPPING.md): mapping UI → API/source code hiện tại.
- [STREAMING_UI_SPEC.md](./STREAMING_UI_SPEC.md): spec riêng cho `/obs/stream` và card `Streaming` trên `/obs`.
- [LEGACY_UI_INVENTORY.md](./LEGACY_UI_INVENTORY.md): inventory capability và dữ liệu của UI hiện tại cần preserve.
- [reference/StreamOpsMobileDashboard.tsx](./reference/StreamOpsMobileDashboard.tsx): reference cho `/obs`, gồm card `Streaming` mới.
- [reference/StreamOpsStreamingOutput.tsx](./reference/StreamOpsStreamingOutput.tsx): reference cho `/obs/stream`.

## MagicPath reference

- Share URL: https://designs.magicpath.ai/v1/smart-cliff-3265
- MagicPath component: `StreamOps Mobile Dashboard`
- Component ID: `456064390102405120`
- Reference revision: `456972475197177856`

Streaming page:

- Share URL: https://designs.magicpath.ai/v1/clear-tower-8758
- MagicPath component: `StreamOps Streaming Output`
- Component ID: `456934973027528704`
- Reference revision: `456972485301243904`

## Nguyên tắc handoff

MagicPath component là **design source of truth**, không phải production architecture source of truth.

Agent triển khai phải:

1. inspect code hiện tại trước;
2. reuse API, lifecycle guard, profile store, inventory và validation hiện có;
3. preserve toàn bộ safety rule hiện tại;
4. không copy mock state, hard-coded PID/profile/source/result từ component reference;
5. cập nhật browser/E2E tests cho behavior mới.
