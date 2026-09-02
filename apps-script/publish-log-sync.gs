/**
 * 노션 콘텐츠 플래너 → 고객사 마스터 시트 '발행 로그' 자동 기입
 *
 * 플래너에서 발행이 끝난 행(URL이 채워진 행)을 골라 마스터 시트에 한 줄씩 옮겨 적습니다.
 *
 * ── 이 스크립트는 마스터 시트에 붙이지 마세요 ──
 * 마스터 시트는 고객사와 공유하는 문서입니다. 시트에 붙는(바운드) 스크립트는 그 시트를
 * 편집할 수 있는 사람이면 누구나 열어볼 수 있어서, 아래 NOTION_TOKEN 이 그대로 노출됩니다.
 * script.google.com 에서 만든 **독립 스크립트**로 두고, 시트는 openById 로 열어 씁니다.
 * (설치 방법은 apps-script/README.md 참고)
 *
 * 시트를 다루는 규칙 두 가지:
 *   · 덧쓰지 않습니다 — 제목과 게재본이 둘 다 빈 줄에만 씁니다.
 *   · 게재본 주소로 중복을 걸러, 몇 번을 돌려도 같은 글이 두 줄이 되지 않습니다.
 */

/** 고객사 대응표. 새 고객사는 여기에 한 덩어리 더 넣으면 됩니다. */
var TARGETS = [
  {
    client: '제로클리닉',
    // 플래너 DB ID (노션 주소의 32자리 값)
    plannerDb: '37b68fa206ff80c5a520e7500fac7d0e',
    // 스프레드시트 ID (주소의 /d/ 와 /edit 사이)
    spreadsheetId: '1fGmSvJzA9y46KQTuKEnuSlknwPkcJcDOtzUq9Fe1Sek',
    sheetName: '7) 발행 로그',
    // 왼쪽이 시트 헤더, 오른쪽이 노션 속성 이름
    columns: { date: '날짜', type: '콘텐츠 유형', title: '제목', url: '게재본' },
    props: { date: '발행 예정일', type: '유형', title: '제목', url: 'URL' }
  }
];

var NOTION_VERSION = '2022-06-28';
var KEYS = ['date', 'type', 'title', 'url'];
/** 헤더 줄을 찾을 때 훑어볼 윗줄 수. 안내 문구가 몇 줄 붙어 있어도 넉넉합니다. */
var HEADER_SCAN_ROWS = 20;

/** 트리거가 부르는 함수. 대상 고객사를 차례로 처리합니다. */
function syncPublishLog() {
  var token = PropertiesService.getScriptProperties().getProperty('NOTION_TOKEN');
  if (!token) {
    throw new Error('스크립트 속성에 NOTION_TOKEN 이 없습니다. (프로젝트 설정 → 스크립트 속성)');
  }

  TARGETS.forEach(function (target) {
    try {
      var added = syncOne(target, token);
      Logger.log('[' + target.client + '] ' + added.length + '건 기입' +
        (added.length ? ' — ' + added.map(function (e) { return e.title; }).join(' / ') : ''));
    } catch (err) {
      // 한 고객사가 넘어져도 나머지는 계속 진행합니다.
      Logger.log('[' + target.client + '] 실패: ' + err.message);
    }
  });
}

/** 한 고객사 처리. 새로 기입한 항목 목록을 돌려줍니다. */
function syncOne(target, token) {
  var entries = collect(queryPlanner(target.plannerDb, token), target);

  var sheet = SpreadsheetApp.openById(target.spreadsheetId).getSheetByName(target.sheetName);
  if (!sheet) throw new Error("'" + target.sheetName + "' 탭을 찾을 수 없습니다.");

  var values = sheet.getDataRange().getValues();
  var header = findHeader(values, target);
  var plan = planWrites(values, header, entries);

  plan.forEach(function (item) {
    KEYS.forEach(function (key) {
      sheet.getRange(item.row + 1, header.cols[key] + 1).setValue(item.entry[key]);
    });
  });

  return plan.map(function (item) { return item.entry; });
}

// ─────────────────────────────────────────────────────────────── 노션 읽기

function queryPlanner(databaseId, token) {
  var rows = [];
  var cursor = null;

  do {
    var payload = { page_size: 100 };
    if (cursor) payload.start_cursor = cursor;

    var res = UrlFetchApp.fetch('https://api.notion.com/v1/databases/' + databaseId + '/query', {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token, 'Notion-Version': NOTION_VERSION },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

    if (res.getResponseCode() !== 200) {
      throw new Error('노션 요청 실패 ' + res.getResponseCode() + ' — ' +
        res.getContentText().slice(0, 300));
    }

    var data = JSON.parse(res.getContentText());
    rows = rows.concat(data.results);
    cursor = data.has_more ? data.next_cursor : null;
  } while (cursor);

  return rows;
}

function readText(prop) {
  if (!prop) return '';
  var nodes = prop.title || prop.rich_text || [];
  return nodes.map(function (n) { return n.plain_text || ''; }).join('').trim();
}

function readSelect(prop) {
  var value = prop && (prop.select || prop.status);
  return value ? value.name : '';
}

function readDate(prop) {
  var value = prop && prop.date;
  return value && value.start ? value.start.slice(0, 10) : '';
}

function readUrl(prop) {
  return (prop && prop.url) ? String(prop.url).trim() : '';
}

/**
 * 플래너 행 → 시트에 옮길 값.
 *
 * URL이 채워진 행을 발행이 끝난 것으로 봅니다. 진행 상황은 보지 않습니다 —
 * 플래너마다 상태 이름이 다르고(발행완료 · 게재완료), URL이 적혔다는 것 자체가
 * 게재됐다는 뜻이기 때문입니다.
 */
function collect(rows, target) {
  var entries = [];

  rows.forEach(function (row) {
    var props = row.properties || {};
    var entry = {
      title: readText(props[target.props.title]),
      type: readSelect(props[target.props.type]),
      date: readDate(props[target.props.date]),
      url: readUrl(props[target.props.url])
    };

    // 네 칸이 모두 차야 옮깁니다. 하나라도 비면 사람이 플래너를 채워야 합니다.
    if (entry.url && entry.title && entry.type && entry.date) entries.push(entry);
  });

  // 오래된 것부터 쌓이도록 정렬합니다. 같은 날짜는 제목 순으로 고정해 두면
  // 실행할 때마다 순서가 흔들리지 않습니다.
  entries.sort(function (a, b) {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1;
    return a.title < b.title ? -1 : (a.title > b.title ? 1 : 0);
  });

  return entries;
}

// ─────────────────────────────────────────────────────────────── 시트 다루기

function cellAt(values, row, col) {
  if (row >= values.length) return '';
  var value = values[row][col];
  return value === null || value === undefined ? '' : String(value).trim();
}

/** 날짜·콘텐츠 유형·제목·게재본이 한 줄에 모두 있는 줄을 위에서부터 찾습니다. */
function findHeader(values, target) {
  var limit = Math.min(values.length, HEADER_SCAN_ROWS);

  for (var row = 0; row < limit; row++) {
    var cols = {};
    var found = 0;

    KEYS.forEach(function (key) {
      for (var col = 0; col < values[row].length; col++) {
        if (String(values[row][col]).trim() === target.columns[key]) {
          cols[key] = col;
          found++;
          return;
        }
      }
    });

    if (found === KEYS.length) return { row: row, cols: cols };
  }

  throw new Error("'" + target.sheetName + "' 에서 헤더 줄을 찾지 못했습니다. " +
    KEYS.map(function (k) { return target.columns[k]; }).join(' · ') + ' 이(가) 한 줄에 모두 있어야 합니다.');
}

/** 같은 글인지 비교하기 위한 형태. 앞뒤 공백과 끝의 빗금 차이는 무시합니다. */
function normalizeUrl(url) {
  return String(url || '').trim().replace(/\/+$/, '');
}

/**
 * 채울 줄 계획. 빈 줄부터 쓰고, 모자라면 표 아래에 이어 붙입니다.
 * 이미 무언가 적혀 있는 줄은 건드리지 않습니다.
 */
function planWrites(values, header, entries) {
  var already = {};
  var blanks = [];

  for (var row = header.row + 1; row < values.length; row++) {
    var url = cellAt(values, row, header.cols.url);
    if (url) already[normalizeUrl(url)] = true;

    // 유형만 미리 적어둔 예정 줄이 표에 깔려 있습니다. 제목과 게재본이 둘 다 비어야
    // 아직 아무도 쓰지 않은 줄입니다.
    if (!url && !cellAt(values, row, header.cols.title)) blanks.push(row);
  }

  var nextRow = values.length;
  var plan = [];

  entries.forEach(function (entry) {
    var key = normalizeUrl(entry.url);
    if (already[key]) return;
    already[key] = true;

    plan.push({ row: blanks.length ? blanks.shift() : nextRow++, entry: entry });
  });

  return plan;
}
