/* Menu icon geometry from Lucide 0.468.0.
ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
*/
import { createElement } from "react";

const icons = {
  create: [
    ["rect", {"width": "18", "height": "18", "x": "3", "y": "3", "rx": "2"}],
    ["path", {"d": "M8 12h8"}],
    ["path", {"d": "M12 8v8"}],
  ],
  folder: [
    ["path", {"d": "m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"}],
  ],
  bug: [
    ["path", {"d": "m8 2 1.88 1.88"}],
    ["path", {"d": "M14.12 3.88 16 2"}],
    ["path", {"d": "M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"}],
    ["path", {"d": "M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"}],
    ["path", {"d": "M12 20v-9"}],
    ["path", {"d": "M6.53 9C4.6 8.8 3 7.1 3 5"}],
    ["path", {"d": "M6 13H2"}],
    ["path", {"d": "M3 21c0-2.1 1.7-3.9 3.8-4"}],
    ["path", {"d": "M20.97 5c0 2.1-1.6 3.8-3.5 4"}],
    ["path", {"d": "M22 13h-4"}],
    ["path", {"d": "M17.2 17c2.1.1 3.8 1.9 3.8 4"}],
  ],
  logs: [
    ["path", {"d": "M10 12v-1"}],
    ["path", {"d": "M10 18v-2"}],
    ["path", {"d": "M10 7V6"}],
    ["path", {"d": "M14 2v4a2 2 0 0 0 2 2h4"}],
    ["path", {"d": "M15.5 22H18a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v16a2 2 0 0 0 .274 1.01"}],
    ["circle", {"cx": "10", "cy": "20", "r": "2"}],
  ],
  more: [
    ["circle", {"cx": "12", "cy": "12", "r": "1"}],
    ["circle", {"cx": "12", "cy": "5", "r": "1"}],
    ["circle", {"cx": "12", "cy": "19", "r": "1"}],
  ],
  chevron: [
    ["path", {"d": "m9 18 6-6-6-6"}],
  ],
} as const;

export function MenuIcon({ name, size }: { name: keyof typeof icons; size: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    {icons[name].map(([tag, props], index) => createElement(tag, { ...props, key: index }))}
  </svg>;
}
