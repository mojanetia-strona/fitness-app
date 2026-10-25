/**
 * ŻELAZNY DZIENNIK · arkusz Google
 * 1. Wklej cały ten kod w Rozszerzenia > Apps Script (zastąp zawartość Kod.gs), zapisz.
 * 2. Wybierz funkcję "setup" i kliknij Uruchom (zaakceptuj uprawnienia).
 * 3. Wdróż > Nowe wdrożenie > typ: Aplikacja internetowa
 *    Wykonaj jako: Ja · Kto ma dostęp: Każdy > Wdróż. Skopiuj adres URL.
 * 4. W apce: Ustawienia > wklej adres i token (token pokaże się po setup,
 *    albo menu Fitness > Pokaż token).
 */

const TZ = 'Europe/Warsaw';
const SH = { DASH:'Dashboard', TRAIN:'Treningi', SETS:'Serie', WEIGHT:'Waga', MEAS:'Pomiary', REC:'Rekordy', WEEK:'Tygodnie', PLAN:'Plan', CAT:'Catering', FOOD:'Jedzenie', DIET:'Dieta', DAILY:'Codziennie', REP:'Raporty' };
const REPORT_TO = 'glowadzkilukasz@gmail.com';
const APP_URL = 'https://mojanetia-strona.github.io/fitness-app/';
const MUSCLE = { bench:'Klatka', incdb:'Klatka', flatdb:'Klatka', cablefly:'Klatka', ohp:'Barki', latraise:'Barki', facepull:'Barki', cgskull:'Triceps', ohext:'Triceps', pushdown:'Triceps', dips:'Triceps', deadlift:'Plecy', wpullup:'Plecy', bbrow:'Plecy', latpull:'Plecy', csrow:'Plecy', bbcurl:'Biceps', hammer:'Biceps', inclcurl:'Biceps', cablecurl:'Biceps', squat:'Nogi', legpress:'Nogi', legcurl:'Nogi', calf:'Nogi' };
const C = {
  ink:'#1D1D1D', muted:'#5B6770', line:'#E3E7EA', band:'#F5F5F5', head:'#00283D', headTxt:'#FFFFFF',
  accent:'#0079C2', accentSoft:'#E5F2FA', good:'#0079C2', goodSoft:'#E5F2FA', warnSoft:'#FFF3DF', bad:'#D0105B', pink:'#EE1264',
  grey:'#7FA62A'
};
const DAYCOLOR = { 'Push A':'#EE1264', 'Pull A':'#0079C2', 'Push B':'#00B8C7', 'Pull B':'#764A9E', 'Nogi':'#7FA62A' };
const MEAS_COLS = ['arm','forearm','chest','waist','thigh','calf','bf'];

const PLAN_ROWS = [
  ['Push A','Wyciskanie sztangi leżąc','4','5-6','3:00'],
  ['Push A','Wyciskanie sztangi nad głową (OHP)','3','6-8','2:30'],
  ['Push A','Wyciskanie hantli na skosie dodatnim','3','8-10','2:00'],
  ['Push A','Unoszenie hantli bokiem','3','12-15','1:00'],
  ['Push A','Wyciskanie francuskie wąskim chwytem','4','8-10','1:30'],
  ['Push A','Prostowanie ramion nad głową','3','10-12','1:15'],
  ['Pull A','Martwy ciąg','3','4-5','3:30'],
  ['Pull A','Podciąganie z obciążeniem','4','6-8','2:30'],
  ['Pull A','Wiosłowanie sztangą','3','8-10','2:00'],
  ['Pull A','Uginanie ramion ze sztangą','4','8-10','1:30'],
  ['Pull A','Uginanie młotkowe','3','10-12','1:15'],
  ['Push B','Wyciskanie hantli na skosie dodatnim','4','8-10','2:00'],
  ['Push B','Wyciskanie hantli płasko','3','10-12','2:00'],
  ['Push B','Rozpiętki na wyciągu','3','12-15','1:15'],
  ['Push B','Unoszenie hantli bokiem','4','12-15','1:00'],
  ['Push B','Prostowanie ramion na wyciągu','4','12-15','1:00'],
  ['Push B','Dipy na poręczach','3','10-12','1:30'],
  ['Pull B','Ściąganie drążka wyciągu','4','10-12','1:30'],
  ['Pull B','Wiosłowanie na maszynie z podparciem','3','10-12','1:30'],
  ['Pull B','Face pull','3','15','1:00'],
  ['Pull B','Uginanie hantlami na skosie','3','10-12','1:15'],
  ['Pull B','Uginanie na wyciągu','4','12-15','1:00'],
  ['Nogi','Przysiad ze sztangą','4','5-6','3:00'],
  ['Nogi','Wyciskanie nóg na suwnicy','3','10-12','2:00'],
  ['Nogi','Uginanie nóg leżąc','2','10-12','1:15'],
  ['Nogi','Wspięcia na palce stojąc','3','12-15','1:00']
];


/* Formuły piszemy po angielsku (przecinki); przy polskich ustawieniach arkusza
   zamieniamy separatory: argumenty ";" , kolumny w {} "\\" , ułamki ",". */
let FX_COMMA_ = null;
function fx_(f) {
  if (FX_COMMA_ === null) {
    const loc = SpreadsheetApp.getActiveSpreadsheet().getSpreadsheetLocale() || 'en_US';
    FX_COMMA_ = !/^(en|ja|zh|ko|he|th)/.test(loc);
  }
  if (!FX_COMMA_) return f;
  let out = '', q = false; const st = [];
  for (let i = 0; i < f.length; i++) {
    const ch = f[i];
    if (ch === '"') { q = !q; out += ch; continue; }
    if (q) { out += ch; continue; }
    if (ch === '{' || ch === '(') st.push(ch);
    if (ch === '}' || ch === ')') st.pop();
    if (ch === ',') { out += st[st.length - 1] === '{' ? '\\' : ';'; continue; }
    if (ch === '.' && /\d/.test(f[i - 1] || '') && /\d/.test(f[i + 1] || '')) { out += ','; continue; }
    out += ch;
  }
  return out;
}

/* ================= MENU ================= */
function onOpen() {
  SpreadsheetApp.getUi().createMenu('Fitness')
    .addItem('Zbuduj / odśwież arkusz', 'setup')
    .addItem('Pokaż token', 'showToken')
    .addItem('Ustaw klucz API Claude (AI w diecie)', 'setClaudeKey')
    .addItem('Włącz niedzielny raport mailem', 'installReportTrigger')
    .addItem('Wyślij raport teraz (test)', 'sendWeeklyReport')
    .addToUi();
}

function getToken_() {
  const p = PropertiesService.getScriptProperties();
  let t = p.getProperty('TOKEN');
  if (!t) { t = Utilities.getUuid().replace(/-/g, '').slice(0, 20); p.setProperty('TOKEN', t); }
  return t;
}

function showToken() {
  const ui = SpreadsheetApp.getUi();
  ui.alert('Token do apki', 'Token: ' + getToken_() +
    '\n\nAdres URL weź z: Wdróż > Zarządzaj wdrożeniami (adres kończy się na /exec).', ui.ButtonSet.OK);
}

/* ================= SETUP ================= */
function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.setSpreadsheetTimeZone(TZ);
  if (/bez tytułu|Untitled/i.test(ss.getName())) ss.rename('Żelazny Dziennik');
  getToken_();

  const dash = sheet_(ss, SH.DASH);
  dataSheet_(ss, SH.TRAIN, ['ID','Data','Dzień','Start','Koniec','Czas (min)','Serie','Objętość (kg)'],
    [120,100,90,70,70,90,70,110], {B:'d mmm yyyy', D:'HH:mm', E:'HH:mm', H:'#,##0'});
  dataSheet_(ss, SH.SETS, ['ID treningu','Data','Dzień','Ćwiczenie','Seria','Kg','Powt.','e1RM','Objętość','ID ćwiczenia'],
    [120,100,80,280,60,70,60,80,90,100], {B:'d mmm yyyy', F:'0.0#', H:'0.0', I:'#,##0'});
  dataSheet_(ss, SH.WEIGHT, ['Data','Waga (kg)','Średnia 7 dni','Zmiana tydz. (kg)'],
    [110,100,120,140], {A:'d mmm yyyy', B:'0.0', C:'0.00', D:'+0.00;-0.00;0.00'});
  dataSheet_(ss, SH.MEAS, ['Data','Ramię','Przedramię','Klatka','Talia','Udo','Łydka','Tłuszcz %'],
    [110,80,95,80,80,80,80,90], {A:'d mmm yyyy', B:'0.0', C:'0.0', D:'0.0', E:'0.0', F:'0.0', G:'0.0', H:'0.0'});
  dataSheet_(ss, SH.CAT, ['Data','Posiłek','Nazwa','kcal','Białko','Węgle','Tłuszcz','Zjedzone','Dieta'],
    [100,110,380,70,70,70,70,85,170], {A:'d mmm yyyy', D:'0', E:'0.0', F:'0.0', G:'0.0'});
  ss.getSheetByName(SH.CAT).getRange('H2:H').setDataValidation(SpreadsheetApp.newDataValidation().requireCheckbox().build());
  dataSheet_(ss, SH.FOOD, ['ID','Data','Godzina','Źródło','Nazwa','Ilość','kcal','Białko','Węgle','Tłuszcz','Kod EAN'],
    [110,100,70,90,280,70,70,70,70,70,120], {B:'d mmm yyyy', C:'HH:mm', G:'0', H:'0.0', I:'0.0', J:'0.0', K:'@'});
  buildDiet_(ss);
  dataSheet_(ss, SH.DAILY, ['Data','Kroki','Sen (h)'], [110,90,90], {A:'d mmm yyyy', B:'#,##0', C:'0.0'});
  dataSheet_(ss, SH.REP, ['Tydzień od','Data wpisu','Komentarz trenera','Zalecenia','Wysłano'], [100,130,520,420,130], {A:'d mmm yyyy', B:'d mmm yyyy HH:mm', E:'d mmm yyyy HH:mm'});
  ss.getSheetByName(SH.REP).getRange('C2:D').setWrap(true).setVerticalAlignment('top');
  buildPlan_(ss);
  buildWeeks_(ss);
  buildRecords_(ss);
  rewriteWeightFormulas_(ss.getSheetByName(SH.WEIGHT));
  buildDashboard_(ss, dash);

  // kolejność i sprzątanie
  [SH.DASH, SH.DIET, SH.TRAIN, SH.SETS, SH.WEIGHT, SH.MEAS, SH.DAILY, SH.CAT, SH.FOOD, SH.REP, SH.REC, SH.WEEK, SH.PLAN].forEach((n, i) => {
    ss.setActiveSheet(ss.getSheetByName(n)); ss.moveActiveSheet(i + 1);
  });
  ['Arkusz1','Sheet1'].forEach(n => { const s = ss.getSheetByName(n); if (s && s.getLastRow() === 0) ss.deleteSheet(s); });
  ss.getSheetByName(SH.WEEK).setTabColor(C.grey);
  ss.setActiveSheet(dash);
  try { showToken(); } catch (e) {}
}

function sheet_(ss, name) { return ss.getSheetByName(name) || ss.insertSheet(name); }

function dataSheet_(ss, name, headers, widths, formats) {
  const sh = sheet_(ss, name);
  sh.getRange(1, 1, 1, headers.length).setValues([headers])
    .setBackground(C.head).setFontColor(C.headTxt).setFontWeight('bold').setFontFamily('Roboto Condensed')
    .setFontSize(10).setVerticalAlignment('middle');
  sh.setRowHeight(1, 32);
  sh.setFrozenRows(1);
  widths.forEach((w, i) => sh.setColumnWidth(i + 1, w));
  const maxR = sh.getMaxRows();
  sh.getRange(2, 1, maxR - 1, headers.length).setFontFamily('Roboto').setFontSize(10).setFontColor(C.ink);
  Object.keys(formats).forEach(col => sh.getRange(col + '2:' + col).setNumberFormat(formats[col]));
  // pasy co drugi wiersz
  sh.getBandings().forEach(b => b.remove());
  sh.getRange(1, 1, maxR, headers.length).applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false)
    .setHeaderRowColor(C.head).setFirstRowColor('#FFFFFF').setSecondRowColor(C.band);
  // usuń zbędne kolumny
  const extra = sh.getMaxColumns() - headers.length;
  if (extra > 0) sh.deleteColumns(headers.length + 1, extra);
  sh.setTabColor(C.accent);
  return sh;
}

function buildPlan_(ss) {
  const sh = sheet_(ss, SH.PLAN);
  sh.clear(); sh.getBandings().forEach(b => b.remove());
  sh.getRange(1, 1, 1, 5).setValues([['Dzień','Ćwiczenie','Serie','Powtórzenia','Przerwa']])
    .setBackground(C.head).setFontColor(C.headTxt).setFontWeight('bold');
  sh.getRange(2, 1, PLAN_ROWS.length, 5).setValues(PLAN_ROWS).setFontFamily('Roboto');
  sh.getRange(2, 3, PLAN_ROWS.length, 3).setNumberFormat('@').setHorizontalAlignment('center');
  PLAN_ROWS.forEach((r, i) => sh.getRange(i + 2, 1).setBackground(DAYCOLOR[r[0]]).setFontColor('#FFFFFF').setFontWeight('bold'));
  [90, 300, 70, 110, 80].forEach((w, i) => sh.setColumnWidth(i + 1, w));
  sh.setFrozenRows(1);
  sh.getRange(PLAN_ROWS.length + 3, 1).setValue('Plan edytujemy w apce (z Claude). Ta zakładka to podgląd.').setFontColor(C.muted).setFontStyle('italic');
  sh.setTabColor(C.grey);
}

function buildWeeks_(ss) {
  const sh = sheet_(ss, SH.WEEK);
  sh.clear();
  sh.getRange('A1').setFormula(fx_(
    '=IFERROR(QUERY({ARRAYFORMULA(IF(Treningi!B2:B="",,INT(Treningi!B2:B)-WEEKDAY(Treningi!B2:B,2)+1)),Treningi!G2:G,Treningi!H2:H},' +
    '"select Col1, count(Col1), sum(Col2), sum(Col3) where Col1 is not null group by Col1 order by Col1 ' +
    'label Col1 \'Tydzień od\', count(Col1) \'Treningi\', sum(Col2) \'Serie\', sum(Col3) \'Objętość (kg)\'",0),' +
    '{"Tydzień od","Treningi","Serie","Objętość (kg)"})'));
  sh.getRange('A2:A').setNumberFormat('d mmm');
  sh.getRange('D2:D').setNumberFormat('#,##0');
  sh.getRange('A1:D1').setBackground(C.head).setFontColor(C.headTxt).setFontWeight('bold');
  sh.setColumnWidths(1, 4, 110);
}

function buildDiet_(ss) {
  const sh = sheet_(ss, SH.DIET);
  sh.clear(); sh.getBandings().forEach(b => b.remove());
  sh.getRange(1, 1, 1, 6).setValues([['Data','Zjedzone kcal','Białko (g)','Catering (plan kcal)','Dodatkowe kcal','Cel kcal']])
    .setBackground(C.head).setFontColor(C.headTxt).setFontWeight('bold');
  sh.getRange('A2').setFormula(fx_('=IFERROR(SORT(UNIQUE(FILTER({Catering!A2:A;Jedzenie!B2:B},{Catering!A2:A;Jedzenie!B2:B}<>""))),)'));
  sh.getRange('B2').setFormula(fx_('=MAP(A2:A,LAMBDA(d,IF(d="",,SUMIFS(Catering!D2:D,Catering!A2:A,d,Catering!H2:H,TRUE)+SUMIFS(Jedzenie!G2:G,Jedzenie!B2:B,d))))'));
  sh.getRange('C2').setFormula(fx_('=MAP(A2:A,LAMBDA(d,IF(d="",,SUMIFS(Catering!E2:E,Catering!A2:A,d,Catering!H2:H,TRUE)+SUMIFS(Jedzenie!H2:H,Jedzenie!B2:B,d))))'));
  sh.getRange('D2').setFormula(fx_('=MAP(A2:A,LAMBDA(d,IF(d="",,SUMIFS(Catering!D2:D,Catering!A2:A,d))))'));
  sh.getRange('E2').setFormula(fx_('=MAP(A2:A,LAMBDA(d,IF(d="",,SUMIFS(Jedzenie!G2:G,Jedzenie!B2:B,d))))'));
  sh.getRange('F2').setFormula(fx_('=MAP(A2:A,LAMBDA(d,IF(d="",,3300)))'));
  sh.getRange('A2:A').setNumberFormat('ddd d mmm');
  sh.getRange('B2:F').setNumberFormat('0');
  sh.setColumnWidths(1, 6, 140);
  sh.setFrozenRows(1);
  sh.setTabColor(C.pink);
}

function buildRecords_(ss) {
  const sh = sheet_(ss, SH.REC);
  sh.clear();
  sh.getRange('A1').setFormula(fx_(
    '=IFERROR(QUERY(Serie!A2:J,"select D, max(H), max(F), count(D), max(B) where D is not null group by D order by max(H) desc ' +
    'label D \'Ćwiczenie\', max(H) \'Najlepszy e1RM\', max(F) \'Max ciężar\', count(D) \'Serie łącznie\', max(B) \'Ostatnio\'",0),' +
    '{"Ćwiczenie","Najlepszy e1RM","Max ciężar","Serie łącznie","Ostatnio"})'));
  sh.getRange('A1:E1').setBackground(C.head).setFontColor(C.headTxt).setFontWeight('bold');
  sh.getRange('B2:C').setNumberFormat('0.0" kg"');
  sh.getRange('E2:E').setNumberFormat('d mmm yyyy');
  sh.setColumnWidth(1, 290); sh.setColumnWidths(2, 4, 120);
  sh.setFrozenRows(1);
  sh.setTabColor(C.good);
}

/* ================= DASHBOARD ================= */
function buildDashboard_(ss, sh) {
  sh.getCharts().forEach(c => sh.removeChart(c));
  sh.getRange(1, 1, sh.getMaxRows(), sh.getMaxColumns()).breakApart();
  sh.clear(); sh.getBandings().forEach(b => b.remove());
  sh.setHiddenGridlines(true);
  if (sh.getMaxColumns() < 12) sh.insertColumnsAfter(sh.getMaxColumns(), 12 - sh.getMaxColumns());
  sh.setColumnWidth(1, 24);
  sh.setColumnWidths(2, 10, 92);
  sh.getRange('A1:L80').setFontFamily('Roboto').setFontColor(C.ink).setBackground('#FFFFFF');

  // nagłówek
  sh.getRange('B2:K2').merge().setValue('ŻELAZNY DZIENNIK').setFontFamily('Roboto Condensed').setFontSize(26).setFontWeight('bold').setFontColor(C.head);
  sh.getRange('B3:K3').merge().setFormula(fx_('="Masa: "&IFERROR(TEXT(B6,"0.0"),"–")&" → cel "&TEXT(K5,"0.0")&" kg  ·  aktualizacja "&TEXT(NOW(),"d mmm yyyy, HH:mm")'))
    .setFontColor(C.muted).setFontSize(10);
  sh.setRowHeight(2, 42);

  // parametry (edytowalne)
  sh.getRange('J5').setValue('Cel wagi').setFontColor(C.muted).setFontSize(9).setHorizontalAlignment('right');
  sh.getRange('K5').setValue(90.5).setNumberFormat('0.0" kg"').setBackground(C.accentSoft).setFontWeight('bold');
  sh.getRange('J6').setValue('Waga start').setFontColor(C.muted).setFontSize(9).setHorizontalAlignment('right');
  sh.getRange('K6').setValue(85).setNumberFormat('0.0" kg"').setBackground(C.accentSoft).setFontWeight('bold');

  const WEEK0 = 'TODAY()-WEEKDAY(TODAY(),2)+1';
  const tiles = [
    // [kolumna start, wiersz, etykieta, formuła, format, podpis]
    ['B', 5, 'ŚREDNIA 7 DNI', '=IF(COUNTA(Waga!A2:A)=0,"–",INDEX(Waga!C2:C,COUNTA(Waga!A2:A)))', '0.0" kg"',
      '=IF(COUNTA(Waga!A2:A)=0,"brak wpisów","ostatni wpis: "&TEXT(INDEX(Waga!B2:B,COUNTA(Waga!A2:A)),"0.0")&" kg")'],
    ['D', 5, 'TEMPO / TYDZIEŃ', '=IF(COUNTA(Waga!A2:A)<2,"–",INDEX(Waga!D2:D,COUNTA(Waga!A2:A)))', '+0.00" kg";-0.00" kg"',
      '=IF(NOT(ISNUMBER(D6)),"cel 0,2-0,35 kg",IF(D6<0.2,"za wolno: dodaj 100-150 kcal",IF(D6<=0.35,"w celu 0,2-0,35 kg",IF(D6<=0.5,"szybko, obserwuj","za szybko: odejmij 100-150 kcal"))))'],
    ['F', 5, 'DO CELU', '=IF(ISNUMBER(B6),K5-B6,"–")', '0.0" kg"',
      '=IF(ISNUMBER(B6),"zrobione "&TEXT((B6-K6)/(K5-K6),"0%")&" masy","")'],
    ['B', 9, 'TRENINGI W TYM TYG.', '=COUNTIFS(Treningi!B2:B,">="&' + WEEK0 + ')', '0" / 5"',
      '="serie: "&SUMIFS(Treningi!G2:G,Treningi!B2:B,">="&' + WEEK0 + ')'],
    ['D', 9, 'OSTATNI TRENING', '=IFERROR(INDEX(SORT(Treningi!B2:C,1,FALSE),1,2),"–")', '@',
      '=IF(COUNT(Treningi!B2:B)=0,"brak treningów",TEXT(MAX(Treningi!B2:B),"dddd, d mmm"))'],
    ['F', 9, 'OBJĘTOŚĆ TYG.', '=SUMIFS(Treningi!H2:H,Treningi!B2:B,">="&' + WEEK0 + ')/1000', '0.0" t"',
      '=IFERROR("poprz. tydz.: "&TEXT(SUMIFS(Treningi!H2:H,Treningi!B2:B,">="&(' + WEEK0 + '-7),Treningi!B2:B,"<"&' + WEEK0 + ')/1000,"0.0")&" t","")']
  ];
  tiles.forEach(t => tile_(sh, t[0], t[1], t[2], t[3], t[4], t[5]));

  // pomiary
  sh.getRange('H8:K8').merge().setValue('OSTATNIE POMIARY (cm)').setFontSize(9).setFontColor(C.muted).setFontWeight('bold');
  const ml = [['Ramię','B'],['Klatka','D'],['Talia','E'],['Udo','F']];
  ml.forEach((m, i) => {
    sh.getRange(9 + i, 8, 1, 2).merge().setValue(m[0]).setFontColor(C.muted);
    sh.getRange(9 + i, 10).setFormula(fx_('=IF(COUNTA(Pomiary!A2:A)=0,"–",INDEX(Pomiary!' + m[1] + '2:' + m[1] + ',COUNTA(Pomiary!A2:A)))')).setNumberFormat('0.0').setFontWeight('bold').setFontSize(12);
    sh.getRange(9 + i, 11).setFormula(fx_('=IF(COUNTA(Pomiary!A2:A)<2,"",INDEX(Pomiary!' + m[1] + '2:' + m[1] + ',COUNTA(Pomiary!A2:A))-INDEX(Pomiary!' + m[1] + '2:' + m[1] + ',1))'))
      .setNumberFormat('+0.0;-0.0;0.0').setFontColor(C.good);
  });
  sh.getRange('H13:K13').merge().setFormula(fx_('=IF(COUNTA(Pomiary!A2:A)=0,"brak pomiarów","od "&TEXT(INDEX(Pomiary!A2:A,1),"d mmm")&" do "&TEXT(INDEX(Pomiary!A2:A,COUNTA(Pomiary!A2:A)),"d mmm"))')).setFontSize(9).setFontColor(C.muted);

  // wykresy
  const w = ss.getSheetByName(SH.WEIGHT), wk = ss.getSheetByName(SH.WEEK);
  sh.getRange('B15:K15').merge().setValue('WAGA I ŚREDNIA 7 DNI').setFontSize(9).setFontColor(C.muted).setFontWeight('bold');
  sh.insertChart(sh.newChart().setChartType(Charts.ChartType.LINE)
    .addRange(w.getRange('A1:C400')).setPosition(16, 2, 0, 0)
    .setOption('width', 860).setOption('height', 300).setOption('legend', { position: 'bottom' })
    .setOption('colors', ['#B7C2CA', C.accent]).setOption('lineWidth', 2)
    .setOption('series', { 0: { lineWidth: 0, pointSize: 5 }, 1: { lineWidth: 3, pointSize: 0 } })
    .setOption('vAxis', { format: '0.0', gridlines: { color: '#E6EAEF' } })
    .setOption('hAxis', { format: 'd MMM', gridlines: { color: 'transparent' } })
    .setOption('chartArea', { left: 50, top: 14, width: '88%', height: '72%' })
    .setOption('useFirstColumnAsDomain', true).build());

  sh.getRange('B32:K32').merge().setValue('OBJĘTOŚĆ TYGODNIOWA (kg)').setFontSize(9).setFontColor(C.muted).setFontWeight('bold');
  sh.insertChart(sh.newChart().setChartType(Charts.ChartType.COLUMN)
    .addRange(wk.getRange('A1:A60')).addRange(wk.getRange('D1:D60')).setPosition(33, 2, 0, 0)
    .setOption('width', 860).setOption('height', 260).setOption('legend', { position: 'none' })
    .setOption('colors', [C.accent]).setOption('vAxis', { format: '#,##0', gridlines: { color: '#E6EAEF' } })
    .setOption('hAxis', { format: 'd MMM' })
    .setOption('chartArea', { left: 60, top: 14, width: '86%', height: '74%' }).build());

  // top rekordy
  sh.getRange('B47:K47').merge().setValue('NAJLEPSZE WYNIKI').setFontSize(9).setFontColor(C.muted).setFontWeight('bold');
  sh.getRange('B48:F48').merge().setValue('Ćwiczenie');
  sh.getRange('G48').setValue('e1RM');
  sh.getRange('H48').setValue('Max kg');
  sh.getRange('I48:J48').merge().setValue('Ostatnio');
  sh.getRange('B48:J48').setFontSize(9).setFontColor(C.muted).setFontWeight('bold')
    .setBorder(null, null, true, null, null, null, C.line, SpreadsheetApp.BorderStyle.SOLID);
  for (let i = 0; i < 10; i++) {
    const r = 49 + i, src = i + 2;
    sh.getRange(r, 2, 1, 5).merge().setFormula(fx_('=IFERROR(INDEX(Rekordy!A:A,' + src + ')&"","")'));
    sh.getRange(r, 7).setFormula(fx_('=IFERROR(INDEX(Rekordy!B:B,' + src + ')/1,"")')).setNumberFormat('0.0').setFontWeight('bold');
    sh.getRange(r, 8).setFormula(fx_('=IFERROR(INDEX(Rekordy!C:C,' + src + ')/1,"")')).setNumberFormat('0.0');
    sh.getRange(r, 9, 1, 2).merge().setFormula(fx_('=IFERROR(INDEX(Rekordy!E:E,' + src + ')/1,"")')).setNumberFormat('d mmm').setFontColor(C.muted);
  }

  sh.setFrozenRows(3);
  sh.setTabColor(C.ink);
}

function tile_(sh, col, row, label, formula, fmt, sub) {
  const c = sh.getRange(col + row).getColumn();
  const box = sh.getRange(row, c, 3, 2);
  box.setBackground(C.band).setBorder(true, true, true, true, false, false, C.line, SpreadsheetApp.BorderStyle.SOLID);
  sh.getRange(row, c, 1, 2).merge().setValue(label).setFontSize(8).setFontColor(C.muted).setFontWeight('bold');
  sh.getRange(row + 1, c, 1, 2).merge().setFormula(fx_(formula)).setNumberFormat(fmt)
    .setFontFamily('Roboto Condensed').setFontSize(22).setFontWeight('bold').setHorizontalAlignment('left');
  sh.getRange(row + 2, c, 1, 2).merge().setFormula(fx_(sub)).setFontSize(9).setFontColor(C.muted);
  sh.setRowHeight(row + 1, 38);
}

/* ================= API (apka → arkusz) ================= */
function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.token !== getToken_()) return json_({ ok: false, error: 'Zły token' });
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (p.action === 'pull') return json_(Object.assign({ ok: true }, pullAll_(ss), dietRange_(ss, '', '')));
  if (p.action === 'daily') return json_(dailyFromShortcut_(ss, p));
  if (p.action === 'diet') return json_(Object.assign({ ok: true }, dietRange_(ss, p.from || '', p.to || '')));
  return json_({ ok: true, name: ss.getName() });
}

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return json_({ ok: false, error: 'Złe dane' }); }
  if (body.token !== getToken_()) return json_({ ok: false, error: 'Zły token' });
  if (body.action === 'estimate') {
    try { return json_(estimate_(body.text)); } catch (err) { return json_({ ok: false, error: err.message }); }
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const done = [], errors = [];
    (body.items || []).forEach(it => {
      try { handle_(ss, it); done.push(it.qid); }
      catch (err) { errors.push(it.qid + ': ' + err.message); }
    });
    SpreadsheetApp.flush();
    return json_({ ok: true, done: done, errors: errors });
  } catch (err) {
    return json_({ ok: false, error: err.message });
  } finally {
    lock.releaseLock();
  }
}

/* ================= AI: posiłek opisany słownie ================= */
// Klucz API trzymany we właściwościach skryptu (ANTHROPIC_API_KEY), nigdy w apce.
// Model można zmienić właściwością CLAUDE_MODEL.
function setClaudeKey() {
  const ui = SpreadsheetApp.getUi();
  const r = ui.prompt('Klucz API Claude', 'Wklej klucz z console.anthropic.com (zaczyna się od sk-ant-):', ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  const k = r.getResponseText().trim();
  if (!/^sk-ant-/.test(k)) { ui.alert('To nie wygląda na klucz API Claude (powinien zaczynać się od sk-ant-).'); return; }
  PropertiesService.getScriptProperties().setProperty('ANTHROPIC_API_KEY', k);
  const t = estimate_('banan 120 g');
  ui.alert(t.ok ? 'Zapisano klucz. Test działa: banan 120 g ≈ ' + t.items[0].kcal + ' kcal.\n\nTeraz: Wdróż > Zarządzaj wdrożeniami > ołówek > Wersja: Nowa wersja > Wdróż.'
    : 'Zapisano klucz, ale test nie przeszedł: ' + t.error);
}

// Test z edytora: wybierz testClaude i kliknij Uruchom, wynik w Dzienniku wykonania.
function testClaude() {
  const t = estimate_('burger wołowy 400 g plus mała porcja frytek');
  Logger.log(JSON.stringify(t));
  return t;
}

function estimate_(text) {
  text = String(text || '').trim().slice(0, 600);
  if (!text) return { ok: false, error: 'Pusty opis posiłku' };
  const props = PropertiesService.getScriptProperties();
  const key = props.getProperty('ANTHROPIC_API_KEY');
  if (!key) return { ok: false, error: 'Brak klucza API Claude. W arkuszu: menu Fitness > Ustaw klucz API Claude.' };
  const model = props.getProperty('CLAUDE_MODEL') || 'claude-sonnet-5-5';
  const tool = {
    name: 'zapisz_posilek',
    description: 'Zapisuje oszacowane wartości odżywcze posiłku, osobno dla każdego składnika.',
    input_schema: {
      type: 'object',
      properties: {
        items: { type: 'array', items: { type: 'object', properties: {
          name: { type: 'string', description: 'Krótka polska nazwa pozycji, np. "Burger wołowy"' },
          grams: { type: 'number', description: 'Gramatura całej porcji w gramach' },
          kcal: { type: 'number', description: 'Kalorie całej porcji' },
          protein: { type: 'number', description: 'Białko w gramach dla całej porcji' },
          carbs: { type: 'number', description: 'Węglowodany w gramach dla całej porcji' },
          fat: { type: 'number', description: 'Tłuszcz w gramach dla całej porcji' }
        }, required: ['name', 'grams', 'kcal', 'protein', 'carbs', 'fat'] } },
        note: { type: 'string', description: 'Jedno krótkie zdanie po polsku o przyjętych założeniach' }
      },
      required: ['items']
    }
  };
  const system = 'Jesteś dietetykiem. Szacujesz kalorie i makroskładniki posiłków opisanych słownie po polsku. ' +
    'Rozbij posiłek na sensowne pozycje (np. burger i frytki osobno; napój osobno). ' +
    'Gdy podano gramaturę, użyj jej dokładnie dla tej pozycji. Gdy jej brak, przyjmij typową polską porcję ' +
    '(np. frytki z fast foodu: mała ok. 80 g, średnia ok. 115 g, duża ok. 150 g). ' +
    'Dania z restauracji i fast foodu szacuj realistycznie, z tłuszczem ze smażenia i sosami. ' +
    'Wartości podawaj dla całej porcji, nie na 100 g. Zawsze odpowiadaj wyłącznie wywołaniem narzędzia zapisz_posilek.';
  const res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01' },
    payload: JSON.stringify({ model: model, max_tokens: 1024, system: system, tools: [tool],
      tool_choice: { type: 'auto' }, messages: [{ role: 'user', content: text }] })
  });
  const code = res.getResponseCode();
  let j = {}; try { j = JSON.parse(res.getContentText()); } catch (err) {}
  if (code !== 200) return { ok: false, error: 'Claude API: ' + ((j.error && j.error.message) || ('błąd ' + code)) };
  let tu = (j.content || []).filter(c => c.type === 'tool_use')[0];
  if (!tu) { // zapas: model odpisał tekstem z JSON-em
    const txt = (j.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
    const m = txt.match(/\{[\s\S]*\}/);
    try { if (m) tu = { input: JSON.parse(m[0]) }; } catch (err) {}
  }
  if (!tu || !tu.input || !tu.input.items || !tu.input.items.length) return { ok: false, error: 'Claude nie zwrócił wyniku. Opisz posiłek dokładniej.' };
  const r1 = v => Math.round((Number(v) || 0) * 10) / 10;
  const items = tu.input.items.map(x => ({ name: String(x.name || '').slice(0, 80), g: Math.round(Number(x.grams) || 0),
    kcal: Math.round(Number(x.kcal) || 0), p: r1(x.protein), c: r1(x.carbs), f: r1(x.fat) })).filter(x => x.name);
  return { ok: true, items: items, note: String(tu.input.note || '').slice(0, 200) };
}

function handle_(ss, it) {
  const d = it.data || {};
  switch (it.type) {
    case 'workout':    saveWorkout_(ss, d); break;
    case 'delWorkout': deleteWhere_(ss.getSheetByName(SH.TRAIN), 1, d.id); deleteWhere_(ss.getSheetByName(SH.SETS), 1, d.id); break;
    case 'weight':     upsertByDate_(ss.getSheetByName(SH.WEIGHT), d.date, [d.kg]); rewriteWeightFormulas_(ss.getSheetByName(SH.WEIGHT)); break;
    case 'delWeight':  deleteDate_(ss.getSheetByName(SH.WEIGHT), d.date); rewriteWeightFormulas_(ss.getSheetByName(SH.WEIGHT)); break;
    case 'measure':    upsertByDate_(ss.getSheetByName(SH.MEAS), d.date, MEAS_COLS.map(k => d[k] == null ? '' : d[k])); break;
    case 'delMeasure': deleteDate_(ss.getSheetByName(SH.MEAS), d.date); break;
    case 'catering':   saveCatering_(ss, d); break;
    case 'eat':        setEaten_(ss, d); break;
    case 'food':       saveFood_(ss, d); break;
    case 'daily':      upsertDaily_(ss, d.date, d); break;
    case 'delFood':    deleteWhere_(ss.getSheetByName(SH.FOOD), 1, d.id); break;
    default: throw new Error('Nieznany typ ' + it.type);
  }
}

function saveWorkout_(ss, w) {
  const tr = ss.getSheetByName(SH.TRAIN), st = ss.getSheetByName(SH.SETS);
  deleteWhere_(tr, 1, w.id); deleteWhere_(st, 1, w.id);
  const date = toDate_(w.date);
  const vol = w.sets.reduce((n, s) => n + s.kg * s.reps, 0);
  tr.appendRow([w.id, date, w.day, new Date(w.start), new Date(w.end), Math.round((w.end - w.start) / 60000), w.sets.length, vol]);
  const rows = w.sets.map(s => [w.id, date, w.day, s.ex, s.set, s.kg, s.reps, e1rm_(s.kg, s.reps), s.kg * s.reps, s.exId]);
  if (rows.length) st.getRange(st.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
  if (tr.getLastRow() > 2) tr.getRange(2, 1, tr.getLastRow() - 1, tr.getLastColumn()).sort([{ column: 2, ascending: true }, { column: 4, ascending: true }]);
  colorDays_(tr);
}

function saveCatering_(ss, d) {
  const sh = ss.getSheetByName(SH.CAT);
  // zachowaj odhaczenia "nie zjedzone" dla tego dnia
  const keep = {};
  if (sh.getLastRow() > 1) sh.getRange(2, 1, sh.getLastRow() - 1, 8).getValues().forEach(r => {
    if (key_(r[0]) === d.date && r[7] === false) keep[r[1]] = false;
  });
  deleteDate_(sh, d.date);
  const rows = (d.meals || []).map(m => [toDate_(d.date), m.meal, m.name, m.kcal, m.p, m.c, m.f, keep[m.meal] === false ? false : true, d.diet || '']);
  if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
  if (sh.getLastRow() > 2) sh.getRange(2, 1, sh.getLastRow() - 1, sh.getLastColumn()).sort({ column: 1, ascending: true });
}

function setEaten_(ss, d) {
  const sh = ss.getSheetByName(SH.CAT); const n = sh.getLastRow() - 1; if (n < 1) return;
  const vals = sh.getRange(2, 1, n, 2).getValues();
  vals.forEach((r, i) => { if (key_(r[0]) === d.date && r[1] === d.meal) sh.getRange(i + 2, 8).setValue(!!d.eaten); });
}

function saveFood_(ss, f) {
  const sh = ss.getSheetByName(SH.FOOD);
  deleteWhere_(sh, 1, f.id);
  sh.appendRow([f.id, toDate_(f.date), f.time ? new Date(f.time) : '', f.source || 'Ręcznie', f.name, f.amount || '', f.kcal || 0, f.p || 0, f.c || 0, f.f || 0, f.ean ? String(f.ean) : '']);
  if (sh.getLastRow() > 2) sh.getRange(2, 1, sh.getLastRow() - 1, sh.getLastColumn()).sort([{ column: 2, ascending: true }, { column: 3, ascending: true }]);
}

function dietRange_(ss, from, to) {
  const cat = ss.getSheetByName(SH.CAT), fd = ss.getSheetByName(SH.FOOD);
  const inR = k => (!from || k >= from) && (!to || k <= to);
  const catering = cat && cat.getLastRow() > 1 ? cat.getRange(2, 1, cat.getLastRow() - 1, 9).getValues().filter(r => r[0] && inR(key_(r[0])))
    .map(r => ({ date: key_(r[0]), meal: r[1], name: r[2], kcal: Number(r[3]) || 0, p: Number(r[4]) || 0, c: Number(r[5]) || 0, f: Number(r[6]) || 0, eaten: r[7] !== false, diet: r[8] })) : [];
  const foods = fd && fd.getLastRow() > 1 ? fd.getRange(2, 1, fd.getLastRow() - 1, 11).getValues().filter(r => r[0] && inR(key_(r[1])))
    .map(r => ({ id: String(r[0]), date: key_(r[1]), time: r[2] instanceof Date ? r[2].getTime() : null, source: r[3], name: r[4], amount: r[5], kcal: Number(r[6]) || 0, p: Number(r[7]) || 0, c: Number(r[8]) || 0, f: Number(r[9]) || 0, ean: String(r[10] || '') })) : [];
  const dl = ss.getSheetByName(SH.DAILY);
  const daily = dl && dl.getLastRow() > 1 ? dl.getRange(2, 1, dl.getLastRow() - 1, 3).getValues().filter(r => r[0] && inR(key_(r[0])))
    .map(r => ({ date: key_(r[0]), steps: r[1] === '' ? null : Number(r[1]), sleep: r[2] === '' ? null : Number(r[2]) })) : [];
  const wt = ss.getSheetByName(SH.WEIGHT);
  const weights = wt && wt.getLastRow() > 1 ? wt.getRange(2, 1, wt.getLastRow() - 1, 2).getValues().filter(r => r[0] && r[1] !== '' && inR(key_(r[0])))
    .map(r => ({ date: key_(r[0]), kg: Number(r[1]) })) : [];
  return { catering: catering, foods: foods, daily: daily, weights: weights };
}

function colorDays_(tr) {
  const n = tr.getLastRow() - 1; if (n < 1) return;
  const vals = tr.getRange(2, 3, n, 1).getValues();
  tr.getRange(2, 3, n, 1).setBackgrounds(vals.map(v => [DAYCOLOR[v[0]] || null]))
    .setFontColors(vals.map(v => [DAYCOLOR[v[0]] ? '#FFFFFF' : C.ink])).setFontWeight('bold');
}

function e1rm_(kg, r) { return (!kg || !r) ? 0 : (r === 1 ? kg : Math.round(kg * (1 + r / 30) * 10) / 10); }

function toDate_(s) { const p = String(s).split('-').map(Number); return new Date(p[0], p[1] - 1, p[2]); }
function key_(v) { return v instanceof Date ? Utilities.formatDate(v, TZ, 'yyyy-MM-dd') : String(v); }

function deleteWhere_(sh, col, val) {
  const last = sh.getLastRow(); if (last < 2) return;
  const vals = sh.getRange(2, col, last - 1, 1).getValues();
  for (let i = vals.length - 1; i >= 0; i--) if (String(vals[i][0]) === String(val)) sh.deleteRow(i + 2);
}
function deleteDate_(sh, date) {
  const last = sh.getLastRow(); if (last < 2) return;
  const vals = sh.getRange(2, 1, last - 1, 1).getValues();
  for (let i = vals.length - 1; i >= 0; i--) if (key_(vals[i][0]) === date) sh.deleteRow(i + 2);
}
function upsertByDate_(sh, date, values) {
  deleteDate_(sh, date);
  sh.appendRow([toDate_(date)].concat(values));
  if (sh.getLastRow() > 2) sh.getRange(2, 1, sh.getLastRow() - 1, sh.getLastColumn()).sort({ column: 1, ascending: true });
}
function rewriteWeightFormulas_(sh) {
  const n = sh.getLastRow() - 1; if (n < 1) return;
  const c = [], d = [];
  for (let i = 0; i < n; i++) {
    c.push([fx_('=IFERROR(AVERAGEIFS(C2,C1,">"&RC1-7,C1,"<="&RC1),"")')]);
    d.push([fx_('=IFERROR(RC[-1]-AVERAGEIFS(C2,C1,">"&RC1-14,C1,"<="&RC1-7),"")')]);
  }
  sh.getRange(2, 3, n, 1).setFormulasR1C1(c);
  sh.getRange(2, 4, n, 1).setFormulasR1C1(d);
}

function pullAll_(ss) {
  const tr = ss.getSheetByName(SH.TRAIN), st = ss.getSheetByName(SH.SETS);
  const byId = {};
  const dayIds = { 'Push A':'pushA', 'Pull A':'pullA', 'Push B':'pushB', 'Pull B':'pullB', 'Nogi':'legs' };
  if (tr.getLastRow() > 1) tr.getRange(2, 1, tr.getLastRow() - 1, 8).getValues().forEach(r => {
    const start = r[3] instanceof Date ? r[3].getTime() : toDate_(key_(r[1])).getTime();
    byId[r[0]] = { id: String(r[0]), dayId: dayIds[r[2]] || r[2], start: start, end: r[4] instanceof Date ? r[4].getTime() : start, ex: [] };
  });
  if (st.getLastRow() > 1) st.getRange(2, 1, st.getLastRow() - 1, 10).getValues().forEach(r => {
    const w = byId[r[0]]; if (!w) return;
    let e = w.ex.find(x => x.exId === r[9]); if (!e) { e = { exId: r[9], sets: [] }; w.ex.push(e); }
    e.sets.push({ kg: Number(r[5]) || 0, reps: Number(r[6]) || 0, done: true });
  });
  const ws = ss.getSheetByName(SH.WEIGHT), ms = ss.getSheetByName(SH.MEAS);
  const weights = ws.getLastRow() > 1 ? ws.getRange(2, 1, ws.getLastRow() - 1, 2).getValues().filter(r => r[0]).map(r => ({ date: key_(r[0]), kg: Number(r[1]) })) : [];
  const measures = ms.getLastRow() > 1 ? ms.getRange(2, 1, ms.getLastRow() - 1, 8).getValues().filter(r => r[0]).map(r => {
    const o = { date: key_(r[0]) }; MEAS_COLS.forEach((k, i) => { if (r[i + 1] !== '') o[k] = Number(r[i + 1]); }); return o;
  }) : [];
  return { workouts: Object.keys(byId).map(k => byId[k]), weights: weights, measures: measures };
}

function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }


/* ================= KROKI I SEN ================= */
// Skróty iOS: ?action=daily&token=…&steps=…&sleep=…&kg=…  (każdy parametr opcjonalny)
// sleep: godziny (7,5), „7 h 30 min”, albo sleep_min (minuty) / sleep_s (sekundy)
function dailyFromShortcut_(ss, p) {
  const date = /^\d{4}-\d{2}-\d{2}$/.test(p.date || '') ? p.date : Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd');
  const sleep = sleepHours_(p);
  upsertDaily_(ss, date, { steps: p.steps, sleep: sleep });
  const kg = numIn_(p.kg || p.weight);
  let wOk = false;
  if (kg !== null && kg >= 30 && kg <= 250) {
    const sh = ss.getSheetByName(SH.WEIGHT);
    upsertByDate_(sh, date, [Math.round(kg * 10) / 10]); rewriteWeightFormulas_(sh); wOk = true;
  }
  return { ok: true, date: date, steps: numIn_(p.steps), sleep: sleep, kg: wOk ? Math.round(kg * 10) / 10 : null };
}
function sleepHours_(p) {
  if (numIn_(p.sleep_s) !== null) return Math.round(numIn_(p.sleep_s) / 360) / 10;
  if (numIn_(p.sleep_min) !== null) return Math.round(numIn_(p.sleep_min) / 6) / 10;
  const v = String(p.sleep == null ? '' : p.sleep).toLowerCase();
  if (!v) return null;
  const h = v.match(/([\d.,]+)\s*(h|godz)/), m = v.match(/([\d.,]+)\s*(min|m\b)/);
  let out;
  if (h || m) out = (h ? numIn_(h[1]) : 0) + (m ? numIn_(m[1]) / 60 : 0);
  else { out = numIn_(v); if (out !== null && out > 1440) out = out / 3600; else if (out !== null && out > 24) out = out / 60; }
  return out === null || out <= 0 || out > 16 ? null : Math.round(out * 10) / 10; // 0 h = brak danych w Zdrowiu, nie nadpisuje ręcznego wpisu
}

function numIn_(v) { if (v === undefined || v === null || v === '') return null; const n = parseFloat(String(v).replace(/\s/g, '').replace(',', '.')); return isNaN(n) ? null : n; }
function upsertDaily_(ss, date, d) {
  const sh = ss.getSheetByName(SH.DAILY); if (!sh || !date) return;
  const steps = numIn_(d.steps), sleep = numIn_(d.sleep);
  const n = sh.getLastRow() - 1;
  if (n > 0) {
    const vals = sh.getRange(2, 1, n, 1).getValues();
    for (let i = 0; i < n; i++) if (key_(vals[i][0]) === date) {
      if (steps !== null) sh.getRange(i + 2, 2).setValue(Math.round(steps));
      if (sleep !== null) sh.getRange(i + 2, 3).setValue(sleep);
      return;
    }
  }
  sh.appendRow([toDate_(date), steps === null ? '' : Math.round(steps), sleep === null ? '' : sleep]);
  if (sh.getLastRow() > 2) sh.getRange(2, 1, sh.getLastRow() - 1, 3).sort({ column: 1, ascending: true });
}

/* ================= RAPORT TYGODNIOWY ================= */
function installReportTrigger() {
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'sendWeeklyReport').forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('sendWeeklyReport').timeBased().onWeekDay(ScriptApp.WeekDay.SUNDAY).atHour(21).nearMinute(0).inTimezone(TZ).create();
  try { SpreadsheetApp.getUi().alert('Raport włączony', 'Mail z podsumowaniem tygodnia pójdzie w każdą niedzielę ok. 21:00 na ' + REPORT_TO + '.', SpreadsheetApp.getUi().ButtonSet.OK); } catch (e) {}
}

function rows_(ss, name, cols) { const sh = ss.getSheetByName(name); return sh && sh.getLastRow() > 1 ? sh.getRange(2, 1, sh.getLastRow() - 1, cols).getValues() : []; }
function avg_(a) { const b = a.filter(x => typeof x === 'number' && !isNaN(x)); return b.length ? b.reduce((x, y) => x + y, 0) / b.length : null; }
function f1_(n, d) { if (n === null || n === undefined || isNaN(n)) return '–'; return Number(n).toFixed(d === undefined ? 1 : d).replace('.', ','); }

function weekStats_(ss) {
  const now = new Date();
  const todayK = Utilities.formatDate(now, TZ, 'yyyy-MM-dd');
  const t = toDate_(todayK); const dow = (t.getDay() + 6) % 7;
  const mon = new Date(t.getTime() - dow * 864e5), sun = new Date(mon.getTime() + 6 * 864e5);
  const K = d => Utilities.formatDate(d, TZ, 'yyyy-MM-dd');
  const from = K(mon), to = K(sun), pFrom = K(new Date(mon.getTime() - 7 * 864e5)), pTo = K(new Date(mon.getTime() - 864e5));
  const inW = k => k >= from && k <= to, inP = k => k >= pFrom && k <= pTo;
  // waga
  const W = rows_(ss, SH.WEIGHT, 2).filter(r => r[0]).map(r => ({ k: key_(r[0]), kg: Number(r[1]) }));
  const wNow = avg_(W.filter(x => inW(x.k)).map(x => x.kg)), wPrev = avg_(W.filter(x => inP(x.k)).map(x => x.kg));
  const wLast = W.length ? W[W.length - 1].kg : null;
  // treningi
  const TR = rows_(ss, SH.TRAIN, 8).filter(r => r[0] && inW(key_(r[1])));
  const SE = rows_(ss, SH.SETS, 10).filter(r => r[0]);
  const seW = SE.filter(r => inW(key_(r[1])));
  const muscles = {}; seW.forEach(r => { const m = MUSCLE[r[9]] || 'Inne'; muscles[m] = (muscles[m] || 0) + 1; });
  const best = {}, bestBefore = {};
  SE.forEach(r => { const k = key_(r[1]); const e = Number(r[7]) || 0; const ex = r[3];
    if (inW(k)) { if (!best[ex] || e > best[ex].e) best[ex] = { e: e, kg: r[5], reps: r[6] }; }
    else if (k < from) bestBefore[ex] = Math.max(bestBefore[ex] || 0, e); });
  const prs = Object.keys(best).filter(ex => bestBefore[ex] && best[ex].e > bestBefore[ex] + 0.01)
    .map(ex => ({ ex: ex, kg: best[ex].kg, reps: best[ex].reps, d: best[ex].e - bestBefore[ex] })).sort((a, b) => b.d - a.d);
  // dieta (tylko dni do dziś)
  const D = rows_(ss, SH.DIET, 3).filter(r => r[0] && inW(key_(r[0])) && key_(r[0]) <= todayK && Number(r[1]) > 0);
  const kcal = avg_(D.map(r => Number(r[1]))), prot = avg_(D.map(r => Number(r[2])));
  // kroki i sen
  const DL = rows_(ss, SH.DAILY, 3).filter(r => r[0] && inW(key_(r[0])));
  const steps = avg_(DL.map(r => r[1] === '' ? NaN : Number(r[1]))), sleep = avg_(DL.map(r => r[2] === '' ? NaN : Number(r[2])));
  // pomiary
  const M = rows_(ss, SH.MEAS, 8).filter(r => r[0]);
  // komentarz trenera
  const REP = ss.getSheetByName(SH.REP); let coach = null, coachRow = null;
  if (REP && REP.getLastRow() > 1) REP.getRange(2, 1, REP.getLastRow() - 1, 5).getValues().forEach((r, i) => { if (r[0] && key_(r[0]) === from) { coach = { text: String(r[2] || ''), tips: String(r[3] || '') }; coachRow = i + 2; } });
  return { from: from, to: to, mon: mon, sun: sun, wNow: wNow, wPrev: wPrev, wLast: wLast, wDays: W.filter(x => inW(x.k)).length,
    trainings: TR.map(r => ({ day: r[2], date: key_(r[1]), sets: r[6], vol: r[7], min: r[5] })), sets: seW.length, vol: seW.reduce((a, r) => a + (Number(r[8]) || 0), 0),
    muscles: muscles, prs: prs, kcal: kcal, prot: prot, dietDays: D.length, steps: steps, sleep: sleep, dailyDays: DL.length,
    lastMeas: M.length ? M[M.length - 1] : null, firstMeas: M.length ? M[0] : null, coach: coach, coachRow: coachRow };
}

function sendWeeklyReport() {
  const ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty('SSID'));
  const st = weekStats_(ss);
  const html = reportHtml_(st, ss.getUrl());
  const fmt = d => Utilities.formatDate(d, TZ, 'd.MM');
  MailApp.sendEmail({ to: REPORT_TO, subject: 'Żelazny Dziennik · tydzień ' + fmt(st.mon) + ' do ' + fmt(st.sun), htmlBody: html, name: 'Żelazny Dziennik' });
  if (st.coachRow) ss.getSheetByName(SH.REP).getRange(st.coachRow, 5).setValue(new Date());
}

function esc_(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function reportHtml_(st, sheetUrl) {
  const NAVY = '#00283D', BLUE = '#0079C2', PINK = '#EE1264', TEAL = '#00B8C7', MUTED = '#5B6770', LINE = '#E3E7EA', BG = '#F5F5F5';
  const font = "font-family:'Source Sans 3','Source Sans Pro',Arial,sans-serif;";
  const fmt = d => Utilities.formatDate(d, TZ, 'd MMM');
  const rate = (st.wNow !== null && st.wPrev !== null) ? st.wNow - st.wPrev : null;
  let rateTxt = 'za mało danych', rateCol = MUTED;
  if (rate !== null) { if (rate < 0.2) { rateTxt = 'za wolno'; rateCol = '#B26B00'; } else if (rate <= 0.35) { rateTxt = 'w celu'; rateCol = BLUE; } else if (rate <= 0.5) { rateTxt = 'szybko'; rateCol = '#B26B00'; } else { rateTxt = 'za szybko'; rateCol = PINK; } }
  const tile = (label, value, sub, col) => '<td width="33%" style="padding:6px;vertical-align:top"><div style="background:#fff;border:1px solid ' + LINE + ';padding:12px 12px 10px">'
    + '<div style="' + font + 'font-size:11px;color:' + MUTED + ';text-transform:uppercase;letter-spacing:.06em;font-weight:700">' + label + '</div>'
    + '<div style="' + font + 'font-size:26px;font-weight:800;color:' + (col || NAVY) + ';line-height:1.2;margin-top:2px">' + value + '</div>'
    + '<div style="' + font + 'font-size:12px;color:' + MUTED + '">' + sub + '</div></div></td>';
  const h3 = t => '<div style="' + font + 'font-size:17px;font-weight:800;color:' + NAVY + ';margin:22px 0 8px">' + t + '</div>';
  let h = '<div style="background:' + BG + ';padding:16px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;background:' + BG + '"><tr><td style="padding:0 10px">';
  h += '<div style="background:' + NAVY + ';padding:18px 18px 16px;border-bottom:4px solid ' + PINK + '"><div style="' + font + 'color:#B9C7D0;font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:700">Raport tygodnia</div>'
    + '<div style="' + font + 'color:#fff;font-size:24px;font-weight:800;margin-top:2px">Żelazny Dziennik</div><div style="' + font + 'color:#B9C7D0;font-size:14px">' + fmt(st.mon) + ' do ' + fmt(st.sun) + '</div></div>';
  // kafle
  h += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px"><tr>'
    + tile('Waga śr.', f1_(st.wNow) + ' kg', st.wDays + ' wpisów' + (st.wLast ? ', ostatni ' + f1_(st.wLast) : ''))
    + tile('Tempo', rate === null ? '–' : (rate > 0 ? '+' : '') + f1_(rate, 2) + ' kg', '<span style="color:' + rateCol + ';font-weight:700">' + rateTxt + '</span> · cel 0,2 do 0,35', rateCol)
    + tile('Treningi', st.trainings.length + ' / 5', st.sets + ' serii · ' + f1_(st.vol / 1000) + ' t') + '</tr><tr>'
    + tile('Kalorie śr.', st.kcal === null ? '–' : Math.round(st.kcal), 'cel 3300 · ' + st.dietDays + ' dni')
    + tile('Białko śr.', st.prot === null ? '–' : Math.round(st.prot) + ' g', 'cel 170 g', st.prot !== null && st.prot < 170 ? PINK : NAVY)
    + tile('Kroki · sen', st.steps === null ? '–' : Math.round(st.steps).toLocaleString('pl-PL'), 'sen śr. ' + (st.sleep === null ? '–' : f1_(st.sleep) + ' h')) + '</tr></table>';
  // komentarz trenera
  if (st.coach && st.coach.text) {
    h += h3('Komentarz trenera') + '<div style="background:#fff;border:1px solid ' + LINE + ';border-left:4px solid ' + BLUE + ';padding:14px 16px">'
      + st.coach.text.split(/\n+/).filter(Boolean).map(p => '<p style="' + font + 'font-size:15px;line-height:1.5;color:#1D1D1D;margin:0 0 10px">' + esc_(p) + '</p>').join('');
    const tips = st.coach.tips.split(/\n+/).map(x => x.replace(/^[-•\d.\s]+/, '').trim()).filter(Boolean);
    if (tips.length) h += '<div style="' + font + 'font-size:12px;font-weight:700;color:' + PINK + ';text-transform:uppercase;letter-spacing:.06em;margin:4px 0 6px">Na ten tydzień</div>'
      + tips.map(x => '<div style="' + font + 'font-size:15px;line-height:1.45;color:' + NAVY + ';padding:6px 0;border-top:1px solid ' + LINE + '">→ ' + esc_(x) + '</div>').join('');
    h += '</div>';
  }
  // treningi
  h += h3('Treningi');
  if (st.trainings.length) h += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid ' + LINE + '">'
    + st.trainings.map(t => '<tr><td style="' + font + 'padding:9px 12px;border-bottom:1px solid ' + LINE + ';font-weight:700;color:' + NAVY + '">' + esc_(t.day) + '</td><td style="' + font + 'padding:9px 12px;border-bottom:1px solid ' + LINE + ';color:' + MUTED + '">' + Utilities.formatDate(toDate_(t.date), TZ, 'EEE d.MM') + '</td><td style="' + font + 'padding:9px 12px;border-bottom:1px solid ' + LINE + ';text-align:right;color:#1D1D1D">' + t.sets + ' serii · ' + t.min + ' min</td></tr>').join('') + '</table>';
  else h += '<div style="' + font + 'color:' + MUTED + ';background:#fff;border:1px dashed ' + LINE + ';padding:12px">Brak zapisanych treningów w tym tygodniu.</div>';
  // partie
  const order = ['Klatka', 'Plecy', 'Barki', 'Biceps', 'Triceps', 'Nogi'];
  const maxM = Math.max(1, ...order.map(m => st.muscles[m] || 0));
  if (st.sets) h += h3('Serie na partie') + '<div style="background:#fff;border:1px solid ' + LINE + ';padding:10px 14px">' + order.map(m => { const n = st.muscles[m] || 0; const col = (m === 'Biceps' || m === 'Triceps') ? PINK : BLUE;
    return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:5px 0"><tr><td width="80" style="' + font + 'font-size:13px;color:' + NAVY + ';font-weight:700">' + m + '</td><td><div style="background:' + BG + ';height:10px"><div style="background:' + col + ';height:10px;width:' + Math.round(n / maxM * 100) + '%"></div></div></td><td width="36" style="' + font + 'font-size:13px;text-align:right;color:#1D1D1D">' + n + '</td></tr></table>'; }).join('')
    + '<div style="' + font + 'font-size:12px;color:' + MUTED + ';margin-top:4px">Priorytet bloku: ramiona (różowe), cel ok. 14 serii tygodniowo na biceps i triceps.</div></div>';
  // rekordy
  if (st.prs.length) h += h3('Rekordy tygodnia') + '<div style="background:#fff;border:1px solid ' + LINE + ';padding:4px 14px">' + st.prs.slice(0, 6).map(p => '<div style="' + font + 'font-size:15px;padding:8px 0;border-bottom:1px solid ' + LINE + '"><b style="color:' + NAVY + '">' + esc_(p.ex) + '</b> · ' + f1_(p.kg) + ' kg × ' + p.reps + ' <span style="color:' + TEAL + ';font-weight:700">+' + f1_(p.d) + ' kg e1RM</span></div>').join('') + '</div>';
  // pomiary
  if (st.lastMeas) { const L = st.lastMeas, F = st.firstMeas; const nm = ['Ramię', 'Przedramię', 'Klatka', 'Talia', 'Udo', 'Łydka'];
    h += h3('Ostatnie pomiary · ' + Utilities.formatDate(L[0], TZ, 'd.MM')) + '<div style="background:#fff;border:1px solid ' + LINE + ';padding:10px 14px;' + font + 'font-size:14px;color:#1D1D1D">'
      + nm.map((n, i) => L[i + 1] === '' ? '' : n + ' <b>' + f1_(Number(L[i + 1])) + '</b>' + (F && F[i + 1] !== '' && F !== L ? ' <span style="color:' + MUTED + '">(' + ((L[i + 1] - F[i + 1]) >= 0 ? '+' : '') + f1_(L[i + 1] - F[i + 1]) + ')</span>' : '')).filter(Boolean).join(' · ') + '</div>'; }
  h += '<div style="text-align:center;margin:24px 0 8px"><a href="' + APP_URL + '" style="' + font + 'display:inline-block;background:' + NAVY + ';color:#fff;text-decoration:none;font-weight:700;padding:12px 26px;border-radius:999px">Otwórz apkę</a></div>'
    + '<div style="' + font + 'text-align:center;font-size:12px;color:' + MUTED + '"><a href="' + sheetUrl + '" style="color:' + BLUE + '">Arkusz z danymi</a> · raport wysyła się w każdą niedzielę</div>';
  h += '</td></tr></table></div>';
  return h;
}
