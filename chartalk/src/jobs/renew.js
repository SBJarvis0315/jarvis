// 매일 한 번 돌리는 정기결제 배치.
// 예) crontab: 5 3 * * * cd /srv/chartalk && npm run renew >> logs/renew.log 2>&1
import { loadEnv } from '../config.js';
loadEnv();
const { openDb } = await import('../db.js');
const { runRenewals } = await import('../billing.js');

openDb();
const results = await runRenewals();
const ok = results.filter((r) => r.ok);
console.log(`[renew] ${new Date().toISOString()} 대상 ${results.length}건 · 성공 ${ok.length} · 실패 ${results.length - ok.length}`);
for (const r of results.filter((x) => !x.ok)) console.log(`  실패: ${r.email} (${r.error})`);
process.exit(0);
