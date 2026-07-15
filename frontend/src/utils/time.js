/**
 * Time formatting for list rows.
 *   - today     → HH:MM
 *   - yesterday → 昨天
 *   - this year → MM-DD
 *   - older     → YYYY-MM-DD
 *
 * Accepts the backend's "YYYY-MM-DD HH:MM:SS" or ISO strings.
 */

/** @param {string|number|Date} input */
export function formatListTime(input) {
    const d = _parse(input);
    if (!d) return "";
    const now = new Date();
    const sameYear = d.getFullYear() === now.getFullYear();
    const startOfToday = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate()
    );
    const dayMs = 86400000;
    const diffDays = Math.floor((startOfToday - d) / dayMs);

    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const MM = String(d.getMonth() + 1).padStart(2, "0");
    const DD = String(d.getDate()).padStart(2, "0");

    if (diffDays <= 0) return `${hh}:${mm}`; // today
    if (diffDays === 1) return "昨天"; // yesterday
    if (sameYear) return `${MM}-${DD}`;
    return `${d.getFullYear()}-${MM}-${DD}`;
}

/** @param {string|number|Date} input */
function _parse(input) {
    if (!input) return null;
    if (input instanceof Date) return isNaN(input) ? null : input;
    const s = typeof input === "string" ? input.replace(" ", "T") : input;
    const n = Date.parse(s);
    return Number.isNaN(n) ? null : new Date(n);
}
