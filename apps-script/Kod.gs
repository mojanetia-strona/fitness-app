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
const SH = { DASH:'Dashboard', TRAIN:'Treningi', SETS:'Serie', WEIGHT:'Waga', MEAS:'Pomiary', REC:'Rekordy', WEEK:'Tygodnie', PLAN:'Plan', CAT:'Catering', FOOD:'Jedzenie', DIET:'Dieta' };
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
  buildPlan_(ss);
  buildWeeks_(ss);
  buildRecords_(ss);
  rewriteWeightFormulas_(ss.getSheetByName(SH.WEIGHT));
  buildDashboard_(ss, dash);

  // kolejność i sprzątanie
  [SH.DASH, SH.DIET, SH.TRAIN, SH.SETS, SH.WEIGHT, SH.MEAS, SH.CAT, SH.FOOD, SH.REC, SH.WEEK, SH.PLAN].forEach((n, i) => {
    ss.setActiveSheet(ss.getSheetByName(n)); ss.moveActiveSheet(i + 1);
  });
  ['Arkusz1','Sheet1'].forEach(n => { const s = ss.getSheetByName(n); if (s && s.getLastRow() === 0) ss.deleteSheet(s); });
  ss.getSheetByName(SH.WEEK).setTabColor(C.grey);
  ss.setActiveSheet(dash);
  showToken();
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
  if (p.action === 'diet') return json_(Object.assign({ ok: true }, dietRange_(ss, p.from || '', p.to || '')));
  return json_({ ok: true, name: ss.getName() });
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.token !== getToken_()) return json_({ ok: false, error: 'Zły token' });
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
  return { catering: catering, foods: foods };
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
