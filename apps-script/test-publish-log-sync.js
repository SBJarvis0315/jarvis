/**
 * publish-log-sync.gs 의 판정 로직을 구글에 올리기 전에 확인합니다.
 *
 *     node apps-script/test-publish-log-sync.js
 *
 * 시트·노션을 건드리지 않고, 실제 마스터 시트와 같은 모양의 표에 대고
 * 어느 줄에 무엇이 들어가는지만 봅니다.
 */
const fs = require('fs');
const vm = require('vm');
const ctx = { Logger: { log: () => {} } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(require("path").join(__dirname, "publish-log-sync.gs"), 'utf8'), ctx);
const { collect, findHeader, planWrites, normalizeUrl, TARGETS } = ctx;
const t = TARGETS[0];

let fails = 0;
function ok(name, cond, extra) {
  if (cond) { console.log('  ✓ ' + name); } else { fails++; console.log('  ✗ ' + name + (extra ? '  → ' + JSON.stringify(extra) : '')); }
}

function page(o) {
  o = o || {};
  return { properties: {
    '제목': { title: [{ plain_text: o.title === undefined ? '제목' : o.title }] },
    '유형': { select: o.type === '' ? null : { name: o.type || '숏폼' } },
    '발행 예정일': { date: o.date === '' ? null : { start: (o.date || '2026-07-29') } },
    'URL': { url: o.url === '' ? null : (o.url || 'https://ex.test/1') }
  } };
}

// 실제 마스터 시트 모양: 2행 안내문구, 3행 헤더, 4~29행은 유형만 미리 적힌 예정 줄
function sheet(n) {
  const v = [
    ['', '', '', '', ''],
    ['', '', '', '- 월 발행 건수: 롱폼 6건 / 숏폼 20건', ''],
    ['', '날짜', '콘텐츠 유형', '제목', '게재본']
  ];
  for (let i = 0; i < n; i++) v.push(['', '', i < 6 ? '롱폼' : '숏폼', '', '']);
  return v;
}

console.log('collect');
ok('URL 없는 행은 거른다', collect([page(), page({ url: '' })], t).length === 1);
ok('유형 빈 행은 거른다', collect([page({ type: '' })], t).length === 0);
ok('날짜 빈 행은 거른다', collect([page({ date: '' })], t).length === 0);
const sorted = collect([page({ title: '나중', date: '2026-07-29', url: 'https://ex.test/2' }),
                        page({ title: '먼저', date: '2026-06-10' })], t);
ok('오래된 것부터 정렬', sorted.map(e => e.title).join(',') === '먼저,나중', sorted.map(e => e.title));
ok('date 는 앞 10자리만', collect([page({ date: '2026-07-29T09:00:00+09:00' })], t)[0].date === '2026-07-29');

console.log('findHeader');
const h = findHeader(sheet(26), t);
ok('헤더는 3행(0기준 2)', h.row === 2, h.row);
ok('열은 B~E(1~4)', JSON.stringify(h.cols) === JSON.stringify({ date: 1, type: 2, title: 3, url: 4 }), h.cols);
let threw = false; try { findHeader([['아무것도', '없음']], t); } catch (e) { threw = /헤더 줄을 찾지 못했습니다/.test(e.message); }
ok('헤더 없으면 사유를 알려준다', threw);

console.log('planWrites');
const e1 = { date: '2026-06-10', type: '숏폼', title: '가', url: 'https://ex.test/1' };
const e2 = { date: '2026-07-14', type: '롱폼', title: '나', url: 'https://ex.test/2' };

let v = sheet(26);
let p = planWrites(v, findHeader(v, t), [e1, e2]);
ok('예정 줄부터 채운다 (4·5행)', p.map(x => x.row + 1).join(',') === '4,5', p.map(x => x.row + 1));

v = sheet(1);
p = planWrites(v, findHeader(v, t), [e1, e2]);
ok('예정 줄이 모자라면 표 아래로', p.map(x => x.row + 1).join(',') === '4,5', p.map(x => x.row + 1));

v = sheet(26);
v[3] = ['', '2026-01-01', '롱폼', '손으로 적은 글', 'https://ex.test/hand'];
p = planWrites(v, findHeader(v, t), [e1]);
ok('사람이 적은 줄은 건너뛴다', p[0].row + 1 === 5, p.map(x => x.row + 1));

v = sheet(26);
v[3] = ['', '2026-06-10', '숏폼', '가', 'https://ex.test/1/'];
p = planWrites(v, findHeader(v, t), [e1, e2]);
ok('이미 적힌 주소는 다시 안 넣는다 (끝 빗금 무시)', p.length === 1 && p[0].entry.title === '나', p.map(x => x.entry.title));

v = sheet(26);
p = planWrites(v, findHeader(v, t), [e1, e1]);
ok('같은 실행 안에서도 중복은 한 번만', p.length === 1);

ok('normalizeUrl', normalizeUrl(' https://a/b/ ') === 'https://a/b');

console.log(fails ? '\n실패 ' + fails + '건' : '\n전부 통과');
process.exit(fails ? 1 : 0);
