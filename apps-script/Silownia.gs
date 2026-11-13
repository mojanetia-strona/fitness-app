/* ================= SIŁOWNIA (Skróty iOS: przybycie / wyjście) ================= */
// ?action=gym&token=…&e=in|out&g=Nazwa siłowni. Apka przy otwarciu dopina wejście do treningu i zamyka go godziną wyjścia minus 15 min.
function gymSheet_(ss) {
  return ss.getSheetByName('Siłownia') || (function () { const s = ss.insertSheet('Siłownia'); s.appendRow(['Czas', 'Zdarzenie', 'Siłownia']); s.setFrozenRows(1); s.getRange('A:A').setNumberFormat('d mmm yyyy HH:mm'); return s; })();
}
function gymEvent_(ss, e, g) {
  e = String(e || '').toLowerCase(); if (e !== 'in' && e !== 'out') return { ok: false, error: 'e=in albo e=out' };
  gymSheet_(ss).appendRow([new Date(), e === 'in' ? 'wejście' : 'wyjście', String(g || '').slice(0, 60)]);
  return { ok: true };
}
function gymRecent_(ss) {
  const sh = ss.getSheetByName('Siłownia'); if (!sh || sh.getLastRow() < 2) return [];
  const from = Date.now() - 2 * 864e5, n = Math.min(sh.getLastRow() - 1, 200);
  return sh.getRange(sh.getLastRow() - n + 1, 1, n, 3).getValues()
    .filter(r => r[0] instanceof Date && r[0].getTime() >= from)
    .map(r => ({ t: r[0].getTime(), e: r[1] === 'wejście' ? 'in' : 'out', g: String(r[2] || '') }));
}

// Dopisuje do ostatnio dodanego wiersza w Treningi: Wejście, Wyjście, Do 1. serii (min), Siłownia.
function gymColumns_(tr, w) {
  if (tr.getRange(1, 9).getValue() === '') {
    tr.getRange(1, 9, 1, 4).setValues([['Wejście', 'Wyjście', 'Do 1. serii (min)', 'Siłownia']]).setFontWeight('bold').setBackground(C.head).setFontColor(C.headTxt);
    tr.getRange('I:J').setNumberFormat('HH:mm');
  }
  tr.getRange(tr.getLastRow(), 9, 1, 4).setValues([[w.arrive ? new Date(w.arrive) : '', w.exit ? new Date(w.exit) : '',
    w.arrive && w.first ? Math.round((w.first - w.arrive) / 60000) : '', w.gym || '']]);
}
