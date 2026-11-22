/* ================= STRAŻNIK DOMU ================= */
// Osobny plik, niezależny od Kod.gs (Żelazny Dziennik). Co 10 min czyta zakładkę „Dom” i zgłasza tylko prawdziwe awarie:
//  - płytka milczy (brak wpisu stanu „ok …” od 45 min),
//  - grzejnik nie odpowiada w 2 kolejnych odczytach stanu (ok. 30–60 min),
//  - Qingping nie podaje danych w 2 kolejnych odczytach stanu,
//  - nawilżacz / oczyszczacz / robot „nie odpowiada” co najmniej 3 razy w ciągu godziny (pojedyncze zrywy Wi-Fi pomija),
//  - bateria zasłony poniżej 15%.
// Awaria = mail na glowadzkilukasz@gmail.com + zadanie na liście „zadania”. Gdy problem zniknie: zadanie odhacza się samo, bez maila.
// Wymaga usługi Tasks API (jest już włączona dla zadań z kalendarza). Uruchom raz z edytora: straznikUstaw.

const STRAZ_TO = 'glowadzkilukasz@gmail.com';
const STRAZ_DEV = { bed_hum: 'nawilżacz w sypialni', salon_hum: 'nawilżacz w salonie', salon_pur: 'oczyszczacz w salonie', robot: 'robot sprzątający' };

function straznik() {
  const ss = SpreadsheetApp.getActiveSpreadsheet(), sh = ss.getSheetByName('Dom');
  if (!sh || sh.getLastRow() < 2) return;
  const n = Math.min(300, sh.getLastRow() - 1);
  const rows = sh.getRange(sh.getLastRow() - n + 1, 1, n, 2).getValues().filter(r => r[0] instanceof Date);
  const now = Date.now(), problems = {};

  // 1. płytka milczy: ostatni wpis stanu (co 30 min) albo start płytki
  const status = rows.filter(r => /^ok RH /.test(String(r[1])) || /start v\d/.test(String(r[1])));
  const last = status.length ? status[status.length - 1][0].getTime() : 0;
  if (now - last > 45 * 60e3) {
    problems.plytka = { t: 'Płytka domu nie odpowiada', d: 'Ostatni wpis stanu: ' + (last ? Utilities.formatDate(new Date(last), TZ, 'd.MM HH:mm') : 'brak') +
      '. Automatyka domu nie działa. Sprawdzić, czy płytka ma prąd i Wi-Fi; najprościej wyjąć ją z gniazdka na 5 s.' };
  }

  // 2. i 3. dwa ostatnie wpisy stanu „ok …”
  const ok = rows.filter(r => /^ok RH /.test(String(r[1]))).slice(-2).map(r => String(r[1]));
  if (ok.length === 2) {
    [['salon', 'Grzejnik w salonie'], ['bed', 'Grzejnik w sypialni']].forEach(([k, name]) => {
      if (ok.every(l => new RegExp('\\b' + k + ' \\?').test(l))) {
        problems['trv_' + k] = { t: name + ' nie odpowiada', d: name + ' od ok. godziny nie odpowiada przez bramkę „Termostaty”. Sprawdzić baterie głowicy i czy bramka ma zasilanie.' };
      }
    });
    if (ok.every(l => /^ok RH None /.test(l))) {
      problems.qingping = { t: 'Qingping nie podaje odczytów', d: 'Monitor powietrza w salonie od ok. godziny nie odpowiada. Salon grzeje się wtedy według samej głowicy. Sprawdzić zasilanie i Wi-Fi Qingpinga.' };
    }
  }

  // 4. urządzenia Xiaomi: co najmniej 3 „nie odpowiada” w ostatniej godzinie, ostatni nie starszy niż 20 min
  Object.keys(STRAZ_DEV).forEach(d => {
    const hits = rows.filter(r => now - r[0].getTime() < 60 * 60e3 && String(r[1]).indexOf(d + ' nie odpowiada') >= 0);
    if (hits.length >= 3 && now - hits[hits.length - 1][0].getTime() < 20 * 60e3) {
      problems['dev_' + d] = { t: STRAZ_DEV[d].charAt(0).toUpperCase() + STRAZ_DEV[d].slice(1) + ' nie odpowiada', d: 'Płytka nie może połączyć się z urządzeniem (' + d + ') od dłuższego czasu. Sprawdzić, czy jest podłączone do prądu i w sieci Wi-Fi.' };
    }
  });

  // 5. baterie zasłon (wpis raz na dobę)
  const cur = rows.filter(r => /zaslony: lewa bateria/.test(String(r[1]))).slice(-1)[0];
  if (cur) {
    const m = String(cur[1]).match(/lewa bateria (\d+)%.*prawa bateria (\d+)%/);
    if (m && Math.min(+m[1], +m[2]) < 15) {
      problems.zaslony = { t: 'Naładować zasłony', d: 'Bateria zasłon: lewa ' + m[1] + '%, prawa ' + m[2] + '%. Naładować przez USB-C, zanim przestaną się zasuwać.' };
    }
  }

  straznikZglos_(problems);
}

function straznikZglos_(problems) {
  const props = PropertiesService.getScriptProperties();
  const open = JSON.parse(props.getProperty('STRAZ_OPEN') || '{}');
  const listId = zadaniaListaId_();
  // nowe awarie: mail + zadanie
  Object.keys(problems).forEach(k => {
    if (open[k]) return;
    const p = problems[k];
    MailApp.sendEmail({ to: STRAZ_TO, subject: 'Dom: ' + p.t, body: p.d + '\n\nZadanie naprawy jest na liście „zadania”. Gdy problem zniknie, odhaczy się samo.', name: 'Strażnik domu' });
    let id = null;
    if (listId) {
      try { id = Tasks.Tasks.insert({ title: 'Naprawić: ' + p.t.toLowerCase(), notes: p.d + '\n(mail „Dom: ' + p.t + '” wysłany ' + Utilities.formatDate(new Date(), TZ, 'd.MM HH:mm') + ')' }, listId).id; } catch (e) { }
    }
    open[k] = id || true;
  });
  // naprawione: zadanie odhaczone, bez maila
  Object.keys(open).forEach(k => {
    if (problems[k]) return;
    if (listId && typeof open[k] === 'string') {
      try { Tasks.Tasks.patch({ status: 'completed' }, listId, open[k]); } catch (e) { }
    }
    delete open[k];
  });
  props.setProperty('STRAZ_OPEN', JSON.stringify(open));
}

// Uruchom raz z edytora: wyzwalacz co 10 min.
function straznikUstaw() {
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'straznik').forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('straznik').timeBased().everyMinutes(10).create();
  straznik();
  Logger.log('strażnik działa, otwarte awarie: ' + PropertiesService.getScriptProperties().getProperty('STRAZ_OPEN'));
}
