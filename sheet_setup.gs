/**
 * ════════════════════════════════════════════════════════════════
 *  TREND PULSE v2 — Google Sheet Setup (Apps Script)
 * ════════════════════════════════════════════════════════════════
 *  ব্যবহারের নিয়ম:
 *  1. তোমার Google Sheet খোলো
 *  2. Extensions → Apps Script
 *  3. পুরনো কোড মুছে এই পুরো কোডটা পেস্ট করো
 *  4. উপরে ফাংশন লিস্ট থেকে "setupTrendPulse" বেছে ▶ Run চাপো
 *  5. প্রথমবার পারমিশন চাইলে Allow করে দাও
 *
 *  এই স্ক্রিপ্ট কোনো ডেটা ডিলিট করে না — যতবার খুশি চালাতে পারো।
 * ════════════════════════════════════════════════════════════════
 */

const HEADERS = ['Date', 'Platform', 'Topic', 'Popularity (Searches/Views)',
                 'Description', 'Link', 'Source'];

const CATEGORIES = [
  { name: 'Technology',    color: '#1a73e8', emoji: '💻' },  // নীল
  { name: 'Islamic',       color: '#188038', emoji: '🕌' },  // সবুজ
  { name: 'Trending (US)', color: '#d93025', emoji: '🔥' }   // লাল
];

const COL_WIDTHS = [95, 110, 420, 160, 420, 260, 130];

function setupTrendPulse() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // ---- ১) তিনটি ক্যাটেগরি ট্যাব তৈরি/সাজানো ----
  CATEGORIES.forEach(function (cat, idx) {
    let sh = ss.getSheetByName(cat.name);
    if (!sh) {
      sh = ss.insertSheet(cat.name, idx);
    }
    styleCategorySheet_(sh, cat);
  });

  // ---- ২) ড্যাশবোর্ড ট্যাব ----
  buildDashboard_(ss);

  // ---- ৩) খালি ডিফল্ট "Sheet1" থাকলে মুছে দাও ----
  const def = ss.getSheetByName('Sheet1');
  if (def && def.getLastRow() === 0 && ss.getSheets().length > 1) {
    ss.deleteSheet(def);
  }

  // ড্যাশবোর্ডকে প্রথম ট্যাব বানাও
  const dash = ss.getSheetByName('📊 Dashboard');
  if (dash) { ss.setActiveSheet(dash); ss.moveActiveSheet(1); }

  SpreadsheetApp.flush();
  SpreadsheetApp.getUi().alert('✅ Trend Pulse শিট সেটআপ সম্পন্ন!\n\n' +
    'এখন GitHub → Actions → "Daily Trend Fetch" → Run workflow চালালেই ' +
    'ডেটা আসা শুরু হবে।');
}

function styleCategorySheet_(sh, cat) {
  // হেডার রো
  sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS])
    .setFontWeight('bold')
    .setFontColor('#ffffff')
    .setBackground(cat.color)
    .setFontSize(10)
    .setVerticalAlignment('middle');
  sh.setRowHeight(1, 34);
  sh.setFrozenRows(1);
  sh.setTabColor(cat.color);

  // কলামের চওড়া
  COL_WIDTHS.forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });

  // Date কলাম সবসময় yyyy-mm-dd ফরম্যাটে (রিটেনশন সিস্টেমের জন্য জরুরি)
  sh.getRange('A2:A').setNumberFormat('yyyy-mm-dd');

  // টেক্সট যেন ছড়িয়ে না পড়ে
  sh.getRange(2, 1, sh.getMaxRows() - 1, HEADERS.length)
    .setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP)
    .setVerticalAlignment('middle');

  // ফিল্টার (আগে থেকে থাকলে বাদ)
  if (!sh.getFilter()) {
    sh.getRange(1, 1, sh.getMaxRows(), HEADERS.length).createFilter();
  }

  // Popularity কলাম হাইলাইট
  sh.getRange('D2:D').setFontWeight('bold').setFontColor(cat.color);

  // একটার-পর-একটা রো হালকা রঙ (banding)
  const dataRange = sh.getRange(1, 1, sh.getMaxRows(), HEADERS.length);
  if (sh.getBandings().length === 0) {
    dataRange.applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, false, false);
  }
}

function buildDashboard_(ss) {
  const name = '📊 Dashboard';
  let dash = ss.getSheetByName(name);
  if (!dash) dash = ss.insertSheet(name, 0);
  dash.clear();
  dash.setTabColor('#f9ab00');
  dash.setHiddenGridlines(true);

  // শিরোনাম
  dash.getRange('B2').setValue('📈 TREND PULSE — Daily Trending Topics (US)')
      .setFontSize(20).setFontWeight('bold').setFontColor('#1a73e8');
  dash.getRange('B3').setValue('প্রতিদিন সকাল ৯টায় অটো-আপডেট • ৬০ দিনের ডেটা সংরক্ষিত')
      .setFontSize(10).setFontColor('#5f6368');

  // সারাংশ কার্ড
  const cards = [
    ['B5', 'আজকের নতুন টপিক',
     '=SUMPRODUCT((TEXT(Technology!A2:A500,"yyyy-mm-dd")=TEXT(TODAY(),"yyyy-mm-dd"))*1)' +
     '+SUMPRODUCT((TEXT(Islamic!A2:A500,"yyyy-mm-dd")=TEXT(TODAY(),"yyyy-mm-dd"))*1)' +
     '+SUMPRODUCT((TEXT(\'Trending (US)\'!A2:A500,"yyyy-mm-dd")=TEXT(TODAY(),"yyyy-mm-dd"))*1)',
     '#1a73e8'],
    ['D5', 'মোট টপিক জমা আছে',
     '=COUNTA(Technology!C2:C)+COUNTA(Islamic!C2:C)+COUNTA(\'Trending (US)\'!C2:C)',
     '#188038'],
    ['F5', 'সর্বশেষ আপডেট',
     '=IFERROR(TEXT(MAX(Technology!A2:A;Islamic!A2:A;\'Trending (US)\'!A2:A),"yyyy-mm-dd"),"—")',
     '#d93025']
  ];
  cards.forEach(function (c) {
    const cell = dash.getRange(c[0]);
    cell.setValue(c[1]).setFontSize(9).setFontColor('#5f6368');
    cell.offset(1, 0).setFormula(c[2])
        .setFontSize(18).setFontWeight('bold').setFontColor(c[3]);
    dash.getRange(cell.getRow(), cell.getColumn(), 2, 2)
        .setBackground('#f8f9fa');
  });

  // প্রতিটি ক্যাটেগরির লেটেস্ট ১০ টপিক
  let row = 9;
  CATEGORIES.forEach(function (cat) {
    dash.getRange(row, 2).setValue(cat.emoji + ' ' + cat.name + ' — লেটেস্ট টপিক')
        .setFontWeight('bold').setFontSize(12).setFontColor('#ffffff')
        .setBackground(cat.color);
    dash.getRange(row, 2, 1, 5).setBackground(cat.color);

    const q = "=IFERROR(QUERY('" + cat.name + "'!A2:G500, " +
      "\"select A, B, C, D where C is not null order by A desc limit 10\", 0), " +
      "\"এখনো ডেটা আসেনি — GitHub Actions চালাও\")";
    dash.getRange(row + 1, 2).setFormula(q);
    dash.getRange(row + 1, 2, 10, 5).setFontSize(9)
        .setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP);
    row += 13;
  });

  // কলাম চওড়া
  dash.setColumnWidth(1, 25);
  dash.setColumnWidth(2, 110);
  dash.setColumnWidth(3, 120);
  dash.setColumnWidth(4, 430);
  dash.setColumnWidth(5, 170);
  dash.setColumnWidth(6, 170);
}
