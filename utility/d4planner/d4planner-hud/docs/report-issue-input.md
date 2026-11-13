# Report form input and Vietnamese IME

The report form must preserve the text committed by the input method, including
Vietnamese accents. It cannot infer whether an English-looking word was intended
as English or as a Telex key sequence. Do not normalize, transliterate, disable
composition, or reconstruct words from keydown events.

When entering English technical text, select **English** explicitly in the Windows
input selector (Win+Space). Select Vietnamese Telex again when composing Vietnamese.
Check the active input source on both ends of a remote session. Ctrl+Shift is not a
reliable universal instruction because the configured switching shortcut can vary.
See [Microsoft's Vietnamese IME documentation](https://learn.microsoft.com/en-us/globalization/input/vietnamese-ime).

## Isolating a report of lost characters

1. Record the application build, Windows and WebView2 versions, IME product/version
   and settings, and the remote client's version, keyboard mode and input source.
2. Use synthetic text, with a trailing space to commit the composition:
   `tieengs vieetj issue expected `.
3. Compare Title, Actual, Expected and Steps to Reproduce against an ordinary
   textarea in the same WebView and Notepad. Use the same keys and active IME for
   each control. A test-only textarea can be appended outside the React root using
   DevTools; do not ship that control in the application.
4. Repeat with English and Vietnamese Telex, first through the VM console and then
   through the actual remote client. Vary typing speed separately from language.
   Record RustDesk Map, Translate and Legacy separately; they are different input
   paths, not interchangeable evidence. See the [RustDesk keyboard FAQ](https://github.com/rustdesk/rustdesk/wiki/FAQ).
5. Capture `keydown`, `beforeinput`, `input`, and composition events, final DOM
   values, focus and selection. Generate input through the native keyboard path;
   JavaScript value assignment or Playwright `fill()` does not exercise the IME.
   Keep generated traces and screenshots outside the repository and use no real
   credentials or user report text in the probe.
6. Only treat a discrepancy attributable to the HUD as a reproduced application
   defect. Turn its event sequence into a failing regression before changing
   production handlers, then rerun the native path after the fix.

## Baseline investigation for #194

On 9 November 2026, baseline `bf086db94f86a35526c1f1f47ac29e1956dc9f44`
was tested in the actual Tauri HUD on Windows 11 Enterprise LTSC Evaluation build
26100, WebView2 157.0.4341.42, with Microsoft Vietnamese Telex and English US.
RustDesk 1.5.1 ran between a Linux client using US input and the Windows guest.
The HUD ran standalone in viewer mode; this was not a packaged installer test or
an end-to-end submission to GitHub.

Console input used QEMU keyboard events. Remote input used native X11 keyboard
events through a real RustDesk connection. DevTools only focused/read controls and
recorded events. Key hold was 10 ms; configured gaps were 35 ms and 180 ms, plus
transport/scheduling overhead. These timings are not measured end-to-end latency.

Console and RustDesk Map each covered 20 cases: two input languages, two speeds,
and all four report fields plus the ordinary textarea. Every report value matched
its corresponding control. English preserved the synthetic key sequence; Telex
produced `tiếng việt isue ễpcted ` in all five controls. Notepad with Telex produced
the same text. Thus missing letters/added accents alone do not establish corruption
inside the report form.

Six additional RustDesk Translate cases (Telex selected on the guest, both speeds,
Title/Actual/ordinary textarea) preserved the raw synthetic sequence with no
composition events, again identically across controls. This demonstrates why the
remote keyboard mode must be recorded. It does not establish Vietnamese composition
support through Translate when the sending client also uses a Vietnamese IME.

The Legacy probe did not deliver input events to the ordinary textarea; its result
is inconclusive and excluded from the successful cases. Legacy needs a separately
verified input path before drawing conclusions about the form.

`src/ReportIssue.ime.test.tsx` adds seven regression guards for all four fields,
composition across parent rerenders, final input on either side of compositionend,
cancellation/deletion, and exact committed text passed to the submission bridge.
These DOM tests already pass on the baseline: they protect the existing contract,
not a demonstrated red-to-green fix, and do not replace native IME tests.

The original machine A's exact IME/settings, WebView2 version and RustDesk
version/mode have not been established, and its encrypted diagnostic attachment
has not been inspected. The observations above do not close #194 or prove all IMEs
and remote configurations work. Reproduce its exact configuration and compare
the controls before deciding whether a production code change is warranted.
