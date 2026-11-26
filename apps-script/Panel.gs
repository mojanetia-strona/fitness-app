/* ================= PANEL DOMU (dom.ldesk.pl, 26.11) ================= */
// Osobny plik, niezależny od Żelaznego Dziennika. Kod.gs wywołuje tylko panelGet_ (doGet) i espPanel_ (espSync_).
//
// Polecenia trafiają do zakładki „Panel” (kolejka): Czas | Polecenie | Parametry (JSON) | Status | Źródło.
// Wpisuje je aplikacja dom.ldesk.pl albo Claude (zwykły nowy wiersz z pustym Statusem). Płytka odbiera je przy
// synchronizacji; arkusz od razu ją szturcha, a wyzwalacz panelTick (co minutę) szturcha, gdy coś czeka.
//
// Polecenia: swiatla {room: work|bed|bath|all, on, k?, dim?} · lampa {key: lamp_salon|kitchen_led|desk_light, on}
//   wszystko_off {} · czytanie {} · temp {room: salon|sypialnia, t} · budzenie {on: false|true} · robot {akcja: start|dock}
//   wyjscie {} · powrot {} (te dwa jak skróty iPhone'a: zdarzenie wyjścia/powrotu)

const PANEL_SHEET = 'Panel';
const PANEL_POKE = 'http://77.252.240.204:18089/teraz?k=';

function panelSheet_(ss) {
  let sh = ss.getSheetByName(PANEL_SHEET);
  if (!sh) {
    sh = ss.insertSheet(PANEL_SHEET);
    sh.appendRow(['Czas', 'Polecenie', 'Parametry', 'Status', 'Źródło']);
    sh.setFrozenRows(1);
    sh.getRange('A:A').setNumberFormat('d mmm yyyy HH:mm:ss');
  }
  return sh;
}

// ?action=panel&token=…            → stan domu
// ?action=panel&cmd=swiatla&a={...}  → polecenie (+ stan). Uwaga: parametr „c” jest zastrzeżony przez Google, stąd „cmd”.
function panelGet_(ss, p) {
  const out = { ok: true };
  const c = p.cmd || p.polecenie;
  if (c) out.cmd = panelCmd_(ss, String(c), p.a || '{}', 'panel');
  else if (p.fresh === '1') {  // otwarcie panelu: stan starszy niż 30 s → szturchnij płytkę, żeby przysłała świeży
    const pr = PropertiesService.getScriptProperties();
    const stAt = Number(pr.getProperty('ESP_STATE_AT') || 0), pk = Number(pr.getProperty('PANEL_POKE_AT') || 0);
    if (Date.now() - stAt > 30e3 && Date.now() - pk > 20e3) out.poked = panelPoke_();
  }
  return Object.assign(out, panelState_(ss, p.log === '1'));
}

function panelCmd_(ss, c, a, src) {
  let args = {};
  try { args = typeof a === 'string' ? JSON.parse(a) : (a || {}); } catch (e) { return { ok: false, error: 'zle parametry' }; }
  if (c === 'wyjscie' || c === 'powrot') {
    awayEvent_(ss, c === 'wyjscie' ? 'out' : 'in');
    panelPoke_();
    return { ok: true, c: c };
  }
  const allowed = ['swiatla', 'lampa', 'wszystko_off', 'czytanie', 'temp', 'budzenie', 'robot'];
  if (allowed.indexOf(c) < 0) return { ok: false, error: 'nieznane polecenie' };
  panelSheet_(ss).appendRow([new Date(), c, JSON.stringify(args), '', src || 'panel']);
  SpreadsheetApp.flush();
  panelPoke_();
  return { ok: true, c: c };
}

function panelPoke_() {
  const pr = PropertiesService.getScriptProperties();
  pr.setProperty('PANEL_POKE_AT', String(Date.now()));
  try { UrlFetchApp.fetch(PANEL_POKE + getToken_(), { muteHttpExceptions: true, followRedirects: false }); return true; }
  catch (e) { pr.setProperty('PANEL_POKE_ERR', String(e).slice(0, 200)); return false; }
}

// Wołane z espSync_: zapisuje stan płytki i oddaje oczekujące polecenia (najwyżej 10 naraz, starsze niż 30 min odrzuca).
function espPanel_(ss, p) {
  const pr = PropertiesService.getScriptProperties();
  if (p.st) { pr.setProperty('ESP_STATE', String(p.st).slice(0, 8000)); pr.setProperty('ESP_STATE_AT', String(Date.now())); }
  const sh = ss.getSheetByName(PANEL_SHEET);
  if (!sh || sh.getLastRow() < 2) return {};
  const n = Math.min(50, sh.getLastRow() - 1), r0 = sh.getLastRow() - n + 1;
  const rows = sh.getRange(r0, 1, n, 4).getValues();
  const cmds = [], now = Date.now(), stamp = Utilities.formatDate(new Date(), TZ, 'HH:mm:ss');
  rows.forEach((r, i) => {
    if (String(r[3]).trim() !== '' || !r[1]) return;
    const t = r[0] instanceof Date ? r[0].getTime() : now;
    const cell = sh.getRange(r0 + i, 4);
    if (now - t > 30 * 60e3) { cell.setValue('za stare, pominięte'); return; }
    if (cmds.length >= 10) return;
    let a = {};
    try { a = JSON.parse(String(r[2] || '{}')); } catch (e) { cell.setValue('złe parametry'); return; }
    cmds.push({ c: String(r[1]).trim(), a: a });
    cell.setValue('wysłane do płytki ' + stamp);
  });
  return cmds.length ? { cmds: cmds } : {};
}

function panelState_(ss, withLog) {
  const pr = PropertiesService.getScriptProperties();
  let st = null;
  try { st = JSON.parse(pr.getProperty('ESP_STATE') || 'null'); } catch (e) { }
  const out = { st: st, stAt: Number(pr.getProperty('ESP_STATE_AT') || 0), last: Number(pr.getProperty('ESP_LAST') || 0), now: Date.now() };
  try { const aw = pr.getProperty('AWAY_LAST'); if (aw) out.away = JSON.parse(aw); } catch (e) { }
  const sh = ss.getSheetByName(PANEL_SHEET);
  if (sh && sh.getLastRow() > 1) {
    const n = Math.min(8, sh.getLastRow() - 1);
    out.cmds = sh.getRange(sh.getLastRow() - n + 1, 1, n, 5).getValues().reverse()
      .map(r => ({ t: r[0] instanceof Date ? r[0].getTime() : 0, c: r[1], a: String(r[2]), s: String(r[3]), z: r[4] }));
  }
  if (withLog) {
    const lg = ss.getSheetByName('Dom');
    if (lg && lg.getLastRow() > 1) {
      const n = Math.min(40, lg.getLastRow() - 1);
      out.log = lg.getRange(lg.getLastRow() - n + 1, 1, n, 2).getValues().reverse()
        .map(r => [r[0] instanceof Date ? r[0].getTime() : 0, String(r[1]).slice(0, 600)]);
    }
  }
  return out;
}

// Wyzwalacz co minutę (ustaw raz: panelUstaw). Polecenia wpisane wprost do zakładki (np. przez Claude) nie szturchają
// płytki same, więc tu: jeśli coś czeka, a ostatnie szturchnięcie było ponad 50 s temu, szturchamy.
function panelTick() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(PANEL_SHEET);
  if (!sh || sh.getLastRow() < 2) return;
  const n = Math.min(20, sh.getLastRow() - 1);
  const pending = sh.getRange(sh.getLastRow() - n + 1, 2, n, 3).getValues().some(r => r[0] && String(r[2]).trim() === '');
  if (!pending) return;
  const last = Number(PropertiesService.getScriptProperties().getProperty('PANEL_POKE_AT') || 0);
  if (Date.now() - last > 50e3) panelPoke_();
}

function panelUstaw() {
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'panelTick').forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('panelTick').timeBased().everyMinutes(1).create();
  panelSheet_(SpreadsheetApp.getActiveSpreadsheet());
}

// Test z edytora: czy arkusz potrafi szturchnąć płytkę z zewnątrz (wynik w dzienniku wykonania).
function panelTestSzturchniecia() {
  const r = UrlFetchApp.fetch(PANEL_POKE + getToken_(), { muteHttpExceptions: true });
  Logger.log('kod ' + r.getResponseCode() + ': ' + r.getContentText());
}
